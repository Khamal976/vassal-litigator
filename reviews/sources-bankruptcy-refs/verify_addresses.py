# -*- coding: utf-8 -*-
"""Машинная проверка АДРЕСА цитаты: тот ли пункт и тот ли абзац названы.

`verify_quotes.py` отвечает на вопрос «цитата дословна?». Он по построению
не ловит класс «цитата дословна, но приписана не тому месту» — а именно этот
класс дал десять неверных адресов абзацев в шести пунктах Постановления № 63,
причём дважды по названному адресу стояло правило противоположного смысла.

Логика обратная обычной: не «найти абзац по адресу», а «найти цитату в корпусе,
вычислить её настоящий адрес и сверить с тем, что написано рядом». Поэтому
работают и безномерные формы («Абзац второй: «...»») — пункт берётся из самой
цитаты, а не из контекста.

Счёт абзацев ведётся по действующей редакции; редакционные пометы
(«(в ред. …)», «(абзац введен …)», «(см. текст в предыдущей редакции)»)
абзацами не считаются — так же, как их не считает КонсультантПлюс.

Запуск:  python verify_addresses.py <файл-справочника> [ещё файлы]
         python verify_addresses.py --structure          # карта абзацев корпуса
"""
import sys, os, re, glob, unicodedata

REF = os.path.dirname(os.path.abspath(__file__))

# Акты, у которых есть пункты и абзацы. Ключ — как их зовут в справочнике.
ACTS = [
    ('Постановление Пленума ВАС № 63', os.path.join(REF, 'sources0', 'ppvas63-full-current.txt'),
     (r'постановлени\w*\s+(?:пленума\s+)?вас\D{0,30}63', r'№\s*63', r'\bn\s*63\b')),
    ('Постановление Пленума ВС № 53', os.path.join(REF, 'texts', 'ppvs53.txt'),
     (r'постановлени\w*\s+(?:пленума\s+)?вс\D{0,30}53', r'№\s*53')),
    ('Постановление Пленума ВАС № 62', os.path.join(REF, 'sources0', 'ppvas62-2013.txt'),
     (r'постановлени\w*\s+(?:пленума\s+)?вас\D{0,30}62', r'№\s*62')),
    ('Обзор Президиума ВС по ст. 53.1 ГК от 30.07.2025',
     os.path.join(REF, 'sources0', 'obzor-53.1-2025.txt'),
     (r'обзор\w*\D{0,40}53\.1', r'30\.07\.2025')),
    ('Постановление Пленума ВС № 25', os.path.join(REF, 'sources0', 'ppvs25-full.txt'),
     (r'постановлени\w*\s+(?:пленума\s+)?вс\D{0,30}25', r'№\s*25')),
    ('Постановление Пленума ВС № 7', os.path.join(REF, 'sources0', 'ppvs7-2016.txt'),
     (r'постановлени\w*\s+(?:пленума\s+)?вс\D{0,30}7\b', r'№\s*7\b')),
]

# Хвост файла источника с примечаниями редакции КонсультантПлюс — не текст акта.
# Без этой отсечки примечания приклеиваются абзацами к последнему пункту и
# сдвигают его нумерацию, а цитата из примечания «находится» в самом акте.
#
# Искать маркер надо ТОЛЬКО с начала строки: блок ПРОВЕНАНС сам называет его
# («…вынесены в конец файла под заголовок «ВРЕЗКИ КонсультантПлюс»»), и поиск
# подстрокой обрезал файл на девятой строке — акт целиком выпадал из корпуса
# молча, как пустой. Так потерялись Пленум ВАС № 62 и Пленум ВС № 25.
NOTES_MARKER = re.compile(r'(?m)^ВРЕЗКИ КонсультантПлюс')


def cut_notes(text):
    hits = list(NOTES_MARKER.finditer(text))
    return text[:hits[-1].start()] if hits else text

ORD = ['первый', 'второй', 'третий', 'четвертый', 'пятый', 'шестой', 'седьмой',
       'восьмой', 'девятый', 'десятый', 'одиннадцатый', 'двенадцатый',
       'тринадцатый', 'четырнадцатый', 'пятнадцатый', 'шестнадцатый',
       'семнадцатый', 'восемнадцатый', 'девятнадцатый', 'двадцатый']
