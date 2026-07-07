#!/usr/bin/env python3
"""
extract_text.py — детерминированная Python-нога OCR-модуля `shared/ocr`.

Контракт, дерево решений и агентский протокол (vision, кэш, структурный режим,
пер-полевой confidence) — см. shared/ocr.md. Эта программа делает ТОЛЬКО
детерминированную часть и НЕ выполняет vision (Python не имеет доступа к Read tool):

  - программное извлечение текста: PDF с текстовым слоем, DOCX, TXT;
  - детект «мусорного» текстового слоя (F3.3) — mojibake / тонкий OCR-артефакт
    поверх скана → директива needs_vision вместо молчаливого возврата мусора;
  - решение needs_vision / vision_pages / vision_reason (F3.1): vision — основной
    путь OCR, не tesseract-rus (которого в Cowork нет и который упирается в таймаут);
  - рекомендация структурного режима для длинных сканов (F3.4);
  - вычисление content_hash для кэша (F3.2; само решение о кэше — агентское);
  - рендер страницы(ц) в PNG для vision через pymupdf (надёжнее системного
    pdftoppm, который у файлового Read падает «unsafe location») + guard обрезки (F3.5);
  - ОПЦИОНАЛЬНАЯ tesseract спот-сверка ОДНОГО поля по вендоренному rus.traineddata
    (F3.1, вторая нога) — для независимой сверки критичной цифры (ИНН/сумма/дата).

Режимы запуска:
    # 1) извлечение (основной режим, вызывается скиллами ingest):
    python3 extract_text.py <файл> [--output-dir <папка>] [--render-dir <папка>]
                            [--max-head-pages N] [--structural-threshold N]

    # 2) рендер одной страницы в PNG (для vision-ноги агента):
    python3 extract_text.py --render <file.pdf> --page N [--render-dir <папка>] [--width 1500]

    # 3) tesseract спот-сверка одного поля (кроп → одна строка):
    python3 extract_text.py --spot-check <crop.png> [--tessdata <путь>]

Выход: JSON. Поля контракта — см. shared/ocr.md §3.
"""

import sys
import json
import os
import re
import errno
import hashlib
import subprocess
from pathlib import Path

# --- Параметры по умолчанию -------------------------------------------------

DEFAULT_RENDER_WIDTH = 1500          # ориентир ширины PNG для vision (1200–1700 px)
DEFAULT_MAX_HEAD_PAGES = 10          # сколько головных страниц полнотекстить в структурном режиме
DEFAULT_STRUCTURAL_THRESHOLD = 15    # порог (скан-страниц) для рекомендации структурного режима


# --- content_hash (F3.2) ----------------------------------------------------

