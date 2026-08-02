# -*- coding: utf-8 -*-
"""Обратная проверка: что в акте есть, а в справочнике не использовано.

`verify_quotes.py` и `verify_addresses.py` идут ОТ СПРАВОЧНИКА: верна ли
цитата, тот ли адрес. Оба по построению слепы к пропуску — норма, которую
следовало учесть, но которую справочник не называет вовсе, для них не
существует. Этот скрипт идёт В ОБРАТНУЮ СТОРОНУ: берёт акт целиком и
показывает, какие его пункты справочник не упоминает ни разу.

Скрипт НЕ говорит, должен ли пункт быть использован — это вопрос правовой,
и машина его не решает. Он превращает безразмерное «а не упустили ли мы
что-нибудь» в конечный список, который можно просмотреть глазами. Ровно так
вручную был переработан справочник по оспариванию: 46 задействованных
пунктов Пленума № 63 из 47 против прежних 20.

Пункт считается использованным по любому из двух признаков:
  * дословная цитата из него найдена в справочнике (через locate());
  * он назван в прозе рядом с именем акта («п. 68 Постановления № 53»).
Второй признак обязателен: справочники `legal-review` излагают норму своими
словами со ссылкой, и по одним цитатам их покрытие было бы нулевым.

Запуск:
    python verify_coverage.py <файл-справочника> [ещё файлы]
    python verify_coverage.py <файл> --act 53      # только один акт
    python verify_coverage.py <файл> --used        # печатать и использованные
"""
import sys, os, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import verify_addresses as V


# Номер акта → как он зовётся в отчёте load_acts(). Ключ — номер, потому что
# в корпусе все номера различны, а форм написания у каждого акта штук пять
# («Постановления № 53», «ППВС № 53», «Пленума ВС РФ от 21.12.2017 № 53»).
DOC_WORD = r'(?:постановлени\w*|пленум\w*|ппвас|ппвс|обзор\w*|информационн\w*\s+письм\w*|информписьм\w*)'
# Слово-документ, затем в пределах 60 символов номер. Ограничитель по «.«»|»
# нужен, чтобы мостик не перепрыгивал границу предложения, цитаты или ячейки.
ACT_MENTION = re.compile(DOC_WORD + r'[^.«»|]{0,60}?№\s*(\d+)', re.I)
# Обзоры без номера опознаются по годам и предмету.
NAMED_REVIEWS = [
    (re.compile(r'обзор\w*[^.«»|]{0,50}(?:53\.1|30\.07\.2025)', re.I),
     'Обзор Президиума ВС по ст. 53.1 ГК от 30.07.2025'),
    (re.compile(r'обзор\w*[^.«»|]{0,50}(?:банкротств\w*[^.«»|]{0,20})?2024', re.I),
     'Обзор судебной практики по банкротству за 2024 год'),
]
# «п. 68», «пп. 24, 25 и 26», «пункты 1 и 2», «п. 22(2)», «абз. 2 п. 5»
PUNKT_LIST = re.compile(
    r'(?:пп?\.|пункт\w*)\s*((?:\d+(?:\(\d+\))?)(?:\s*(?:,|и|-|–)\s*\d+(?:\(\d+\))?)*)', re.I)
# «п. 6 ст. 213.28», «абзац второй пункта 5 статьи 61.14», «ст. 61.20»
ART_PUNKT = re.compile(
    r'(?:(?:пп?\.|пункт\w*)\s*(\d+(?:\.\d+)?)\s*)?(?:ст\.|стать\w*)\s*(\d+(?:\.\d+)*)', re.I)
NEAR = 90          # окно вокруг упоминания акта, где ищем номера пунктов


def act_by_number(acts):
    out = {}
    for name, punkts, kind, art in acts:
        if kind != 'акт':
            continue
        m = re.search(r'№\s*(\d+)', name)
        if m:
            out.setdefault(m.group(1), name)
    return out


def statutes_by_article(acts):
    out = {}
    for name, punkts, kind, art in acts:
        if kind == 'норма':
            out.setdefault(art, name)
    return out


def expand(seq):
    """«24, 25 и 26» → ['24','25','26']. Диапазоны не раскрываем: «п. 5-6»
    в юридическом тексте почти всегда перечисление двух, а не интервал."""
    return [p.strip() for p in re.split(r'\s*(?:,|и|-|–)\s*', seq) if p.strip()]