ORD_ANY = '|'.join(ORD) + r'|последний|предпоследний|\d+'
# «абзац четвёртый», «абзацы пятый и седьмой», «абзаце втором»
# Разделитель «и» — только как отдельное слово: внутри «третий» и «предпоследний»
# та же буква, и склейка \s* превращала одно слово в два обломка.
SEP = r'(?:\s*,\s*|\s+и\s+|\s*[-–]\s*)'
ADDR_RE = re.compile(
    r'абзац\w*\s+((?:%s)(?:%s(?:%s))*)' % (ORD_ANY, SEP, ORD_ANY))
# «п. 2» пункта Пленума, но не «п. 2 ст. 61.2» — там это пункт статьи закона,
# и не «п. 7 Обзора» — там это пункт другого акта.
PUNKT_RE = re.compile(
    r'(?:^|[^\w])(?:п\.|пункт\w*)\s*(\d+(?:\.\d+)?)'
    r'(?!\s*(?:ст\.|стать|\d)|\s+\S*\s*(?:обзор|закон|апк|гк|нк))')
SERVICE_RE = re.compile(r'^\(\s*(?:абзац\w*|подпункт\w*|пункт\w*|п\.|в\s+ред\.|см\.|дополнен|исключен|утратил)')
MIN_LEN = 40
LOOKBEHIND = 320      # сколько символов перед цитатой вообще смотреть
ADDR_WINDOW = 140     # адрес абзаца стоит вплотную к цитате
PUNKT_WINDOW = 60     # «П. 5, абзац седьмой: «…»» — номер пункта ещё ближе


def norm(s):
    s = unicodedata.normalize('NFKC', s)
    s = s.replace('ё', 'е').replace('Ё', 'Е')
    s = re.sub(r'[«»""„“”]', '"', s)
    s = re.sub(r'[‐-―−-]', '-', s)
    s = re.sub(r'\s+', ' ', s)
    return s.strip().lower()


def parse_act(path):
    """Файл акта → {номер пункта: [абзац1, абзац2, ...]} в нормализованном виде."""
    punkts, cur = {}, None
    text = cut_notes(open(path, encoding='utf-8').read())
    for raw in text.split('\n'):
        line = raw.strip()
        if not line or SERVICE_RE.match(line):
            continue
        # Пункты бывают дробными двух видов: «12.1.» у актов ВАС и «69(1).»
        # у пунктов, введённых Пленумом ВС № 42 от 23.12.2025. Без второй формы
        # такой пункт читается как продолжение предыдущего, и нумерация абзацев
        # обоих сдвигается: у п. 69 их становилось 5 вместо 2.
        m = re.match(r'^(\d+(?:\.\d+)?(?:\(\d+\))?)\.\s+(.*)$', line)
        if m:
            cur = m.group(1)
            punkts[cur] = [norm(m.group(2))]
            continue
        if cur is None:
            continue
        # заголовок раздела: короткая строка без завершающего знака
        if len(line) < 100 and not re.search(r'[.:;»"]$', line):
            continue
        punkts[cur].append(norm(line))
    return punkts


def load_acts():
    out = []
    for name, path, patterns in ACTS:
        if os.path.exists(path):
            out.append((name, parse_act(path), [re.compile(p) for p in patterns]))
    return out


def locate(quote, acts):
    """Где эта цитата на самом деле: [(акт, пункт, номер абзаца, всего абзацев)]."""
    hits = []
    head = quote[:60] if len(quote) > 60 else quote
    for name, punkts, _ in acts:
        for pnum, paras in punkts.items():
            for i, para in enumerate(paras, 1):
                if head in para:
                    hits.append((name, pnum, i, len(paras)))
    return hits


def ordinal_to_int(word, total):
    word = word.strip()
    if word == 'последний':
        return total
    if word == 'предпоследний':
        return total - 1
    if word.isdigit():
        return int(word)
    return ORD.index(word) + 1 if word in ORD else None


