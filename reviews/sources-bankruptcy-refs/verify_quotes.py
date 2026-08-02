# -*- coding: utf-8 -*-
"""Машинная проверка дословности цитат в драфте справочника.

Берёт каждый фрагмент в кавычках «...» и ищет его в корпусе первоисточников
(тексты Пленумов, нормы ФЗ-127 и НК, добранные акты, карта практики).
Расхождение хотя бы в одном символе — находка: выдуманная или «подправленная»
цитата в производственном юридическом тексте опаснее отсутствующей.

Запуск:  python verify_quotes.py <файл-драфта> [ещё файлы]
"""
import sys, os, re, glob, unicodedata, difflib

REF = os.path.dirname(os.path.abspath(__file__))
CORPUS_GLOBS = [
    os.path.join(REF, 'texts', '*.txt'),
    os.path.join(REF, 'texts', 'fz127', '*.txt'),
    os.path.join(REF, 'sources0', '*.txt'),
    os.path.join(REF, 'sources0', '*.md'),
    os.path.join(REF, 'practice-map.md'),
    os.path.join(REF, 'check-mine.md'),
]
MIN_LEN = 40          # короткие обороты и реквизиты не проверяем
CONTEXT = 60          # сколько символов показать у ближайшего варианта


def norm(s):
    """Нормализация, снимающая типографику, но не меняющая слов."""
    s = unicodedata.normalize('NFKC', s)
    s = s.replace('ё', 'е').replace('Ё', 'Е')
    s = re.sub(r'[«»""„“”]', '"', s)
    s = re.sub(r'[‐-―−-]', '-', s)
    s = re.sub(r'\s+', ' ', s)
    return s.strip().lower()


# Хвост файла источника, куда fetch_source.py складывает примечания редакции
# КонсультантПлюс. Это НЕ текст акта: по ним датируются редакции, но цитировать
# их как норму нельзя. В корпус проверки они не входят — иначе цитата из
# примечания прошла бы сверку как дословная цитата самого акта.
#
# Маркер ищется ТОЛЬКО с начала строки. Блок ПРОВЕНАНС сам упоминает его в
# тексте («…вынесены в конец файла под заголовок «ВРЕЗКИ КонсультантПлюс»»),
# и поиск подстрокой обрезал такой файл на девятой строке: акт целиком выпадал
# из корпуса, а его дословные цитаты объявлялись ненайденными.
NOTES_MARKER = re.compile(r'(?m)^ВРЕЗКИ КонсультантПлюс')


def cut_notes(text):
    hits = list(NOTES_MARKER.finditer(text))
    return text[:hits[-1].start()] if hits else text


def load_corpus():
    parts, names = [], []
    for pattern in CORPUS_GLOBS:
        for path in sorted(glob.glob(pattern)):
            try:
                text = open(path, encoding='utf-8').read()
            except OSError:
                continue
            parts.append(norm(cut_notes(text)))
            names.append(os.path.relpath(path, REF))
    return parts, names


def strip_markup(q):
    """Снимает разметку цитирования, не трогая слова.

    В markdown цитата часто идёт блоком «> ...», абзацы внутри неё склеиваются
    авторским «//», а усечение обозначается многоточием. Всё это — оформление,
    а не текст источника, и сравнивать надо без него.
    """
    q = re.sub(r'(?m)^\s*>\s?', ' ', q)
    q = q.replace('//', ' ')
    # Выделение внутри цитаты — типографика автора, а не текст источника:
    # юрист подчёркивает решающие слова нормы, и это не подмена.
    q = q.replace('**', '').replace('__', '')
    q = re.sub(r'^\s*(?:\.{2,}|…)\s*|\s*(?:\.{2,}|…)\s*$', ' ', q)
    return q.strip()


def fragments(q):
    """Цитата с усечением внутри: многоточие — не текст, а пропуск.

    Такую цитату проверяем по кускам: каждый должен найтись в одном и том же
    источнике и в том же порядке. Это ловит подмену внутри цитаты, но не
    придирается к законному сокращению.
    """
    parts = [p.strip() for p in re.split(r'\.{2,}|…', q) if len(p.strip()) >= 15]
    return parts or [q]


def found_in(q, text):
    pos = 0
    for frag in fragments(q):
        idx = text.find(frag, pos)
        if idx == -1:
            return False
        pos = idx + len(frag)
    return True


def extract_quotes(text):
    """Цитаты в «ёлочках», включая многострочные."""
    out = []
    for m in re.finditer(r'«([^«»]{%d,})»' % MIN_LEN, text, re.S):
        q = strip_markup(m.group(1))
        if len(q) < MIN_LEN:
            continue
        line = text.count('\n', 0, m.start()) + 1
        out.append((line, q))
    return out


def closest(needle, parts, names):
    """Ближайший фрагмент корпуса — чтобы было видно, чем цитата отличается."""
    best = (0.0, '', '')
    head = needle[:40]
    for text, name in zip(parts, names):
        idx = text.find(head[:20])
        while idx != -1 and best[0] < 0.99:
            cand = text[idx:idx + len(needle) + 20]
            r = difflib.SequenceMatcher(None, needle, cand).ratio()
            if r > best[0]:
                best = (r, cand[:len(needle) + CONTEXT], name)
            idx = text.find(head[:20], idx + 1)
    return best


def check(path, parts, names):
    # сам проверяемый файл из корпуса исключаем: иначе цитата подтвердит сама себя
    here = os.path.abspath(path)
    keep = [(t, n) for t, n in zip(parts, names)
            if os.path.abspath(os.path.join(REF, n)) != here]
    parts = [t for t, _ in keep]
    names = [n for _, n in keep]
    text = open(path, encoding='utf-8').read()
    quotes = extract_quotes(text)
    ok = miss = 0
    print('=' * 70)
    print('ФАЙЛ: %s — цитат к проверке: %d' % (os.path.basename(path), len(quotes)))
    print('=' * 70)
    for line, raw in quotes:
        q = norm(raw)
        found = next((n for t, n in zip(parts, names) if found_in(q, t)), None)
        if found:
            ok += 1
            continue
        miss += 1
        ratio, cand, src = closest(q, parts, names)
        print('\n[строка %d] ❌ ДОСЛОВНО НЕ НАЙДЕНА (лучшее совпадение %.2f, %s)'
              % (line, ratio, src or '—'))
        print('  В ДРАФТЕ:    %s' % raw.strip()[:220].replace('\n', ' '))
        if cand:
            print('  В ИСТОЧНИКЕ: %s' % cand[:220])
    print('\nИТОГ по файлу: подтверждено %d, не найдено %d' % (ok, miss))
    return miss


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    parts, names = load_corpus()
    print('корпус: %d файлов' % len(parts))
    total = sum(check(p, parts, names) for p in sys.argv[1:] if os.path.exists(p))
    print('\n%s\nВСЕГО НЕПОДТВЕРЖДЁННЫХ ЦИТАТ: %d' % ('=' * 70, total))
    return 1 if total else 0


if __name__ == '__main__':
    sys.exit(main())