def compute_content_hash(filepath: str) -> str:
    """SHA-256 от бинарного содержимого файла (ключ кэша/дедупа)."""
    h = hashlib.sha256()
    try:
        with open(filepath, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return "sha256:" + h.hexdigest()
    except Exception:
        return ""


# --- Детект мусорного текстового слоя (F3.3) --------------------------------

def _text_diagnostics(text: str) -> dict:
    """Метрики качества извлечённого текстового слоя страницы/документа."""
    t = text or ""
    total = len(t)
    if total == 0:
        return {"empty": True, "len": 0}
    repl = t.count("�")
    ctrl = sum(1 for ch in t if ord(ch) < 32 and ch not in "\t\n\r\f")
    alpha = [ch for ch in t if ch.isalpha()]
    cyr = sum(1 for ch in alpha if "Ѐ" <= ch <= "ӿ")
    cyr_ratio = (cyr / len(alpha)) if alpha else 0.0
    tokens = [w for w in re.split(r"\s+", t.strip()) if w]
    avg_tok = (sum(len(w) for w in tokens) / len(tokens)) if tokens else 0.0
    return {
        "empty": False,
        "len": total,
        "repl_ratio": repl / total,
        "ctrl_ratio": ctrl / total,
        "cyr_ratio": cyr_ratio,
        "alpha_count": len(alpha),
        "avg_token_len": avg_tok,
    }


def _is_garbage(diag: dict) -> bool:
    """True, если текстовый слой — мусор (mojibake/каша), а не осмысленный текст.

    Пусто (empty) — это НЕ мусор: это «нет текстового слоя» (скан) → отдельная ветка.
    Пороги консервативны, чтобы не гнать на vision годный текст.
    """
    if diag.get("empty"):
        return False
    if diag.get("repl_ratio", 0) > 0.02:          # символы замены — сильный сигнал порчи кодировки
        return True
    if diag.get("ctrl_ratio", 0) > 0.05:          # много управляющих символов
        return True
    # текста достаточно, но кириллицы почти нет — характерно для cp1251-mojibake рус. документа.
    # Порог 30 букв: на реальной странице мусора их сотни; ложное срабатывание лишь отправит
    # годную (напр. целиком латинскую) страницу на vision — vision её корректно транскрибирует.
    if diag.get("alpha_count", 0) >= 30 and diag.get("cyr_ratio", 1.0) < 0.15:
        return True
    # «словесная каша»: неправдоподобно короткие токены при объёме
    if diag.get("len", 0) > 200 and diag.get("avg_token_len", 99) < 2.0:
        return True
    return False


def _classify_page(page) -> str:
    """Статус страницы PDF: 'text' | 'garbage' | 'scan' | 'blank'."""
    txt = page.get_text()
    stripped = txt.strip()
    if len(stripped) < 10:
        # почти нет текста — скан, если есть изображения; иначе пустая страница
        try:
            has_images = bool(page.get_images())
        except Exception:
            has_images = False
        return "scan" if has_images else "blank"
    if _is_garbage(_text_diagnostics(txt)):
        return "garbage"
    return "text"


# --- Детект составного пакета (E.6.2) ---------------------------------------

# Заголовки-якоря, которые в норме СТОЯТ В ШАПКЕ самостоятельного документа
# (не встречаются как обычное слово в теле). Повтор одного якоря в шапке ≥2 страниц —
# сигнал, что в одном PDF склеены несколько документов одного типа (напр. 2 платёжки).
# Матчинг — по нормализованной (ё→е, нижний регистр, схлопнутые пробелы) шапке страницы.
_COMPOSITE_HEADER_ANCHORS = [
    "платежное поручение",
    "счет-фактура",
    "счет на оплату",
    "универсальный передаточный документ",
    "товарная накладная",
    "товарно-транспортная накладная",
    "приходный кассовый ордер",
    "расходный кассовый ордер",
]
# Судебные акты: якорь засчитывается ТОЛЬКО вместе с «арбитражный суд» в шапке —
# иначе «определение/решение» ловится в теле («суд вынес определение …»).
_COMPOSITE_COURT_ANCHORS = ["определение", "решение", "постановление"]

_COMPOSITE_HEAD_CHARS = 300          # «шапка» страницы — первые N символов
_INN_RE = re.compile(r"\b\d{10}\b|\b\d{12}\b")


def _norm_head(text: str) -> str:
    """Нормализованная шапка страницы для матчинга якорей."""
    head = (text or "")[:_COMPOSITE_HEAD_CHARS].lower().replace("ё", "е")
    return re.sub(r"\s+", " ", head)


def _detect_composite(text_parts, statuses) -> dict:
    """Эвристика склейки нескольких самостоятельных документов в одном PDF (E.6.2).

    Консервативно, чтобы НЕ гнать иск-с-приложениями (у него один заголовок, а
    приложения — с разными шапками): триггер — один заголовок-якорь в шапке ≥2
    РАЗНЫХ страниц. Множественные ИНН — только вспомогательная пометка при уже
    сработавшем триггере. Решение о split — агентское (в preview), здесь директива.
    Скан/мусор-страницы пропускаем: их текста ещё нет (vision отработает позже).
    """
    anchor_pages = {}   # ярлык якоря -> множество индексов страниц
    for i, (part, status) in enumerate(zip(text_parts, statuses)):
        if status != "text":
            continue
        head = _norm_head(part)
        for anchor in _COMPOSITE_HEADER_ANCHORS:
            if anchor in head:
                anchor_pages.setdefault(anchor, set()).add(i)
        if "арбитражный суд" in head:
            for anchor in _COMPOSITE_COURT_ANCHORS:
                if anchor in head:
                    anchor_pages.setdefault(anchor, set()).add(i)

    reasons = []
    for anchor, pages in sorted(anchor_pages.items()):
        if len(pages) >= 2:
            nums = ", ".join(str(p + 1) for p in sorted(pages))
            reasons.append(f"заголовок «{anchor}» — в шапке {len(pages)} стр. ({nums})")

    if reasons:
        inns = set()
        for part, status in zip(text_parts, statuses):
            if status == "text":
                inns.update(_INN_RE.findall(part or ""))
        if len(inns) >= 2:
            reasons.append(f"различных ИНН в документе: {len(inns)}")

    return {"composite_suspected": bool(reasons), "composite_reasons": reasons}


# --- Классификация сбоя открытия файла (E.14 а/б) ---------------------------

# Маркеры реальной порчи PDF в тексте исключения pymupdf/mupdf.
_CORRUPT_MARKERS = (
    "format error", "cannot open broken", "broken document", "no objects found",
    "syntax error", "damaged", "not a pdf", "cannot recognize", "bad xref",
)
# errno, характерные для НЕ материализованного файла на облачном маунте (OneDrive).
_MATERIALIZE_ERRNOS = {errno.ENOENT, errno.EIO, errno.ESTALE, errno.EACCES, errno.EAGAIN}
# Текстовые маркеры того же (когда errno недоступен — pymupdf оборачивает по-своему).
_MATERIALIZE_MSG_MARKERS = (
    "no such file", "cannot find", "not materialized", "input/output error", "stale file",
)


def classify_open_error(filepath: str, exc: Exception) -> tuple:
    """Различает 'файл не материализован (OneDrive/маунт)' vs 'реально битый' (E.14 а/б).

    Возвращает (error_class, retryable, message):
      - not_materialized / retryable=True  — файл-заглушка не синкнут; ретрай с паузой (rule 2).
      - corrupt          / retryable=False — данные PDF повреждены; ветка «битый файл».
      - empty            / retryable=False — файл нулевого размера.
    Порядок проверок: пусто → не материализован → битый → (по умолчанию) битый.
    """
    exc_name = type(exc).__name__
    msg = str(exc).lower()

    # 0-байтовый файл (в т.ч. pymupdf EmptyFileError) — не битый и не «дождись синка».
    try:
        if os.path.getsize(filepath) == 0:
            return ("empty", False, "файл нулевого размера")
    except OSError:
        pass  # getsize сам упал → отнесём к not_materialized ниже
    if exc_name == "EmptyFileError":
        return ("empty", False, "файл нулевого размера")

    # I/O-ошибки и отсутствие файла на маунте → вероятная дегидратация OneDrive → ретрай.
    oserrno = getattr(exc, "errno", None)
    if (isinstance(exc, FileNotFoundError) or oserrno in _MATERIALIZE_ERRNOS
            or any(m in msg for m in _MATERIALIZE_MSG_MARKERS)):
        return ("not_materialized", True,
                "файл не открылся на маунте — возможно, не синхронизирован OneDrive "
                "(cloud-only): сначала Read (материализует), затем ретрай с паузой")

    # Явные маркеры порчи PDF (pymupdf FileDataError и т.п.) → реально битый.
    if exc_name == "FileDataError" or any(m in msg for m in _CORRUPT_MARKERS):
        return ("corrupt", False, f"PDF повреждён, не открывается: {exc}")

    # Неизвестная ошибка на существующем ненулевом файле — считаем битым (не ретраить бесконечно).
    return ("corrupt", False, f"PDF не открывается: {exc}")


def _pdf_error(error_class: str, retryable: bool, message: str, pages: int = 0) -> dict:
    """Единый JSON-отказ PDF-извлечения с классификацией сбоя (E.14)."""
    return {"text": "", "method": "none", "confidence": "low", "pages": pages,
            "page_statuses": [], "needs_vision": False, "vision_pages": [],
            "vision_pages_suggested": [], "vision_reason": None,
            "structural_recommended": False,
            "composite_suspected": False, "composite_reasons": [],
            "error_class": error_class, "retryable": retryable,
            "warnings": [message]}


# --- Извлечение из PDF ------------------------------------------------------

def extract_pdf(filepath: str,
                max_head_pages: int = DEFAULT_MAX_HEAD_PAGES,
                structural_threshold: int = DEFAULT_STRUCTURAL_THRESHOLD) -> dict:
    """PDF: программный текст по страницам; решение needs_vision по статусам страниц.

    Vision — основной путь для скан/мусорных страниц (агентская сторона, см. shared/ocr.md).
    Здесь только директива: какие страницы и почему.
    """
    try:
        import fitz  # pymupdf
    except ImportError:
        return {"text": "", "method": "none", "confidence": "low", "pages": 0,
                "needs_vision": False, "vision_pages": [], "vision_reason": None,
                "structural_recommended": False,
                "warnings": ["pymupdf не установлен"]}

    try:
        doc = fitz.open(filepath)
    except Exception as e:
        # E.14 а/б: различаем «не материализован (OneDrive) → ретрай» и «реально битый → ветка битого».
        ec, rt, msg = classify_open_error(filepath, e)
        return _pdf_error(ec, rt, msg)

    pages = len(doc)
    statuses = []
    text_parts = []      # текст для 'text'-страниц; плейсхолдер для остальных
    try:
        for i, page in enumerate(doc):
            status = _classify_page(page)
            statuses.append(status)
            if status == "text":
                text_parts.append(page.get_text())
            elif status == "blank":
                text_parts.append("")
            else:  # scan / garbage — отдаётся vision
                text_parts.append(f"[[VISION_PAGE {i + 1}: {status}]]")
    except Exception as e:
        # Файл «открылся, но развалился» при чтении страниц — как правило дегидратация
        # cloud-only на маунте (E.14а): не падаем трейсбеком, а классифицируем.
        doc.close()
        ec, rt, msg = classify_open_error(filepath, e)
        return _pdf_error(ec, rt, msg, pages)
    doc.close()

    # страницы под vision (1-based для человека/агента)
    vision_idx = [i + 1 for i, s in enumerate(statuses) if s in ("scan", "garbage")]
    needs_vision = bool(vision_idx)
    has_garbage = any(s == "garbage" for s in statuses)
    has_scan = any(s == "scan" for s in statuses)

    if needs_vision:
        vision_reason = "garbage-layer" if has_garbage else "no-text-layer"
    else:
        vision_reason = None

    # структурный режим (F3.4): длинный документ под vision → не гнать ВСЕ страницы,
    # а полнотекстить голову + подписную, остальное — структурный скелет (решает агент)
    structural_recommended = needs_vision and pages > structural_threshold
    if structural_recommended:
        head = [i + 1 for i, s in enumerate(statuses)
                if s in ("scan", "garbage") and i < max_head_pages]
        tail = vision_idx[-1] if vision_idx else None
        suggested = sorted(set(head + ([tail] if tail else [])))
    else:
        suggested = vision_idx

    full_text = "\n\n---\n\n".join(text_parts)

    # confidence только для программной части; для vision-страниц confidence ставит агент
    if not needs_vision:
        avg_len = len(full_text) / max(pages, 1)
        confidence = "high" if avg_len > 200 else "medium" if avg_len > 50 else "low"
        method = "pdf-text"
    else:
        # гибрид (часть текстовых, часть vision) или полностью скан
        confidence = "pending-vision"
        method = "pdf-text+vision" if any(s == "text" for s in statuses) else "vision"

    # детект склейки нескольких документов в одном PDF (E.6.2)
    composite = _detect_composite(text_parts, statuses) if pages > 1 else {
        "composite_suspected": False, "composite_reasons": []}

    warnings = []
    if has_garbage:
        warnings.append("Обнаружен мусорный текстовый слой — страницы отправлены на vision (F3.3)")
    if structural_recommended:
        warnings.append(
            f"Длинный скан ({pages} стр.) — рекомендован структурный режим (F3.4): "
            f"полнотекст головы (первые {max_head_pages}) + подписной, остальное — скелет")
    if composite["composite_suspected"]:
        warnings.append(
            "Похоже на составной пакет (несколько документов в одном PDF, E.6.2): "
            + "; ".join(composite["composite_reasons"])
            + " — предложить split в preview")

    return {
        "text": full_text,
        "method": method,
        "confidence": confidence,
        "pages": pages,
        "page_statuses": statuses,
        "needs_vision": needs_vision,
        "vision_pages": vision_idx,
        "vision_pages_suggested": suggested,
        "vision_reason": vision_reason,
        "structural_recommended": structural_recommended,
        "composite_suspected": composite["composite_suspected"],
        "composite_reasons": composite["composite_reasons"],
        "warnings": warnings,
    }


# --- Извлечение из DOCX / TXT (без изменений по сути) ------------------------

def extract_docx_text(filepath: str) -> dict:
    """Извлечение текста из DOCX."""
    try:
        from docx import Document
    except ImportError:
        return {"text": "", "method": "none", "confidence": "low", "pages": 0,
                "needs_vision": False, "warnings": ["python-docx не установлен"]}

    doc = Document(filepath)
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    text = "\n\n".join(paragraphs)

    for table in doc.tables:
        rows = []
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells]
            rows.append(" | ".join(cells))
        if rows:
            text += "\n\n" + "\n".join(rows)

    return {
        "text": text,
        "method": "docx-parse",
        "confidence": "high",
        "pages": max(1, len(paragraphs) // 30),
        "needs_vision": False,
        "warnings": [],
    }


def extract_text_file(filepath: str) -> dict:
    """Чтение текстового файла (UTF-8 → cp1251 fallback)."""
    try:
        with open(filepath, "r", encoding="utf-8-sig") as f:   # -sig срезает BOM, если есть
            text = f.read()
    except UnicodeDecodeError:
        try:
            with open(filepath, "r", encoding="cp1251") as f:
                text = f.read()
        except Exception:
            return {"text": "", "method": "none", "confidence": "low", "pages": 0,
                    "needs_vision": False, "warnings": ["Не удалось прочитать файл"]}

    return {
        "text": text,
        "method": "text-read",
        "confidence": "high",
        "pages": 1,
        "needs_vision": False,
        "warnings": [],
    }


def extract_image(filepath: str) -> dict:
    """Изображение: vision — основной путь (не tesseract). Директива агенту."""
    return {
        "text": "",
        "method": "vision",
        "confidence": "pending-vision",
        "pages": 1,
        "needs_vision": True,
        "vision_pages": [1],
        "vision_pages_suggested": [1],
        "vision_reason": "image",
        "structural_recommended": False,
        "warnings": ["Изображение → vision (Read tool), см. shared/ocr.md"],
    }


# --- Рендер страницы в PNG для vision (F3.1) + guard обрезки (F3.5) ----------

def render_page_to_png(filepath: str, page_index0: int, render_dir: str,
                       width: int = DEFAULT_RENDER_WIDTH) -> dict:
    """Рендер одной страницы PDF в PNG через pymupdf.

    pymupdf рендерит детерминированно в процессе (без системного pdftoppm,
    который у файлового Read падает «unsafe location», F2.11). page_index0 — 0-based.
    Возвращает путь PNG + флаг cropped (сверка аспекта рендера и страницы, F3.5).
    """
    try:
        import fitz
    except ImportError:
        return {"path": None, "cropped": False, "warnings": ["pymupdf не установлен"]}

    try:
        doc = fitz.open(filepath)
        if page_index0 < 0 or page_index0 >= len(doc):
            doc.close()
            return {"path": None, "cropped": False,
                    "warnings": [f"Страница {page_index0 + 1} вне диапазона (всего {len(doc)})"]}
        page = doc[page_index0]
        rect = page.rect
        zoom = (width / rect.width) if rect.width else 2.0
        zoom = max(0.5, min(zoom, 4.0))    # разумные границы downscale/upscale
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat)
        os.makedirs(render_dir, exist_ok=True)
        out = os.path.join(render_dir, f"{Path(filepath).stem}_p{page_index0 + 1}.png")
        pix.save(out)
        # guard обрезки: аспект PNG должен совпасть с аспектом страницы
        page_aspect = (rect.width / rect.height) if rect.height else 0
        img_aspect = (pix.width / pix.height) if pix.height else 0
        cropped = page_aspect > 0 and abs(page_aspect - img_aspect) > 0.02 * page_aspect
        doc.close()
        warnings = []
        if cropped:
            warnings.append(
                f"cropped_render: PNG стр. {page_index0 + 1} обрезан "
                f"(аспект {img_aspect:.3f} ≠ страница {page_aspect:.3f}) — проверить рендер (F3.5)")
        return {"path": out, "width": pix.width, "height": pix.height,
                "cropped": cropped, "warnings": warnings}
    except Exception as e:
        # E.14а: тот же разбор — не материализован (ретрай) vs битый.
        ec, rt, msg = classify_open_error(filepath, e)
        return {"path": None, "cropped": False, "error_class": ec, "retryable": rt,
                "warnings": [f"Рендер не удался: {msg}"]}


