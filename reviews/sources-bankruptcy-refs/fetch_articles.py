# -*- coding: utf-8 -*-
"""Пакетный добор статей кодекса/закона с КонсультантПлюс.

Оглавление документа на consultant.ru содержит ссылку на каждую статью.
Скрипт резолвит «Статья N» в её URL и вызывает fetch_source для каждой.

Дисциплина: если статья в оглавлении не найдена или найдена больше одного
раза — скрипт НЕ угадывает, а докладывает и пропускает. Молчаливая подстановка
соседней статьи здесь дороже пропуска.

Запуск:
    python fetch_articles.py <LAW_ID> <префикс-файла> <ст> [<ст> ...] --reason "..."
Пример:
    python fetch_articles.py cons_doc_LAW_5142 gk 53.1 15 393 --reason "состав убытков"
"""
import re, sys, os, argparse, urllib.request, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}


# Номер статьи в оглавлении: 49, 225.10, 225.10-1. Дефис — часть номера, а не
# диапазон. Прежний шаблон '([\d.]+?)\.?\s' обрывался на дефисе, и статьи вида
# 225.10-1 не попадали в таблицу ВОВСЕ — запрос по ним отвечал «не найдена»,
# хотя статья в оглавлении есть. Тот же класс, что и потерянная точка у п. 37(2)
# в ppvs53.txt: один символ шаблона — и единица источника невидима.
ART_RE = re.compile(r"^Статья\s+(\d+(?:\.\d+)?(?:-\d+)*)\.\s")
# «Статья 225.11, статья 225.12. Утратили силу» — одна строка на две статьи.
# Под ART_RE она не подходит (после номера запятая), и без отдельной ветки
# запрошенная 225.11 попадала в «не найдены в оглавлении» — то есть в тот же
# отчёт, что и опечатка в номере. Это разные диагнозы: искать нечего.
GONE_RE = re.compile(r"[Уу]тратил[аи]? силу")
ANY_ART_RE = re.compile(r"[Сс]тать[яи]\s+(\d+(?:\.\d+)?(?:-\d+)*)")


def toc(law_id):
    """({номер: [(url, заголовок)]}, {номер: строка}, [неразобранные строки]).

    Третий элемент — строки оглавления, начинающиеся со слова «Статья», но не
    разобранные ни одним шаблоном. Он всегда печатается: молчаливый пропуск
    строки оглавления и есть механизм, которым источник теряется незаметно.
    """
    url = "https://www.consultant.ru/document/%s/" % law_id
    req = urllib.request.Request(url, headers=UA)
    h = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "replace")
    pat = r'<a[^>]+href="(/document/%s/[0-9a-f]{20,}/)"[^>]*>(.*?)</a>' % re.escape(law_id)
    out, gone, unparsed = {}, {}, []
    for href, label in re.findall(pat, h, re.S):
        lab = re.sub(r"<[^>]+>", "", label)
        lab = re.sub(r"\s+", " ", lab).strip()
        if not lab.startswith("Статья"):
            continue
        if GONE_RE.search(lab):
            for num in ANY_ART_RE.findall(lab):
                gone[num] = lab
            continue
        m = ART_RE.match(lab)
        if not m:
            unparsed.append(lab)
            continue
        out.setdefault(m.group(1), []).append(("https://www.consultant.ru" + href, lab))
    return out, gone, unparsed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("law_id")
    ap.add_argument("prefix")
    ap.add_argument("articles", nargs="+")
    ap.add_argument("--reason", default="")
    ap.add_argument("--act", default="", help="название акта для строки заголовка")
    ap.add_argument("--outdir", default=os.path.join(HERE, "sources0"))
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()

    table, gone, unparsed = toc(a.law_id)
    print("toc entries:", len(table))
    if unparsed:
        print("НЕРАЗОБРАННЫЕ строки оглавления (%d):" % len(unparsed))
        for lab in unparsed:
            print("   ?", lab)

    missing, repealed, ambiguous, done = [], [], [], []
    for art in a.articles:
        hits = table.get(art)
        if not hits:
            (repealed if art in gone else missing).append(art)
            continue
        if len(hits) > 1:
            ambiguous.append((art, [u for u, _ in hits]))
            continue
        url, lab = hits[0]
        out = os.path.join(a.outdir, "%s-%s.txt" % (a.prefix, art))
        print("ART %-8s -> %s" % (art, url))
        if a.dry:
            continue
        title = ("%s. %s" % (a.act, lab)) if a.act else lab
        cmd = [sys.executable, os.path.join(HERE, "fetch_source.py"), url, out,
               "--title", title, "--reason", a.reason]
        # Дочерний процесс печатает кириллицу в кодировке консоли Windows (cp1251),
        # а не в utf-8; строгое декодирование рвёт отчёт целиком. Статистика,
        # которую мы отсюда читаем, — ASCII, поэтому подмена символов безопасна.
        r = subprocess.run(cmd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        tag = "OK " if r.returncode == 0 else "ERR"
        stats = " ".join(l.strip() for l in (r.stdout or "").splitlines()
                         if l.startswith(("chars", "paragraphs", "konsultant_notes",
                                          "reclaimed_to_body", "pagination")))
        print("   %s %s" % (tag, stats))
        if r.returncode != 0:
            print("   STDERR:", (r.stderr or "")[:300])
        else:
            done.append(out)

    print("\n=== ИТОГ ===")
    print("получено:", len(done))
    if repealed:
        for art in repealed:
            print("УТРАТИЛА СИЛУ:", art, "—", gone[art])
    if missing:
        print("НЕ НАЙДЕНЫ в оглавлении (проверить руками):", ", ".join(missing))
    if ambiguous:
        for art, urls in ambiguous:
            print("НЕОДНОЗНАЧНО:", art, urls)


if __name__ == "__main__":
    main()