def extract_quotes(text):
    out = []
    for m in re.finditer(r'«([^«»]{%d,})»' % MIN_LEN, text, re.S):
        q = re.sub(r'(?m)^\s*>\s?', ' ', m.group(1)).replace('//', ' ')
        q = re.sub(r'^\s*(?:\.{2,}|…)\s*', ' ', q).strip()
        if len(q) < MIN_LEN:
            continue
        line = text.count('\n', 0, m.start()) + 1
        # Подводка — только авторский текст. Адрес внутри соседней цитаты
        # («…абзац седьмой пункта 4 статьи 83 Закона…») принадлежит источнику,
        # а не автору, и адресом проверяемой цитаты не является.
        before = text[max(0, m.start() - LOOKBEHIND):m.start()]
        before = re.sub(r'^[^«»]*»', ' ', before)      # хвост цитаты, начатой до окна
        before = re.sub(r'«[^«»]*»', ' ', before)      # цитаты целиком
        # В таблице подводка стоит в шапке и относится к столбцу, а не к ячейке:
        # адрес из шапки чужой. Заголовок раздела тоже обрывает подводку.
        # Соседняя строка таблицы — чужая целиком: адрес «абзац третий п. 47»
        # в столбце статуса одного акта прочитывался как адрес цитаты из
        # следующей строки, где речь о другом акте. Граница строки — перевод
        # строки перед строкой, в которой есть вертикальная черта.
        for edge in (r'\|\s*-{2,}', r'(?m)^#{2,}\s', r'\n(?=[^\n]*\|)'):
            cut = list(re.finditer(edge, before))
            if cut:
                before = before[cut[-1].end():]
        out.append((line, q, before))
    return out


def check(path, acts, with_punkt=False):
    text = open(path, encoding='utf-8').read()
    problems = checked = 0
    print('=' * 72)
    print('ФАЙЛ: %s' % os.path.basename(path))
    print('=' * 72)
    for line, quote, before in extract_quotes(text):
        hits = locate(norm(quote), acts)
        if len(hits) != 1:
            continue                      # не из этих актов либо неоднозначно
        act, pnum, actual, total = hits[0]
        nbefore = norm(before)
        addr = None
        for m in ADDR_RE.finditer(nbefore):
            if len(nbefore) - m.end() > ADDR_WINDOW:
                continue
            # «п. 4 ст. 61.8, абзац первый» — адрес внутри статьи закона,
            # а не внутри пункта Пленума: у норм своя нумерация абзацев.
            if re.search(r'(?:ст\.|стать)\w*\s*[\d.]+[^.]{0,40}$', nbefore[:m.start()]):
                continue
            # Между адресом и цитатой назван другой источник — значит, адрес
            # относится к предыдущей цитате в том же предложении, а не к этой.
            if re.search(r'(?:ст\.|стать)\w*\s*\d', nbefore[m.end():]):
                continue
            addr = m                      # ближайший к цитате адрес
        pm = None
        for m in PUNKT_RE.finditer(nbefore):
            if len(nbefore) - m.end() <= PUNKT_WINDOW:
                pm = m
        if addr is None and pm is None:
            continue
        checked += 1
        # Ось «пункт» шумная: в прозе номер пункта рядом с цитатой чаще
        # относится к соседнему тезису, чем к самой цитате. По умолчанию
        # выключена — включается флагом --punkt для ручного разбора.
        if with_punkt and pm and pm.group(1) != pnum:
            if addr is None or pm.start() > addr.start():
                print('\n[стр. %d] ⚠ ПУНКТ: рядом названо п. %s, цитата стоит в п. %s (%s)'
                      % (line, pm.group(1), pnum, act))
                print('   «%s…»' % quote[:110].replace('\n', ' '))
                problems += 1
                continue
        if addr is None:
            continue
        words = re.split(SEP, addr.group(1))
        nums = [ordinal_to_int(w, total) for w in words]
        if actual in [n for n in nums if n]:
            continue
        print('\n[стр. %d] ❌ АБЗАЦ: названо «абзац %s» п. %s, цитата стоит в абзаце %d из %d (%s)'
              % (line, addr.group(1), pnum, actual, total, act))
        print('   «%s…»' % quote[:110].replace('\n', ' '))
        problems += 1
    print('\nИТОГ: адресов проверено %d, расхождений %d' % (checked, problems))
    return problems


def structure(acts):
    for name, punkts, _ in acts:
        print('\n%s — пунктов %d' % (name, len(punkts)))
        for pnum, paras in punkts.items():
            print('  п. %-5s абзацев %2d | абз. 1: %s…' % (pnum, len(paras), paras[0][:70]))


def main():
    acts = load_acts()
    if not acts:
        print('корпус не найден')
        return 2
    if len(sys.argv) > 1 and sys.argv[1] == '--structure':
        structure(acts)
        return 0
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    with_punkt = '--punkt' in sys.argv
    if not args:
        print(__doc__)
        return 2
    print('актов в корпусе: %d' % len(acts))
    total = sum(check(p, acts, with_punkt) for p in args if os.path.exists(p))
    print('\n%s\nВСЕГО РАСХОЖДЕНИЙ АДРЕСА: %d' % ('=' * 72, total))
    return 1 if total else 0


if __name__ == '__main__':
    sys.exit(main())