# --- Tesseract спот-сверка одного поля (F3.1, опционально, вариант B) --------

def find_tessdata() -> str:
    """Путь к вендоренным tessdata: $VASSAL_TESSDATA или scripts/tessdata/."""
    env = os.environ.get("VASSAL_TESSDATA")
    if env and os.path.exists(os.path.join(env, "rus.traineddata")):
        return env
    vendored = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tessdata")
    if os.path.exists(os.path.join(vendored, "rus.traineddata")):
        return vendored
    return ""


def spot_check_field(image_path: str, tessdata_dir: str = "") -> dict:
    """Tesseract по КРОПУ одного поля (--psm 7, одна строка), независимое чтение.

    Только для одиночного критичного реквизита (цифра в ИНН/сумме/дате), где vision
    не уверен. На целую страницу не запускать — упирается в таймаут.
    """
    tessdata_dir = tessdata_dir or find_tessdata()
    if not tessdata_dir:
        return {"text": "", "available": False,
                "warnings": ["rus.traineddata не найден (scripts/tessdata/ или $VASSAL_TESSDATA) — спот-сверка пропущена"]}
    env = dict(os.environ)
    env["TESSDATA_PREFIX"] = tessdata_dir
    try:
        result = subprocess.run(
            ["tesseract", image_path, "stdout", "-l", "rus", "--psm", "7"],
            capture_output=True, text=True, timeout=30, env=env
        )
        return {"text": result.stdout.strip(), "available": True, "warnings": []}
    except FileNotFoundError:
        return {"text": "", "available": False,
                "warnings": ["бинарь tesseract не найден — спот-сверка пропущена"]}
    except subprocess.TimeoutExpired:
        return {"text": "", "available": False,
                "warnings": ["tesseract таймаут на кропе — спот-сверка пропущена"]}


