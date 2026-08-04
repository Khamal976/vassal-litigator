# -*- coding: utf-8 -*-
"""Механическая сверка счёта: число объявлено — а список под ним другой.

Класс дефекта, ради которого написан скрипт, на этом проекте не поймала ни
одна из двенадцати смысловых проверок. Причина структурная: проверяющий
читает СМЫСЛ, а не считает строки. Во вводной строке стоит «пять условий»,
таблица под ней за три захода выросла до шести — и текст остаётся связным,
правдоподобным и неверным. Четыре таких расхождения в справочнике по убыткам
прожили по два-три захода и нашлись только сплошным пересчётом вручную.

Скрипт НЕ решает, прав ли автор: он находит в тексте числовые заявления
(«три ветки», «все тринадцать статей», «шесть вопросов») и механически
считает то, что идёт следом — пункты списка, строки таблицы, номера
нумерации. Результат — конечный список мест для просмотра глазами, ровно как
у `verify_coverage.py`.

Что считается перечнем. Сначала — перечень В ТОЙ ЖЕ СТРОКЕ после двоеточия
(«Три способа (п. 2): взыскание…; продажа…; уступка…»): в юридическом тексте
это самая частая форма, и именно она давала весь шум первой версии. Если его
нет — первый блок в пределах LOOKAHEAD строк:
  * маркированный список          - пункт / * пункт
  * нумерованный список           1. пункт / **1.** пункт / 1) пункт
  * буквенный список              а) пункт / (а) пункт / A. пункт
  * таблица markdown              строки данных, без шапки и разделителя
  * жирные подзаголовки подряд    **Первое.** … **Второе.** …
  * подразделы                    ### §7.1 … ### §7.2 (для заголовочных заявок)

Заявки, под которыми не опознано вообще никакой считаемой структуры, идут
отдельным коротким списком в конце: это не находки, а места, где машина
бессильна и нужен глаз.

Запуск:
    python verify_counts.py <файл> [ещё файлы]
    python verify_counts.py <файл> --all      # печатать и сошедшиеся
    python verify_counts.py <файл> --lookahead 60
"""
import sys, os, re

LOOKAHEAD = 40          # сколько строк вперёд искать перечень
GAP = 8                 # сколько пустых/прозаических строк допустимо до начала перечня

NUM = {
    'один': 1, 'одна': 1, 'одно': 1, 'одного': 1, 'одной': 1,
    'два': 2, 'две': 2, 'двух': 2, 'оба': 2, 'обе': 2, 'обоих': 2,
    'три': 3, 'трёх': 3, 'трех': 3,
    'четыре': 4, 'четырёх': 4, 'четырех': 4,
    'пять': 5, 'пяти': 5,
    'шесть': 6, 'шести': 6,
    'семь': 7, 'семи': 7,
    'восемь': 8, 'восьми': 8,
    'девять': 9, 'девяти': 9,
    'десять': 10, 'десяти': 10,
    'одиннадцать': 11, 'одиннадцати': 11,
    'двенадцать': 12, 'двенадцати': 12,
    'тринадцать': 13, 'тринадцати': 13,
    'четырнадцать': 14, 'четырнадцати': 14,
    'пятнадцать': 15, 'пятнадцати': 15,
    'шестнадцать': 16, 'шестнадцати': 16,
    'семнадцать': 17, 'семнадцати': 17,
    'восемнадцать': 18, 'восемнадцати': 18,
    'девятнадцать': 19, 'девятнадцати': 19,
    'двадцать': 20, 'двадцати': 20,
}

# Существительные, при которых число — заявка на длину перечня. Список
# закрытый намеренно: открытый даёт шум из дат, сумм, сроков и реквизитов
# («три года», «пять миллионов», «три рабочих дня» — не перечни).
NOUNS = r"""услови элемент якор вопрос ветк основани критери признак презумпц
позици случа способ маршрут шаг лини стади довод тест механизм ловушк грани
форм блок вид тип состав фигур ситуац развилк исключен изъят требован
подпункт разъяснен адресат потребител сценар оговорк реквизит проверк
ось оси набор перечн разновидност уровн эшелон аргумент возражен контрдовод
дат сроков-типов""".split()
NOUN_RE = '|'.join(NOUNS)

# «три ветки», «все тринадцать статей», «шесть вопросов», «13 статей».
CLAIM = re.compile(
    r'(?<![\w§№.])(?P<num>\d{1,2}|' + '|'.join(NUM) + r')\s+'
    r'(?:[а-яё]+\s+){0,2}?'                       # «три кумулятивных условия»
    r'(?P<noun>(?:' + NOUN_RE + r')[а-яё]*)',
    re.I)