def used_by_prose(text, num2act, art2act):
    """{имя акта: {номера пунктов}} по ссылкам в прозе."""
    used = {}
    low = text.lower()

    def add(act, punkts):
        if not act:
            return
        used.setdefault(act, set()).update(punkts)

    # Пленумы и обзоры. Номер пункта принадлежит РОВНО ОДНОМУ акту —
    # ближайшему, между которым и пунктом не названо другого. Раздача всем
    # актам в окне ±90 символов приписывала «п. 68 Постановления № 53» ещё и
    # Пленумам № 63 и № 62, стоявшим рядом в той же строке таблицы: тот же
    # класс ошибки, что склейка адресов в verify_addresses.py.
    marks = []
    for m in ACT_MENTION.finditer(low):
        act = num2act.get(m.group(1))
        if act:
            marks.append((m.start(), m.end(), act))
    for rx, name in NAMED_REVIEWS:
        marks += [(m.start(), m.end(), name) for m in rx.finditer(low)]
    marks.sort()

    punkt_marks = [(m.start(), m.end(), m.group(1)) for m in PUNKT_LIST.finditer(low)]
    # Граница строки таблицы: «| смена участников | п. 26 того же Обзора |»
    # и следующая строка с другим актом — соседние ячейки чужие друг другу.
    row_edges = [m.start() for m in re.finditer(r'\n(?=[^\n]*\|)', low)]

    def nearest(p_start, p_end):
        best, best_d = None, NEAR + 1
        for s, e, act in marks:
            if s >= p_end:                      # акт стоит после пункта
                d, lo, hi = s - p_end, p_end, s
            elif e <= p_start:                  # акт стоит перед пунктом
                d, lo, hi = p_start - e, e, p_start
            else:
                continue                        # перекрытие — не наш случай
            if d > NEAR or d >= best_d:
                continue
            if any(lo <= s2 < hi for s2, _, _ in marks):
                continue                        # между ними назван другой акт
            # Между пунктом и актом назван другой пункт — значит, наш пункт
            # относится к чему-то ещё: «вывод из п. 68 … как в п. 32 ППВАС
            # № 63» приписывал 68 Пленуму № 63, у которого его нет вовсе.
            if any(lo <= s2 and e2 <= hi for s2, e2, _ in punkt_marks):
                continue
            if any(lo <= x < hi for x in row_edges):
                continue                        # разные строки таблицы
            best, best_d = act, d
        return best

    for p_start, p_end, seq in punkt_marks:
        act = nearest(p_start, p_end)
        if act:
            add(act, expand(seq))
    # Акт назван без единого номера пункта — фиксируем сам факт обращения,
    # но ни один пункт использованным не помечаем: иначе «см. Пленум № 53»
    # закрыл бы весь акт целиком и проверка потеряла бы смысл.
    for _, _, act in marks:
        add(act, set())

    # Нормы: статья опознаёт акт сама, пункт стоит рядом.
    for m in ART_PUNKT.finditer(low):
        punkt, art = m.group(1), m.group(2)
        act = art2act.get(art)
        if act:
            add(act, {punkt} if punkt else set())
    return used


def used_by_quotes(text, acts):
    """{имя акта: {номера пунктов}} по дословным цитатам."""
    used = {}
    for line, quote, before in V.extract_quotes(text):
        for name, pnum, actual, total, kind, art in V.locate(V.norm(quote), acts):
            used.setdefault(name, set()).add(pnum)
    return used


def merge(a, b):
    out = {k: set(v) for k, v in a.items()}
    for k, v in b.items():
        out.setdefault(k, set()).update(v)
    return out


def fold(nums):
    """[1,2,3,7] → '1-3, 7'. Иначе список на семьдесят пунктов нечитаем."""
    def key(x):
        m = re.match(r'^(\d+)', x)
        return (int(m.group(1)) if m else 0, x)
    nums = sorted(set(nums), key=key)
    runs, cur = [], []
    for n in nums:
        if n.isdigit() and cur and cur[-1].isdigit() and int(n) == int(cur[-1]) + 1:
            cur.append(n)
        else:
            if cur:
                runs.append(cur)
            cur = [n]
    if cur:
        runs.append(cur)
    return ', '.join(r[0] if len(r) == 1 else '%s-%s' % (r[0], r[-1]) for r in runs)


def report(path, acts, only=None, show_used=False):
    text = open(path, encoding='utf-8').read()
    num2act, art2act = act_by_number(acts), statutes_by_article(acts)
    used = merge(used_by_prose(text, num2act, art2act), used_by_quotes(text, acts))
    print('=' * 74)
    print('СПРАВОЧНИК: %s' % os.path.basename(path))
    print('=' * 74)
    touched = 0
    for name, punkts, kind, art in acts:
        hit = used.get(name)
        if not hit:
            continue                       # акт вообще не упоминается — не шум
        if only and only not in name:
            continue
        touched += 1
        total = set(punkts)
        real = {p for p in hit if p in total}
        missing = total - real
        pct = 100 * len(real) // len(total) if total else 0
        print('\n%s — пунктов %d, задействовано %d (%d%%)'
              % (name, len(total), len(real), pct))
        if show_used and real:
            print('   исп.: %s' % fold(real))
        if missing:
            print('   НЕ задействовано: %s' % fold(missing))
        else:
            print('   задействован целиком')
        ghost = {p for p in hit if p not in total}
        if ghost:
            # Названный пункт, которого в акте нет. Либо опечатка в номере,
            # либо ссылка на другую редакцию — и то и другое стоит увидеть.
            print('   ⚠ названы пункты, которых в акте НЕТ: %s' % fold(ghost))
    if not touched:
        print('\nНи один акт корпуса в справочнике не опознан.')
    return touched


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    only = None
    if '--act' in sys.argv:
        only = '№ ' + sys.argv[sys.argv.index('--act') + 1]
    if not args:
        print(__doc__)
        return 2
    acts = V.load_acts()
    print('актов и норм в корпусе: %d' % len(acts))
    for p in args:
        if os.path.exists(p):
            report(p, acts, only, '--used' in sys.argv)
    return 0


if __name__ == '__main__':
    sys.exit(main())