# --- Диспетчер --------------------------------------------------------------

def extract(filepath: str,
            max_head_pages: int = DEFAULT_MAX_HEAD_PAGES,
            structural_threshold: int = DEFAULT_STRUCTURAL_THRESHOLD) -> dict:
    """Определяет тип файла и вызывает нужный экстрактор. Добавляет content_hash."""
    ext = Path(filepath).suffix.lower()

    if ext == ".pdf":
        result = extract_pdf(filepath, max_head_pages, structural_threshold)
    elif ext == ".docx":
        result = extract_docx_text(filepath)
    elif ext in (".txt", ".md", ".csv", ".html", ".htm", ".xml", ".json", ".yaml", ".yml"):
        result = extract_text_file(filepath)
    elif ext in (".jpg", ".jpeg", ".png", ".tiff", ".tif", ".bmp"):
        result = extract_image(filepath)
    elif ext in (".doc", ".rtf", ".odt"):
        result = {"text": "", "method": "none", "confidence": "low", "pages": 0,
                  "needs_vision": False,
                  "warnings": [f"Формат {ext} не поддерживается программно. Используй Read tool."]}
    else:
        result = {"text": "", "method": "none", "confidence": "low", "pages": 0,
                  "needs_vision": False, "warnings": [f"Неизвестный формат: {ext}"]}

    result["content_hash"] = compute_content_hash(filepath)
    # нормализуем поля контракта (для единообразия выхода)
    result.setdefault("needs_vision", False)
    result.setdefault("vision_pages", [])
    result.setdefault("vision_pages_suggested", result.get("vision_pages", []))
    result.setdefault("vision_reason", None)
    result.setdefault("structural_recommended", False)
    result.setdefault("composite_suspected", False)   # E.6.2 — только PDF взводит
    result.setdefault("composite_reasons", [])
    result.setdefault("low_confidence_fields", [])   # заполняется vision-ногой агента
    result.setdefault("error_class", None)           # E.14 — not_materialized|corrupt|empty (иначе None)
    result.setdefault("retryable", False)            # E.14 — True → ретрай с паузой (не «битый»)
    return result