# Заявки вида «все тринадцать статей», «пункты 26(1)-26(11)» — усилители.
EMPH = re.compile(r'\b(все[хм]?|всего|ровно|целых)\s+$', re.I)

BULLET = re.compile(r'^\s{0,6}[-*+]\s+\S')
NUMBERED = re.compile(r'^\s{0,6}(?:\*\*)?(\d{1,2})[.)](?:\*\*)?\s+\S')
LETTERED = re.compile(r'^\s{0,6}\(?([а-яa-z])\)\s+\S', re.I)
TABLE = re.compile(r'^\s*\|')
TABLE_SEP = re.compile(r'^\s*\|[\s:|-]+\|\s*$')
SUBHEAD = re.compile(r'^(#{2,4})\s+(?:§?[\d.]+\.?|[A-FА-Я]\.)\s*\S')
BOLD_LEAD = re.compile(r'^\s{0,6}\*\*(?:[А-ЯЁA-Z][а-яёa-z-]+|\d{1,2})[.)]?\*\*[\s—-]')
# Строка, обрывающая перечень: новый заголовок верхнего уровня или разделитель.
BREAK = re.compile(r'^(?:#{1,2}\s|---\s*$|___\s*$)')

# Обороты, при которых число не про длину перечня, а про что-то ещё.
SKIP_CTX = re.compile(
    r'\b(?:из\s+\d|из\s+(?:' + '|'.join(NUM) + r')\b'          # «51 пункт из 96»
    r'|год|лет|дн|месяц|недел|рубл|процент|%'
    r'|редакц|№|абзац\s+втор|части\s+втор)', re.I)

# Заявка не объявляет перечень, а ОТСЫЛАЕТ к нему: «по всем шести вопросам»,
# «три сценария (§10.9)». Перечень лежит в другом месте, считать под строкой
# нечего — и первая версия скрипта давала здесь чистый шум.
BACKREF = re.compile(r'\b(?:по\s+всем|по\s+этим|всех?\s+эти[хм]|тех?\s+же|названн\w+|'
                     r'перечисленн\w+|указанн\w+|упомянут\w+|выше|обои[хм]|оба|обе)\b', re.I)
XREF = re.compile(r'§\s?\d|см\.\s')


def numval(tok):
    tok = tok.lower().replace('ё', 'е')
    if tok.isdigit():
        return int(tok)
    for k, v in NUM.items():
        if k.replace('ё', 'е') == tok:
            return v
    return None


MARKER = re.compile(r'(?:^|[\s(])\(?(\d{1,2})\)\s+(?=[а-яёa-z«"*])')


def split_top(s, sep=';'):
    """Деление по разделителю на верхнем уровне: скобки и кавычки-ёлочки
    не режем — внутри цитаты и ссылки на норму точка с запятой своя."""
    out, depth, quote, cur = [], 0, False, []
    for ch in s:
        if ch == '(':
            depth += 1
        elif ch == ')':
            depth = max(0, depth - 1)
        elif ch == '«':
            quote = True
        elif ch == '»':
            quote = False
        if ch == sep and depth == 0 and not quote:
            out.append(''.join(cur))
            cur = []
        else:
            cur.append(ch)
    out.append(''.join(cur))
    return [x for x in (p.strip() for p in out) if x]


def inline_after(line, pos):
    """Перечень в той же строке после двоеточия. Возвращает (вид, N) или None."""
    colon = line.find(':', pos)
    if colon < 0 or colon - pos > 90:
        return None
    tail = line[colon + 1:]
    if len(tail.strip()) < 15:
        return None
    marks = [int(m.group(1)) for m in MARKER.finditer(tail)]
    if len(marks) >= 2 and marks[0] == 1 and marks == list(range(1, len(marks) + 1)):
        return ('перечень в строке, нумерованный', len(marks))
    parts = split_top(tail.rstrip(' .'))
    if len(parts) >= 2:
        return ('перечень в строке через «;»', len(parts))
    return None


def block_after(lines, start):
    """Первый перечень, начинающийся в пределах GAP строк после `start`.

    Возвращает (вид, число элементов, строка начала, строка конца) или None.
    """
    i = start + 1
    seen_prose = 0
    while i < len(lines) and i <= start + LOOKAHEAD:
        ln = lines[i]
        if BREAK.match(ln):
            return None
        if not ln.strip():
            i += 1
            continue
        if TABLE.match(ln):
            return count_table(lines, i)
        if NUMBERED.match(ln):
            return count_run(lines, i, NUMBERED, 'нумерованный список')
        if BULLET.match(ln):
            return count_run(lines, i, BULLET, 'маркированный список')
        if LETTERED.match(ln):
            return count_run(lines, i, LETTERED, 'буквенный список')
        if SUBHEAD.match(ln):
            return count_run(lines, i, SUBHEAD, 'подразделы')
        if BOLD_LEAD.match(ln):
            return count_run(lines, i, BOLD_LEAD, 'жирные подзаголовки')
        seen_prose += 1
        if seen_prose > GAP:
            return None
        i += 1
    return None


