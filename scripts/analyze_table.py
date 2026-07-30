#!/usr/bin/env python3
"""
analyze_table.py — аналитическая нога табличного разбора (G.3).

Разделение с `extract_text.py` (см. `shared/ocr.md` §5а): приём таблицу **не
анализирует** — он кладёт в зеркало структурную сводку. Здесь считается то, что
нужно `study-evidence`: арифметика, сверки, флаги. Эвристика чтения (поиск шапки,
нормализация ячеек) **импортируется** из `extract_text.py`, а не дублируется —
иначе приём и анализ разойдутся в понимании того, где у таблицы шапка.

Принцип: скрипт **проверяет**, а не выдумывает. Он не назначает формулу расчёта —
он подбирает ту модель, которая сходится с данными, и честно флагует, если не
сходится ни одна. Все цифры отдаются с адресом клетки (лист + строка + колонка):
для таблицы это то же, что «л. 4» для бумажного документа.

Сети не касается. Ключевая ставка **не сверяется** здесь: скрипт возвращает
использованные в расчёте ставки списком, сверку с cbr.ru делает агент по канону
`shared/conventions.md` → «Расчёт денежных требований: дата начала и ставка (F.10)».

Профили (первая версия — по решению Сюзерена 2026-07-30):
    debt-calc   — расчёт долга / неустойки / процентов (наш и оппонента)
    statement   — выписка по счёту: обороты, полнота, дубли, дробление, получатели
    (registry · payments — следующими шагами)

Запуск:
    python3 analyze_table.py <файл.xlsx> --profile debt-calc [--sheet "Лист"]
                             [--tolerance 1.0] [--out-dir DIR]

Выход: JSON. Ключи: profile · sheet · columns · formula · rows · findings ·
totals · rates · periods. Ненайденное — `null`, не догадка.
"""

import sys
import os
import json
import re
import datetime as dt
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from extract_text import (                      # noqa: E402  (общая эвристика чтения)
    _cell_str, _cell_empty, _find_header_row, _pad_row, _is_date_like,
    TABLE_MAX_SCAN_ROWS,
)

# --- параметры ---------------------------------------------------------------

DEFAULT_TOLERANCE = 1.0        # ₽ — абсолютный допуск на строку
REL_TOLERANCE = 0.005          # 0,5 % — относительный допуск
MIN_ROWS_FOR_FORMULA = 2       # меньше — модель не выводим, только проверяем даты/итоги

# --- распознавание колонок --------------------------------------------------

COLUMN_MARKERS = {
    "base":      ("сумма долга", "задолженность", "основной долг", "база", "сумма задолж",
                  "недоимка", "сумма основного", "остаток долга", "долг"),
    "rate":      ("ставка", "%", "процент", "ключевая", "рефинанс"),
    "days":      ("дней", "дни", "кол-во дней", "количество дней", "число дней",
                  "период просрочки", "просрочка, дн"),
    "date_from": ("с ", "дата с", "начало", "период с", "с даты", "дата начала", "от"),
    "date_to":   ("по ", "дата по", "окончание", "период по", "по дату", "дата окончания",
                  "конец"),
    "amount":    ("пени", "неустойка", "проценты", "сумма пени", "начислено",
                  "к взысканию", "итого по строке", "сумма процентов", "размер"),
    "paid":      ("оплачено", "погашено", "платеж", "платёж", "оплата", "внесено"),
}


def _norm_header(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().lower())