# --- CLI --------------------------------------------------------------------

def _get_opt(argv, name, default=None):
    if name in argv:
        i = argv.index(name)
        if i + 1 < len(argv):
            return argv[i + 1]
    return default


def main():
    # Печатаем UTF-8 независимо от консоли ОС (Windows cp1251 иначе рвёт кириллицу/BOM;
    # в Cowork/Linux безвредно — там stdout уже UTF-8).
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

    argv = sys.argv[1:]
    if not argv:
        print("Использование: python3 extract_text.py <файл> [--output-dir DIR] [--render-dir DIR]")
        print("               python3 extract_text.py --render <pdf> --page N [--render-dir DIR] [--width W]")
        print("               python3 extract_text.py --spot-check <crop.png> [--tessdata DIR]")
        sys.exit(1)

    # Режим 3: спот-сверка поля
    if "--spot-check" in argv:
        img = _get_opt(argv, "--spot-check")
        if not img or not os.path.exists(img):
            print(json.dumps({"error": f"Изображение не найдено: {img}"}, ensure_ascii=False))
            sys.exit(1)
        print(json.dumps(spot_check_field(img, _get_opt(argv, "--tessdata", "")),
                         ensure_ascii=False, indent=2))
        return

    # Режим 2: рендер одной страницы
    if "--render" in argv:
        pdf = _get_opt(argv, "--render")
        if not pdf or not os.path.exists(pdf):
            print(json.dumps({"error": f"Файл не найден: {pdf}"}, ensure_ascii=False))
            sys.exit(1)
        page = int(_get_opt(argv, "--page", "1"))
        render_dir = _get_opt(argv, "--render-dir", os.path.join(os.getcwd(), "outputs", "renders"))
        width = int(_get_opt(argv, "--width", str(DEFAULT_RENDER_WIDTH)))
        print(json.dumps(render_page_to_png(pdf, page - 1, render_dir, width),
                         ensure_ascii=False, indent=2))
        return

    # Режим 1: извлечение
    filepath = argv[0]
    if not os.path.exists(filepath):
        # E.14а: на облачном маунте отсутствие enumerated-файла — почти всегда дегидратация
        # (скилл приёма передаёт реально перечисленные файлы), а не «нет такого файла».
        # Отдаём структурный JSON с retryable, чтобы скилл сделал ретрай с паузой, а не «битый».
        print(json.dumps({
            "text": "", "method": "none", "confidence": "low", "pages": 0,
            "needs_vision": False, "content_hash": "",
            "error_class": "not_materialized", "retryable": True,
            "warnings": [f"Файл не найден на маунте: {filepath} — возможно, не синхронизирован "
                         f"OneDrive (cloud-only); сначала Read (материализует), затем ретрай с паузой"],
        }, ensure_ascii=False, indent=2))
        return

    max_head = int(_get_opt(argv, "--max-head-pages", str(DEFAULT_MAX_HEAD_PAGES)))
    threshold = int(_get_opt(argv, "--structural-threshold", str(DEFAULT_STRUCTURAL_THRESHOLD)))
    result = extract(filepath, max_head, threshold)

    output_dir = _get_opt(argv, "--output-dir")
    if output_dir and result.get("text"):
        os.makedirs(output_dir, exist_ok=True)
        txt_path = os.path.join(output_dir, Path(filepath).stem + ".txt")
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(result["text"])
        result["saved_to"] = txt_path

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