def count_table(lines, i):
    rows, j = 0, i
    while j < len(lines) and TABLE.match(lines[j]):
        if not TABLE_SEP.match(lines[j]):
            rows += 1
        j += 1
    return ('таблица', max(0, rows - 1), i, j - 1)      # минус строка шапки


def count_run(lines, i, pat, kind):
    """Считает подряд идущие элементы одного вида, допуская пустые строки
    и «хвосты» — продолжение элемента с отступом или прозой под ним."""
    n, j, blanks = 0, i, 0
    last = i
    while j < len(lines):
        ln = lines[j]
        if BREAK.match(ln) and j > i:
            break
        if pat.match(ln):
            n += 1
            last = j
            blanks = 0
        elif not ln.strip():
            blanks += 1
            if blanks > 2:
                break
        else:
            # чужой перечень другого вида на том же месте обрывает счёт
            for other in (TABLE, NUMBERED, BULLET, LETTERED, SUBHEAD):
                if other is not pat and other.match(ln):
                    if j - last > 1:
                        return (kind, n, i, last)
            blanks = 0
        j += 1
    return (kind, n, i, last)


def check(path, show_all=False):
    with open(path, encoding='utf-8') as f:
        lines = f.read().split('\n')

    print('=' * 72)
    print('ФАЙЛ: %s' % os.path.basename(path))
    print('=' * 72)

    claims = mism = agreed = 0
    unknown = []
    in_fence = False
    for idx, ln in enumerate(lines):
        if ln.strip().startswith('```'):
            in_fence = not in_fence
        if in_fence or not ln.strip():
            continue
        for m in CLAIM.finditer(ln):
            n = numval(m.group('num'))
            if n is None or n < 2 or n > 30:
                continue
            tail = ln[m.end():m.end() + 40]
            if SKIP_CTX.search(tail) or SKIP_CTX.search(ln[max(0, m.start() - 25):m.start()]):
                continue
            if BACKREF.search(ln[max(0, m.start() - 30):m.end()]) or XREF.search(tail):
                continue
            claims += 1
            frag = ln.strip()
            if len(frag) > 110:
                frag = frag[:107] + '...'

            inl = inline_after(ln, m.end())
            blk = block_after(lines, idx)
            # Сошлось хоть по одной структуре — заявка подтверждена: перечень
            # бывает и в строке, и списком под ней (шапка + расшифровка).
            cands = [c for c in (inl, blk) if c is not None]
            if not cands:
                unknown.append((idx + 1, m.group('num'), m.group('noun'), n, frag))
                continue
            ok = any(c[1] == n for c in cands)
            if ok:
                agreed += 1
                if not show_all:
                    continue
            else:
                mism += 1
            print()
            print('[стр. %d] %s' % (idx + 1, 'СОШЛОСЬ' if ok else 'РАСХОЖДЕНИЕ'))
            print('   заявка: «%s %s» — %d' % (m.group('num'), m.group('noun'), n))
            print('   строка: %s' % frag)
            if inl:
                print('   перечень: %s, элементов %d' % (inl[0], inl[1]))
            if blk:
                print('   перечень: %s, элементов %d (стр. %d-%d)'
                      % (blk[0], blk[1], blk[2] + 1, blk[3] + 1))

    if unknown:
        print()
        print('- - - структура не опознана (машина бессильна, смотреть глазами) - - -')
        for line, tok, noun, n, frag in unknown:
            print('  стр. %-5d «%s %s» = %d | %s' % (line, tok, noun, n, frag[:78]))

    print()
    print('-' * 72)
    print('ИТОГ %s: заявок %d — сошлось %d, расхождений %d, не опознано %d'
          % (os.path.basename(path), claims, agreed, mism, len(unknown)))
    return mism


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    show_all = '--all' in sys.argv
    if '--lookahead' in sys.argv:
        global LOOKAHEAD
        LOOKAHEAD = int(sys.argv[sys.argv.index('--lookahead') + 1])
        args = [a for a in args if a != str(LOOKAHEAD)]
    if not args:
        print(__doc__)
        return 1
    total = sum(check(p, show_all) for p in args if os.path.exists(p))
    print()
    print('=' * 72)
    print('ВСЕГО МЕСТ ДЛЯ СВЕРКИ: %d' % total)
    print('Скрипт не решает, кто прав: он показывает, где число и перечень')
    print('могли разойтись. Каждое место смотреть глазами.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