def detect_columns(headers: list, rows: list) -> dict:
    """Индексы значимых колонок. Сначала по заголовку, затем добор по типу данных."""
    found = {}
    norm = [_norm_header(h) for h in headers]

    for key, markers in COLUMN_MARKERS.items():
        for idx, head in enumerate(norm):
            if not head or idx in found.values():
                continue
            if any(m in head for m in markers):
                found[key] = idx
                break

    # Добор по данным: даты — колонки, где преобладают date-значения.
    date_cols = []
    for col in range(len(headers)):
        values = [r[col] for r in rows if col < len(r)]
        dates = [v for v in values if _is_date_like(v)]
        if dates and len(dates) >= max(2, len([v for v in values if not _cell_empty(v)]) // 2):
            date_cols.append(col)
    if "date_from" not in found and date_cols:
        found["date_from"] = date_cols[0]
    if "date_to" not in found and len(date_cols) > 1:
        found["date_to"] = date_cols[1]

    return found


def _num(value):
    """Число из ячейки. Текстовые «1 234,56 ₽» и неразрывные пробелы — тоже числа.

    Без этого суммы, сохранённые как текст (обычное дело для выгрузок), молча
    станут нулями — а нуль в расчёте выглядит как «сошлось».
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value)
    s = s.replace(" ", " ").replace(" ", " ")
    s = re.sub(r"[₽руб.\s]", "", s, flags=re.IGNORECASE)
    s = s.replace(",", ".")
    if not re.fullmatch(r"-?\d+(\.\d+)?%?", s or ""):
        return None
    return float(s.rstrip("%"))


def _as_date(value):
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    if isinstance(value, str):
        m = re.search(r"(\d{2})[.\-/](\d{2})[.\-/](\d{4})", value)
        if m:
            try:
                return dt.date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
            except ValueError:
                return None
        m = re.search(r"(\d{4})-(\d{2})-(\d{2})", value)
        if m:
            try:
                return dt.date(*map(int, m.groups()))
            except ValueError:
                return None
    return None


def _days_in_year(d: dt.date) -> int:
    """Фактическое число дней в году — 365 или 366 (канон F.10, п. 84 ППВС № 7)."""
    year = d.year
    return 366 if (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)) else 365


# --- модели формул ----------------------------------------------------------
# Скрипт не навязывает формулу: он проверяет, какая из типовых моделей сходится
# с данными таблицы. Ни одна не сошлась → честный флаг, а не «пересчёт по-своему».

def _formula_models(anchor_date):
    days_in_year = _days_in_year(anchor_date or dt.date(2026, 1, 1))
    return [
        {"id": "annual/actual", "days_in_year": days_in_year,
         "label": f"ставка % годовых / {days_in_year} дн.",
         "fn": lambda b, r, d: b * (r / 100.0) * d / days_in_year},
        {"id": "annual/365", "days_in_year": 365,
         "label": "ставка % годовых / 365 дн.",
         "fn": lambda b, r, d: b * (r / 100.0) * d / 365.0},
        {"id": "annual/366", "days_in_year": 366,
         "label": "ставка % годовых / 366 дн.",
         "fn": lambda b, r, d: b * (r / 100.0) * d / 366.0},
        {"id": "annual/300", "days_in_year": 300,
         "label": "1/300 ставки за день (ЖКХ, налоги)",
         "fn": lambda b, r, d: b * (r / 100.0) * d / 300.0},
        {"id": "daily-percent", "days_in_year": None,
         "label": "ставка % за день (договорная, напр. 0,1 %)",
         "fn": lambda b, r, d: b * (r / 100.0) * d},
        {"id": "daily-fraction", "days_in_year": None,
         "label": "ставка долей за день (напр. 0,001)",
         "fn": lambda b, r, d: b * r * d},
    ]


def _close(a, b, tolerance):
    if a is None or b is None:
        return False
    return abs(a - b) <= max(tolerance, abs(b) * REL_TOLERANCE)


def _money(value) -> str:
    """Сумма по-русски: пробел между разрядами, запятая в дробной части.

    Отдельной функцией, потому что формат `{:,.2f}` даёт «13,589.04», а замена
    запятых по всему сообщению съедает и обычные запятые текста (поймано тестом).
    """
    if value is None:
        return "—"
    s = f"{abs(value):,.2f}".replace(",", " ").replace(".", ",")
    return ("−" if value < 0 else "") + s + " ₽"


def _money_signed(value) -> str:
    if value is None:
        return "—"
    return ("+" if value > 0 else "") + _money(value)


# --- адресация --------------------------------------------------------------

def _col_letter(idx0: int) -> str:
    letters, n = "", idx0 + 1
    while n:
        n, rem = divmod(n - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def _addr(sheet: str, row1: int, col0: int) -> str:
    return f"{sheet}!{_col_letter(col0)}{row1}"


# --- профиль debt-calc ------------------------------------------------------

def profile_debt_calc(sheet_name, headers, rows, header_row1, tolerance) -> dict:
    findings, out_rows = [], []
    cols = detect_columns(headers, rows)

    def add(code, severity, message, cells=None, numbers=None):
        findings.append({"code": code, "severity": severity, "message": message,
                         "cells": cells or [], "numbers": numbers or {}})

    missing = [k for k in ("base", "rate", "days", "amount") if k not in cols]
    if missing:
        add("columns-missing", "warn",
            "Не распознаны колонки: " + ", ".join(missing)
            + ". Проверены заголовки: " + " | ".join(h for h in headers if h)
            + ". Арифметика строк не проверялась — укажите колонки вручную или "
              "приведите шапку к обычным названиям (сумма долга / ставка / дней / пени).")

    # собираем строки данных
    data = []
    for i, row in enumerate(rows):
        if i <= 0 and not row:
            continue
        row1 = header_row1 + 1 + i          # номер строки в файле
        rec = {"row": row1}
        for key, idx in cols.items():
            raw = row[idx] if idx < len(row) else None
            rec[key] = raw
            rec[key + "_num"] = _num(raw)
            if key in ("date_from", "date_to"):
                rec[key + "_date"] = _as_date(raw)
        # строка считается расчётной, если есть база и итог
        if rec.get("base_num") is not None and rec.get("amount_num") is not None:
            data.append(rec)

    # --- выбор модели формулы
    anchor = next((r.get("date_from_date") for r in data if r.get("date_from_date")), None)
    formula = None
    if len(data) >= MIN_ROWS_FOR_FORMULA and not missing:
        scores = []
        for model in _formula_models(anchor):
            ok = 0
            for r in data:
                exp = model["fn"](r["base_num"], r["rate_num"] or 0, r["days_num"] or 0)
                if _close(exp, r["amount_num"], tolerance):
                    ok += 1
            scores.append((ok, model))
        scores.sort(key=lambda s: s[0], reverse=True)
        best_ok, best = scores[0]
        if best_ok >= max(1, int(len(data) * 0.6)):
            formula = {"id": best["id"], "label": best["label"],
                       "matched_rows": best_ok, "total_rows": len(data)}
        else:
            add("formula-unknown", "warn",
                "Ни одна типовая модель расчёта не сошлась с данными "
                f"(лучшая — «{best['label']}»: {best_ok} из {len(data)} строк). "
                "Формула нестандартная либо в таблице ошибки не в одной строке, а в подходе. "
                "Пересчёт по своей формуле НЕ выполнялся — проверьте расчёт вручную.")

    # --- конвенция счёта дней: определяем преобладающую по таблице
    # Обе конвенции законны (включая первый день / без него), поэтому ошибкой
    # является не значение само по себе, а ВЫПАДЕНИЕ строки из конвенции таблицы:
    # именно так выглядит подкрученный на день период у оппонента.
    day_conv = {"inclusive": 0, "exclusive": 0, "other": 0}
    for r in data:
        if r.get("date_from_date") and r.get("date_to_date") and r.get("days_num") is not None:
            incl = (r["date_to_date"] - r["date_from_date"]).days + 1
            stated = int(r["days_num"])
            if stated == incl:
                day_conv["inclusive"] += 1
            elif stated == incl - 1:
                day_conv["exclusive"] += 1
            else:
                day_conv["other"] += 1
    convention = None
    if day_conv["inclusive"] or day_conv["exclusive"]:
        convention = "inclusive" if day_conv["inclusive"] >= day_conv["exclusive"] else "exclusive"

    # --- проверка строк
    for r in data:
        row_findings = []
        d_from, d_to = r.get("date_from_date"), r.get("date_to_date")

        # дни по датам vs указанные дни — против конвенции таблицы
        if d_from and d_to and r.get("days_num") is not None:
            incl = (d_to - d_from).days + 1
            stated = int(r["days_num"])
            expected_days = incl if convention == "inclusive" else incl - 1
            if convention and stated != expected_days:
                row_findings.append({
                    "code": "days-mismatch", "severity": "error",
                    "message": f"строка {r['row']}: указано {stated} дн., а по датам "
                               f"{d_from:%d.%m.%Y}–{d_to:%d.%m.%Y} должно быть "
                               f"{expected_days} дн. В остальных строках таблицы период "
                               f"считается «{'включая первый день' if convention == 'inclusive' else 'со следующего дня'}»"
                               f" — эта строка из конвенции выпадает",
                    "cells": [_addr(sheet_name, r["row"], cols["days"])],
                    "numbers": {"stated": stated, "expected": expected_days,
                                "by_dates_inclusive": incl}})
            elif not convention:
                row_findings.append({
                    "code": "days-unverifiable", "severity": "warn",
                    "message": f"строка {r['row']}: указано {stated} дн., по датам "
                               f"{d_from:%d.%m.%Y}–{d_to:%d.%m.%Y} — {incl} дн. "
                               f"включая первый день ({incl - 1} без него). Ни одна "
                               f"конвенция счёта по таблице не подтверждается — проверьте вручную",
                    "cells": [_addr(sheet_name, r["row"], cols["days"])],
                    "numbers": {"stated": stated, "by_dates_inclusive": incl}})

        # арифметика строки по выбранной модели
        if formula and r.get("rate_num") is not None and r.get("days_num") is not None:
            model = next(m for m in _formula_models(anchor) if m["id"] == formula["id"])
            expected = model["fn"](r["base_num"], r["rate_num"], r["days_num"])
            if not _close(expected, r["amount_num"], tolerance):
                delta = r["amount_num"] - expected
                row_findings.append({
                    "code": "row-arithmetic", "severity": "error",
                    "message": f"строка {r['row']}: в таблице {_money(r['amount_num'])}, "
                               f"по формуле «{formula['label']}» — {_money(expected)}, "
                               f"расхождение {_money_signed(delta)}",
                    "cells": [_addr(sheet_name, r["row"], cols["amount"])],
                    "numbers": {"stated": r["amount_num"], "expected": round(expected, 2),
                                "delta": round(delta, 2)}})

        findings.extend(row_findings)
        out_rows.append({"row": r["row"],
                         "base": r.get("base_num"), "rate": r.get("rate_num"),
                         "days": r.get("days_num"), "amount": r.get("amount_num"),
                         "date_from": d_from.isoformat() if d_from else None,
                         "date_to": d_to.isoformat() if d_to else None,
                         "ok": not row_findings})

    # --- перекрытие и разрывы периодов (двойной счёт дней)
    periods = {"checked": False, "overlaps": [], "gaps": []}
    dated = [r for r in data if r.get("date_from_date") and r.get("date_to_date")]
    if len(dated) >= 2:
        periods["checked"] = True
        dated.sort(key=lambda r: r["date_from_date"])
        for prev, cur in zip(dated, dated[1:]):
            if cur["date_from_date"] <= prev["date_to_date"]:
                overlap = (prev["date_to_date"] - cur["date_from_date"]).days + 1
                periods["overlaps"].append({"rows": [prev["row"], cur["row"]],
                                            "days": overlap})
                add("period-overlap", "error",
                    f"периоды строк {prev['row']} и {cur['row']} перекрываются на "
                    f"{overlap} дн. ({cur['date_from_date']:%d.%m.%Y} ≤ "
                    f"{prev['date_to_date']:%d.%m.%Y}) — двойной счёт дней",
                    [_addr(sheet_name, prev["row"], cols.get("date_to", 0)),
                     _addr(sheet_name, cur["row"], cols.get("date_from", 0))],
                    {"overlap_days": overlap})
            elif (cur["date_from_date"] - prev["date_to_date"]).days > 1:
                gap = (cur["date_from_date"] - prev["date_to_date"]).days - 1
                periods["gaps"].append({"rows": [prev["row"], cur["row"]], "days": gap})
                add("period-gap", "info",
                    f"между строками {prev['row']} и {cur['row']} пропуск {gap} дн. "
                    f"— проверьте, намеренный ли (мораторий, отсрочка) или потерян период",
                    [_addr(sheet_name, cur["row"], cols.get("date_from", 0))],
                    {"gap_days": gap})

    # --- итог: сумма строк vs заявленный итог
    totals = {"rows_sum": None, "stated_total": None, "stated_total_row": None,
              "delta": None}
    if data and "amount" in cols:
        rows_sum = sum(r["amount_num"] for r in data)
        totals["rows_sum"] = round(rows_sum, 2)
        # ищем итоговую строку ниже данных
        for i, row in enumerate(rows):
            joined = " ".join(_cell_str(c).lower() for c in row if not _cell_empty(c))
            if any(m in joined for m in ("итого", "всего", "итог")):
                val = _num(row[cols["amount"]] if cols["amount"] < len(row) else None)
                if val is not None:
                    totals["stated_total"] = val
                    totals["stated_total_row"] = header_row1 + 1 + i
                    break
        if totals["stated_total"] is not None:
            delta = totals["stated_total"] - rows_sum
            totals["delta"] = round(delta, 2)
            if not _close(totals["stated_total"], rows_sum, tolerance):
                add("total-mismatch", "error",
                    f"итог в таблице {_money(totals['stated_total'])}, сумма строк "
                    f"{_money(rows_sum)}, расхождение {_money_signed(delta)}",
                    [_addr(sheet_name, totals["stated_total_row"], cols["amount"])],
                    {"stated": totals["stated_total"], "rows_sum": round(rows_sum, 2)})

    # --- ставки: перечень для сверки агентом (сеть не трогаем — канон F.10)
    rates = []
    for r in data:
        if r.get("rate_num") is None:
            continue
        rates.append({"row": r["row"], "rate": r["rate_num"],
                      "date_from": r["date_from_date"].isoformat() if r.get("date_from_date") else None,
                      "date_to": r["date_to_date"].isoformat() if r.get("date_to_date") else None})
    distinct = sorted({x["rate"] for x in rates})
    if rates:
        add("rates-to-verify", "info",
            f"в расчёте использованы ставки: {', '.join(f'{v:g} %' for v in distinct)}. "
            "Сверьте значение и дату начала действия каждой по канону F.10 "
            "(база cbr.ru); скрипт сеть не запрашивает.",
            [], {"distinct_rates": distinct})

    # --- частичные оплаты: очерёдность ст. 319 ГК — правовая проверка, не арифметика
    if "paid" in cols and any(r.get("paid_num") for r in data):
        add("partial-payments", "warn",
            "В таблице есть колонка оплат. Проверьте разноску по очерёдности ст. 319 ГК "
            "(канон F.10, п. 7): платёж гасит сначала проценты за пользование, затем "
            "основной долг, и только потом проценты по ст. 395 и неустойку. Если оппонент "
            "закрыл платежами сначала неустойку — остаток долга у него завышен.",
            [_addr(sheet_name, data[0]["row"], cols["paid"])])

    return {"columns": {k: _col_letter(v) for k, v in cols.items()},
            "formula": formula, "rows": out_rows, "findings": findings,
            "totals": totals, "rates": rates, "periods": periods}


# --- чтение листа -----------------------------------------------------------

def load_sheet(path: str, sheet: str = None):
    from openpyxl import load_workbook
    wb = load_workbook(path, data_only=True, read_only=True, keep_links=False)
    try:
        ws = wb[sheet] if sheet else wb[wb.sheetnames[0]]
        name = ws.title
        rows = []
        for n, row in enumerate(ws.iter_rows(values_only=True)):
            if n >= TABLE_MAX_SCAN_ROWS:
                break
            rows.append(list(row))
    finally:
        try:
            wb.close()
        except Exception:
            pass
    while rows and all(_cell_empty(c) for c in rows[-1]):
        rows.pop()
    if not rows:
        return name, [], [], 1
    width = max(len(r) for r in rows)
    hdr = _find_header_row(rows)
    headers = _pad_row([_cell_str(c) for c in rows[hdr]], width)
    data_rows = [_pad_row(r, width) for r in rows[hdr + 1:]]
    return name, headers, data_rows, hdr + 1


# --- CLI --------------------------------------------------------------------

# --- профиль statement (выписка по счёту) -----------------------------------

STATEMENT_MARKERS = {
    "date":    ("дата", "дата операции", "дата проводки", "дата документа"),
    "debit":   ("списание", "расход", "дебет", "по дебету", "уменьшение"),
    "credit":  ("приход", "поступление", "кредит", "по кредиту", "зачисление",
                "увеличение"),
    "amount":  ("сумма", "сумма операции", "сумма по операции"),
    "party":   ("контрагент", "плательщик", "получатель", "наименование",
                "корреспондент", "бенефициар"),
    "inn":     ("инн",),
    "purpose": ("назначение", "назначение платежа", "основание", "содержание операции"),
    "balance": ("остаток", "сальдо", "исходящий остаток", "баланс"),
}

SPLIT_MIN_PAYMENTS = 3      # сколько платежей одному лицу подряд считать дроблением
SPLIT_WINDOW_DAYS = 2       # в пределах скольких дней
TOP_PARTIES = 10


def _detect_by_markers(headers: list, markers: dict) -> dict:
    found, norm = {}, [_norm_header(h) for h in headers]
    for key, marks in markers.items():
        for idx, head in enumerate(norm):
            if not head or idx in found.values():
                continue
            if any(m in head for m in marks):
                found[key] = idx
                break
    return found


def _extract_party(rec: dict) -> str:
    """Контрагент: своя колонка, иначе — из назначения платежа (кавычки / ИНН)."""
    if rec.get("party") and _cell_str(rec["party"]):
        return _cell_str(rec["party"])
    purpose = _cell_str(rec.get("purpose"))
    if not purpose:
        return ""
    m = re.search(r"[«\"']([^»\"']{3,60})[»\"']", purpose)
    if m:
        return m.group(1).strip()
    m = re.search(r"\b(\d{10}|\d{12})\b", purpose)
    if m:
        return f"ИНН {m.group(1)}"
    return ""


def profile_statement(sheet_name, headers, rows, header_row1, tolerance) -> dict:
    findings = []
    cols = _detect_by_markers(headers, STATEMENT_MARKERS)

    def add(code, severity, message, cells=None, numbers=None):
        findings.append({"code": code, "severity": severity, "message": message,
                         "cells": cells or [], "numbers": numbers or {}})

    # дата: добор по данным, если по заголовку не нашлась
    if "date" not in cols:
        for col in range(len(headers)):
            values = [r[col] for r in rows if col < len(r)]
            if sum(1 for v in values if _is_date_like(v)) >= max(2, len(values) // 3):
                cols["date"] = col
                break

    if "date" not in cols:
        add("columns-missing", "warn",
            "Колонка даты не распознана — обороты по периодам и разрывы не проверялись. "
            "Заголовки: " + " | ".join(h for h in headers if h))

    has_split_columns = "debit" in cols and "credit" in cols
    if not has_split_columns and "amount" not in cols:
        add("columns-missing", "warn",
            "Не найдены ни пара «приход/списание», ни единая колонка суммы — обороты "
            "не посчитаны. Заголовки: " + " | ".join(h for h in headers if h))

    ops = []
    for i, row in enumerate(rows):
        row1 = header_row1 + 1 + i
        rec = {key: (row[idx] if idx < len(row) else None) for key, idx in cols.items()}
        date = _as_date(rec.get("date"))
        debit = _num(rec.get("debit")) if has_split_columns else None
        credit = _num(rec.get("credit")) if has_split_columns else None
        single = _num(rec.get("amount")) if not has_split_columns else None
        if single is not None:
            # единая колонка со знаком: минус — списание
            debit, credit = (abs(single), None) if single < 0 else (None, single)
        if date is None and debit is None and credit is None:
            continue
        ops.append({"row": row1, "date": date, "debit": debit, "credit": credit,
                    "party": _extract_party(rec), "purpose": _cell_str(rec.get("purpose")),
                    "balance": _num(rec.get("balance"))})

    dated = [o for o in ops if o["date"]]
    turnover = {
        "operations": len(ops),
        "credit_total": round(sum(o["credit"] or 0 for o in ops), 2),
        "debit_total": round(sum(o["debit"] or 0 for o in ops), 2),
        "period_from": min((o["date"] for o in dated), default=None),
        "period_to": max((o["date"] for o in dated), default=None),
    }
    turnover["period_from"] = turnover["period_from"].isoformat() if turnover["period_from"] else None
    turnover["period_to"] = turnover["period_to"].isoformat() if turnover["period_to"] else None

    # --- непрерывность остатка: самая сильная проверка полноты выписки
    # Если остаток предыдущей строки ± сумма операции ≠ остаток текущей, между ними
    # пропущены операции. Это довод против доказательственной полноты выписки,
    # который иначе не увидеть: по датам «дырки» может не быть вовсе.
    balance_check = {"checked": False, "breaks": []}
    with_balance = [o for o in ops if o["balance"] is not None]
    if len(with_balance) >= 3:
        balance_check["checked"] = True
        for prev, cur in zip(with_balance, with_balance[1:]):
            expected = prev["balance"] + (cur["credit"] or 0) - (cur["debit"] or 0)
            if not _close(expected, cur["balance"], tolerance):
                gap = round(cur["balance"] - expected, 2)
                balance_check["breaks"].append({"rows": [prev["row"], cur["row"]],
                                                "gap": gap})
                if len(balance_check["breaks"]) <= 10:
                    add("balance-break", "error",
                        f"разрыв остатка между строками {prev['row']} и {cur['row']}: "
                        f"по предыдущему остатку и сумме операции должно быть "
                        f"{_money(expected)}, в выписке {_money(cur['balance'])} "
                        f"(расхождение {_money_signed(gap)}). Между строками пропущены "
                        f"операции — выписка неполная",
                        [_addr(sheet_name, cur["row"], cols.get("balance", 0))],
                        {"expected": round(expected, 2), "stated": cur["balance"],
                         "gap": gap})
        if len(balance_check["breaks"]) > 10:
            add("balance-break-many", "error",
                f"разрывов остатка всего {len(balance_check['breaks'])} — показаны первые 10. "
                f"Выписка систематически неполна", [], {"breaks": len(balance_check["breaks"])})

    # --- дробление: группа платежей одному лицу в узком окне
    # Группа собирается ЦЕЛИКОМ (жадно, пока платежи укладываются в окно от первого),
    # а не обрывается на достижении порога: иначе четвёртый платёж выпадает из группы
    # и в отчёте видно 3 платежа вместо 4 — сумма «дробления» занижается.
    splits = []
    by_party = {}
    for o in dated:
        if o["debit"] and o["party"]:
            by_party.setdefault(o["party"], []).append(o)
    for party, items in by_party.items():
        items.sort(key=lambda x: x["date"])
        i = 0
        while i < len(items):
            group = [items[i]]
            j = i + 1
            while j < len(items) and (items[j]["date"] - group[0]["date"]).days <= SPLIT_WINDOW_DAYS:
                group.append(items[j])
                j += 1
            if len(group) >= SPLIT_MIN_PAYMENTS:
                splits.append({"party": party,
                               "rows": [g["row"] for g in group],
                               "total": round(sum(g["debit"] for g in group), 2),
                               "from": group[0]["date"].isoformat(),
                               "to": group[-1]["date"].isoformat()})
                i = j
            else:
                i += 1
    split_rows = {r for s in splits for r in s["rows"]}
    for s in splits[:10]:
        same_day = s["from"] == s["to"]
        add("payment-splitting", "warn",
            f"«{s['party']}» — платежей: {len(s['rows'])}, "
            + (f"все {s['from']}" if same_day else f"за {s['from']}–{s['to']}")
            + f", на {_money(s['total'])} (строки {', '.join(map(str, s['rows']))}). "
              f"Похоже на дробление — гипотеза, требует проверки: у дробления бывают "
              f"законные причины (лимиты банка, разные счета-фактуры, график поставок)",
            [_addr(sheet_name, s["rows"][0], cols.get("date", 0))],
            {"count": len(s["rows"]), "total": s["total"]})

    # --- дубли: одна дата + одна сумма + один контрагент
    # Строки, уже объяснённые флагом дробления, повторно как «дубли» не подаём —
    # иначе одно явление даёт четыре флага и юрист перестаёт их читать.
    seen, duplicates, suppressed = {}, [], 0
    for o in ops:
        key = (o["date"], o["debit"], o["credit"], o["party"])
        if o["date"] is None or (o["debit"] is None and o["credit"] is None):
            continue
        if key in seen:
            pair = [seen[key], o["row"]]
            if all(r in split_rows for r in pair):
                suppressed += 1
                continue
            duplicates.append({"rows": pair, "amount": o["debit"] or o["credit"],
                               "party": o["party"]})
        else:
            seen[key] = o["row"]
    for d in duplicates[:10]:
        add("duplicate-operation", "warn",
            f"строки {d['rows'][0]} и {d['rows'][1]}: одинаковые дата, сумма "
            f"({_money(d['amount'])}) и контрагент — либо дубль в выписке, либо два "
            f"действительно одинаковых платежа. Проверьте перед использованием суммы",
            [_addr(sheet_name, r, cols.get("date", 0)) for r in d["rows"]])
    if len(duplicates) > 10:
        add("duplicate-operation-many", "warn",
            f"совпадающих операций всего {len(duplicates)} — показаны первые 10", [],
            {"duplicates": len(duplicates)})
    if suppressed:
        add("duplicate-in-splitting", "info",
            f"ещё {suppressed} совпадающих операций входят в группы, отмеченные как "
            f"возможное дробление, — отдельными флагами не дублируются", [],
            {"suppressed": suppressed})

    # --- крупнейшие получатели (куда ушли деньги)
    top = sorted(({"party": p,
                   "debit_total": round(sum(o["debit"] or 0 for o in items), 2),
                   "operations": len(items),
                   "rows": [o["row"] for o in items[:5]]}
                  for p, items in by_party.items()),
                 key=lambda x: x["debit_total"], reverse=True)[:TOP_PARTIES]

    # --- разрыв по датам: подозрение на неполноту, когда остатка в выписке нет
    date_gaps = []
    if dated and not balance_check["checked"]:
        dated.sort(key=lambda o: o["date"])
        for prev, cur in zip(dated, dated[1:]):
            gap_days = (cur["date"] - prev["date"]).days
            if gap_days >= 31:
                date_gaps.append({"rows": [prev["row"], cur["row"]], "days": gap_days,
                                  "from": prev["date"].isoformat(),
                                  "to": cur["date"].isoformat()})
        for g in date_gaps[:5]:
            add("date-gap", "info",
                f"между {g['from']} и {g['to']} нет операций ({g['days']} дн., строки "
                f"{g['rows'][0]}–{g['rows'][1]}). Само по себе не дефект, но проверьте, "
                f"полна ли выписка: колонки остатка в ней нет, поэтому машинно "
                f"подтвердить полноту невозможно",
                [_addr(sheet_name, g["rows"][1], cols.get("date", 0))],
                {"gap_days": g["days"]})

    # --- итоговая строка против суммы операций
    totals = {"stated_total": None, "stated_total_row": None, "delta": None,
              "compared_against": None}
    for i, row in enumerate(rows):
        joined = " ".join(_cell_str(c).lower() for c in row if not _cell_empty(c))
        if any(m in joined for m in ("итого", "всего", "оборот за период")):
            for key, ref in (("debit", turnover["debit_total"]),
                             ("credit", turnover["credit_total"])):
                if key in cols:
                    val = _num(row[cols[key]] if cols[key] < len(row) else None)
                    if val is None:
                        continue
                    totals.update({"stated_total": val,
                                   "stated_total_row": header_row1 + 1 + i,
                                   "compared_against": key,
                                   "delta": round(val - ref, 2)})
                    if not _close(val, ref, tolerance):
                        add("total-mismatch", "error",
                            f"итог по колонке «{headers[cols[key]]}» в таблице "
                            f"{_money(val)}, сумма операций {_money(ref)}, расхождение "
                            f"{_money_signed(val - ref)}",
                            [_addr(sheet_name, header_row1 + 1 + i, cols[key])],
                            {"stated": val, "computed": ref})
                    break
            break

    return {"columns": {k: _col_letter(v) for k, v in cols.items()},
            "turnover": turnover, "balance_check": balance_check,
            "duplicates": duplicates[:50], "splitting": splits[:50],
            "top_parties": top, "date_gaps": date_gaps[:50],
            "totals": totals, "findings": findings, "rows": []}


PROFILES = {"debt-calc": profile_debt_calc, "statement": profile_statement}


def selftest() -> int:
    """`--selftest` — проверка профиля на сгенерированной таблице, без внешних файлов.

    Нужна для боевого прогона в Cowork: подтверждает, что профиль ловит подставленные
    дефекты и НЕ шумит на корректном расчёте (ложная тревога дороже пропуска — юрист
    перестанет доверять флагам). Ожидаемые коды перечислены явно.
    """
    import tempfile
    try:
        from openpyxl import Workbook
    except ImportError:
        print("SELFTEST: openpyxl не установлен — запустите scripts/setup.sh")
        return 1

    tmp = tempfile.mkdtemp(prefix="analyze_table_selftest_")
    ok_all = True

    # 1) расчёт с четырьмя подставленными дефектами
    wb = Workbook(); ws = wb.active; ws.title = "Расчёт"
    ws.append(["Расчёт неустойки"]); ws.append([])
    ws.append(["Сумма долга", "с", "по", "Дней", "Ставка, %", "Пени"])
    base, rate = 1000000, 16.0
    good = base * rate / 100 * 31 / 365
    ws.append([base, dt.date(2026, 1, 15), dt.date(2026, 2, 14), 31, rate, round(good, 2)])
    ws.append([base, dt.date(2026, 2, 12), dt.date(2026, 3, 14), 31, rate, round(good, 2)])  # overlap
    ws.append([base, dt.date(2026, 3, 15), dt.date(2026, 4, 14), 30, rate, round(good, 2)])  # days
    ws.append([base, dt.date(2026, 4, 15), dt.date(2026, 5, 15), 31, rate, round(good + 5000, 2)])
    ws.append([None, None, None, None, "ИТОГО", round(good * 4 + 5000 + 10000, 2)])          # total
    bad_path = os.path.join(tmp, "bad.xlsx"); wb.save(bad_path)

    # 2) корректный расчёт (высокосный год → 366)
    wb2 = Workbook(); w2 = wb2.active; w2.title = "Проценты"
    w2.append(["Сумма долга", "с", "по", "Дней", "Ставка, %", "Проценты"])
    total = 0.0
    for start, end, days in ((dt.date(2024, 1, 10), dt.date(2024, 2, 9), 31),
                             (dt.date(2024, 2, 10), dt.date(2024, 3, 10), 30),
                             (dt.date(2024, 3, 11), dt.date(2024, 4, 10), 31)):
        val = round(500000 * 16.0 / 100 * days / 366, 2)
        total += val
        w2.append([500000, start, end, days, 16.0, val])
    w2.append([None, None, None, None, "ИТОГО", round(total, 2)])
    ok_path = os.path.join(tmp, "ok.xlsx"); wb2.save(ok_path)

    # 3) выписка: скрытые операции (разрыв остатка) + дробление + занижённый итог
    wb3 = Workbook(); w3 = wb3.active; w3.title = "Обороты"
    w3.append(["АО «Банк»"]); w3.append(["Выписка по счёту"]); w3.append([])
    w3.append(["Дата", "Контрагент", "Назначение", "Приход", "Списание", "Остаток"])
    bal = 5000000.0
    ledger = [(dt.date(2026, 2, 3), 'ООО "Поставщик"', None, 300000.0)]
    ledger += [(dt.date(2026, 2, 10 + (i // 3)), 'ООО "Ромашка"', None, 400000.0)
               for i in range(4)]                                    # дробление
    for date, party, credit, debit in ledger:
        bal += (credit or 0) - (debit or 0)
        w3.append([date, party, "оплата", credit, debit, round(bal, 2)])
    bal -= 2000000.0                                                 # скрытые операции
    w3.append([dt.date(2026, 3, 1), 'ООО "Прочий"', "возврат", None, 100000.0,
               round(bal - 100000, 2)])
    w3.append([None, None, "ИТОГО", None, 1000000.0, None])          # итог занижен
    st_path = os.path.join(tmp, "statement.xlsx"); wb3.save(st_path)

    for path, expect_codes, expect_errors in (
            (bad_path, {"period-overlap", "days-mismatch", "row-arithmetic", "total-mismatch"}, 5),
            (ok_path, set(), 0)):
        name, headers, rows, hdr = load_sheet(path)
        res = profile_debt_calc(name, headers, rows, hdr, DEFAULT_TOLERANCE)
        codes = {f["code"] for f in res["findings"] if f["severity"] == "error"}
        errors = sum(1 for f in res["findings"] if f["severity"] == "error")
        tag = Path(path).stem
        if codes != expect_codes or errors != expect_errors:
            ok_all = False
            print(f"SELFTEST [{tag}] ✗ ожидались коды {sorted(expect_codes) or '—'} "
                  f"и {expect_errors} ошибок; получено {sorted(codes) or '—'} / {errors}")
        else:
            print(f"SELFTEST [{tag}] ✓ коды {sorted(codes) or '—'}, ошибок {errors}"
                  + (f", формула «{res['formula']['label']}»" if res.get("formula") else ""))

    # профиль statement
    name, headers, rows, hdr = load_sheet(st_path)
    res = profile_statement(name, headers, rows, hdr, DEFAULT_TOLERANCE)
    codes = {f["code"] for f in res["findings"] if f["severity"] == "error"}
    expect = {"balance-break", "total-mismatch"}
    split_groups = len(res["splitting"])
    split_size = max((len(s["rows"]) for s in res["splitting"]), default=0)
    if codes != expect or split_groups != 1 or split_size != 4:
        ok_all = False
        print(f"SELFTEST [statement] ✗ ожидались {sorted(expect)} и одна группа дробления "
              f"из 4 платежей; получено {sorted(codes)}, групп {split_groups}, "
              f"максимальная {split_size}")
    else:
        gap = res["balance_check"]["breaks"][0]["gap"]
        print(f"SELFTEST [statement] ✓ коды {sorted(codes)}, скрытых операций на "
              f"{_money(gap)}, дробление: 1 группа из 4 платежей")

    print("SELFTEST:", "ВСЁ ЗЕЛЁНОЕ" if ok_all else "ЕСТЬ ОТКАЗЫ")
    return 0 if ok_all else 1


def main():
    # Как в extract_text.py: на Windows stdout по умолчанию cp1251 и падает на
    # кириллице/типографике в JSON. Кодировку задаём явно, ensure_ascii=False
    # оставляем — JSON должен быть читаемым, а не в \uXXXX.
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

    argv = sys.argv[1:]
    if "--selftest" in argv:
        return selftest()
    if not argv or argv[0].startswith("--"):
        print(json.dumps({"error": "укажите файл: analyze_table.py <файл.xlsx> "
                                   "--profile debt-calc  (или --selftest)"},
                         ensure_ascii=False))
        return 2
    path = argv[0]

    def opt(name, default=None):
        return argv[argv.index(name) + 1] if name in argv and argv.index(name) + 1 < len(argv) \
            else default

    profile = opt("--profile", "debt-calc")
    sheet = opt("--sheet")
    tolerance = float(opt("--tolerance", DEFAULT_TOLERANCE))

    if profile not in PROFILES:
        print(json.dumps({"error": f"неизвестный профиль: {profile}",
                          "available": sorted(PROFILES)}, ensure_ascii=False))
        return 2
    if not os.path.exists(path):
        print(json.dumps({"error": f"файл не найден: {path}"}, ensure_ascii=False))
        return 1

    try:
        name, headers, rows, header_row1 = load_sheet(path, sheet)
    except Exception as exc:
        print(json.dumps({"error": f"не удалось прочитать таблицу: {exc}"},
                         ensure_ascii=False))
        return 1

    if not rows:
        print(json.dumps({"profile": profile, "sheet": name, "error": "лист пуст"},
                         ensure_ascii=False))
        return 0

    result = PROFILES[profile](name, headers, rows, header_row1, tolerance)
    result.update({"profile": profile, "sheet": name, "file": Path(path).name,
                   "header_row": header_row1,
                   "errors": sum(1 for f in result["findings"] if f["severity"] == "error")})

    out_dir = opt("--out-dir")
    payload = json.dumps(result, ensure_ascii=False, indent=2)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
        dst = os.path.join(out_dir, Path(path).stem + f".{profile}.json")
        with open(dst, "w", encoding="utf-8") as f:
            f.write(payload)
        print(json.dumps({"saved": dst, "errors": result["errors"],
                          "findings": len(result["findings"])}, ensure_ascii=False))
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
