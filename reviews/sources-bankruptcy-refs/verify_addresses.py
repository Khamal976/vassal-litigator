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

# Акты, у которых есть пункты и абзацы: (как зовём в отчёте, файл корпуса).
#
# Раньше у каждой записи стоял третий элемент — кортеж регулярок на имя акта.
# Он компилировался в load_acts() и НИКЕМ не читался: locate() ищет цитату по
# тексту и опознаёт акт по факту нахождения, имя из справочника ему не нужно.
# Поле было мёртвым, но выглядело обязательным — и завод нового акта казался
# работой «сочини регулярку» вместо строчки с путём. Список из-за этого стоял
# на шести актах, пока справочники ссылались на полтора десятка.
#
# Заводить сюда МОЖНО только полный текст действующей редакции. Выдержка
# (`ppvas35-p7.txt`, `ppvs25-p88.txt`) и прежняя редакция (`ppvas63-izm.txt`,
# `ppvas63-prev-p1.txt`) рядом с полным текстом дают два попадания на одну
# цитату, а locate() при len(hits) != 1 молча пропускает адрес — проверка
# теряет покрытие, не сказав об этом. Дубли ловит sanity_acts() ниже.
ACTS = [
    ('Постановление Пленума ВАС № 63', os.path.join(REF, 'sources0', 'ppvas63-full-current.txt')),
    ('Постановление Пленума ВС № 53', os.path.join(REF, 'texts', 'ppvs53.txt')),
    ('Постановление Пленума ВАС № 62', os.path.join(REF, 'sources0', 'ppvas62-2013.txt')),
    ('Обзор Президиума ВС по ст. 53.1 ГК от 30.07.2025',
     os.path.join(REF, 'sources0', 'obzor-53.1-2025.txt')),
    ('Постановление Пленума ВС № 25', os.path.join(REF, 'sources0', 'ppvs25-full.txt')),
    ('Постановление Пленума ВС № 7', os.path.join(REF, 'sources0', 'ppvs7-2016.txt')),
    # Заведены 2026-08-02 (H.4): на них опирается материал v0.35.0 в
    # `legal-review/references/` — п. 53 ППВАС № 35, п. 48 ППВАС № 29,
    # п. 3 ППВС № 43, — и до этого захода у них было нулевое покрытие.
    ('Постановление Пленума ВАС № 35', os.path.join(REF, 'sources0', 'ppvas35-full.txt')),
    ('Постановление Пленума ВАС № 29', os.path.join(REF, 'sources0', 'ppvas29-2004.txt')),
    ('Постановление Пленума ВАС № 32', os.path.join(REF, 'sources0', 'ppvas32-2009.txt')),
    ('Постановление Пленума ВАС № 97', os.path.join(REF, 'sources0', 'ppvas97-2013.txt')),
    ('Постановление Пленума ВС № 43', os.path.join(REF, 'sources0', 'ppvs43-2015.txt')),
    ('Постановление Пленума ВС № 40', os.path.join(REF, 'sources0', 'ppvs40-2024.txt')),
    ('Постановление Пленума ВС № 48', os.path.join(REF, 'sources0', 'ppvs48-2018.txt')),
    ('Информационное письмо Президиума ВАС № 150',
     os.path.join(REF, 'sources0', 'ipvas150-2012.txt')),
    ('Обзор судебной практики по банкротству за 2024 год',
     os.path.join(REF, 'sources0', 'obzor-bankrotstvo-2024.txt')),
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
# Статья, названная ВПЛОТНУЮ к адресу абзаца, — с той или другой стороны:
#   «абзац четвёртый пункта 6 статьи 213.28»  — статья после адреса;
#   «п. 6 ст. 213.28, абзац четвёртый»        — статья перед адресом.
# Вплотную — существенно. У нормы номер абзаца сам по себе ничей: рядом почти
# всегда стоит ещё и ссылка на разъяснение со своей нумерацией абзацев.
STAT_AFTER = re.compile(
    r'^[\s,]*(?:(?:пункт\w*|п\.)\s*\d+(?:\.\d+)?[\s,]*)?(?:стать\w*|ст\.)\s*(\d+(?:\.\d+)*)')
STAT_BEFORE = re.compile(r'(?:стать\w*|ст\.)\s*(\d+(?:\.\d+)*)[^.]{0,20}$')
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


def parse_punkts(lines):
    """Строки → {номер пункта: [абзац1, абзац2, ...]} в нормализованном виде."""
    punkts, cur = {}, None
    for raw in lines:
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


def parse_act(path):
    return parse_punkts(cut_notes(open(path, encoding='utf-8').read()).split('\n'))


# Заголовок статьи в файле нормы. Идёт с начала строки, но перед словом
# «Статья» бывает короткий префикс кодекса («НК РФ Статья 333.21.»).
ART_HEAD = re.compile(r'(?m)^[^\n]{0,20}?Статья\s+(\d+(?:\.\d+)*)\.')


def parse_statute(path):
    """Файл нормы → {номер статьи: {пункт: [абзацы]}}.

    Плоским разбором такие файлы читать нельзя. `nk-333.txt` содержит две
    статьи — 333.21 и 333.22, — и каждую дважды: сначала оглавление
    КонсультантПлюс, затем полный текст. Пункт «1» встречается там четыре
    раза, и parse_punkts() молча оставил бы в словаре последний, то есть
    сверял бы адреса пошлины по обрывку чужой статьи.
    """
    text = cut_notes(open(path, encoding='utf-8').read())
    marks = list(ART_HEAD.finditer(text))
    if not marks:
        return {}
    out = {}
    for i, m in enumerate(marks):
        art = m.group(1)
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        seg = parse_punkts(text[m.end():end].split('\n'))
        # Та же статья встречается дважды: оглавление и текст. Берём вариант
        # с наибольшим числом абзацев — оглавление всегда короче.
        weight = sum(len(v) for v in seg.values())
        if weight > sum(len(v) for v in out.get(art, {}).values()):
            out[art] = seg
    return out


# Нормы корпуса: (маска файлов, как зовём закон). Один файл — одна-две статьи.
STATUTE_GLOBS = [
    (os.path.join(REF, 'texts', 'fz127', 'st*.txt'), 'ФЗ-127'),
    (os.path.join(REF, 'sources0', 'fz127-*.txt'), 'ФЗ-127'),
    (os.path.join(REF, 'sources0', 'st*.txt'), 'ФЗ-127'),
    (os.path.join(REF, 'sources0', 'gk-*.txt'), 'ГК'),
    (os.path.join(REF, 'sources0', 'apk-*.txt'), 'АПК'),
    (os.path.join(REF, 'sources0', 'nk-*.txt'), 'НК'),
    (os.path.join(REF, 'sources0', 'fz208-*.txt'), 'ФЗ-208'),
    (os.path.join(REF, 'sources0', 'fz14-*.txt'), 'ФЗ-14'),
]
# Выдержки и прежние редакции. Рядом с полным текстом они дают второе
# попадание на ту же цитату, и адрес перестаёт сверяться вовсе.
STATUTE_SKIP = re.compile(r'(?:-izm|-prev|-p\d)')


def load_acts():
    """Акты корпуса. Отсутствие файла — не тихий пропуск, а строка в отчёте:
    молча выпавший акт делает все его адреса «непроверенными», и отчёт при
    этом выглядит так же, как если бы их не было вовсе."""
    out, missing = [], []
    for name, path in ACTS:
        if os.path.exists(path):
            out.append((name, parse_act(path), 'акт', None))
        else:
            missing.append((name, path))
    seen = set()
    for pattern, law in STATUTE_GLOBS:
        for path in sorted(glob.glob(pattern)):
            base = os.path.basename(path)
            if STATUTE_SKIP.search(base) or path in seen:
                continue
            seen.add(path)
            for art, punkts in parse_statute(path).items():
                if punkts:
                    out.append(('ст. %s %s' % (art, law), punkts, 'норма', art))
    for name, path in missing:
        print('⚠ акт не найден в корпусе, его адреса проверены НЕ БУДУТ: %s (%s)'
              % (name, os.path.relpath(path, REF)))
    return out


def locate(quote, acts):
    """Где эта цитата на самом деле:
    [(акт, пункт, номер абзаца, всего абзацев, вид, статья)]."""
    hits = []
    head = quote[:60] if len(quote) > 60 else quote
    for name, punkts, kind, art in acts:
        for pnum, paras in punkts.items():
            for i, para in enumerate(paras, 1):
                if head in para:
                    hits.append((name, pnum, i, len(paras), kind, art))
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
    # Разбор непроверенного. Прежде всё непроверенное молча сливалось в
    # `continue`, и файл без единого сверенного адреса печатал ту же строку
    # «расхождений 0», что и файл, где сверено сто. Отчёт читался как «чисто»,
    # хотя означал «нечем было проверить»; на этом я и ошибся 2026-08-02,
    # объявив чистыми справочники `legal-review` с нулевым покрытием.
    outside = ambiguous = no_addr = other_art = 0
    ambiguous_ex = []
    print('=' * 72)
    print('ФАЙЛ: %s' % os.path.basename(path))
    print('=' * 72)
    for line, quote, before in extract_quotes(text):
        hits = locate(norm(quote), acts)
        if not hits:
            outside += 1                  # цитата не из актов корпуса
            continue
        nbefore = norm(before)
        # Цитату из нормы почти всегда находит ещё и Пленум, приводящий её
        # дословно. Разводит их сам автор: рядом с цитатой из нормы он пишет
        # «ст. N», рядом с цитатой из разъяснения — «п. N».
        names_article = re.search(r'(?:ст\.|стать)\w*\s*\d', nbefore) is not None
        if len(hits) > 1:
            narrowed = [h for h in hits if (h[4] == 'норма') == names_article]
            if len(narrowed) == 1:
                hits = narrowed
        if len(hits) > 1:
            # Что осталось — двух родов, и лечится по-разному:
            #   • попадания в РАЗНЫХ актах — либо дубль файлов в корпусе
            #     (полный текст + выдержка, действующая + прежняя редакция),
            #     либо оборот, дословно повторённый несколькими Пленумами;
            #   • попадания в ОДНОМ акте — первых 60 символов цитаты не хватает,
            #     чтобы отличить её пункт от соседнего.
            # Раньше и то и другое молча уходило в `continue`.
            ambiguous += 1
            if len(ambiguous_ex) < 3:
                ambiguous_ex.append((line, hits))
            continue
        act, pnum, actual, total, kind, art = hits[0]
        addr = near = None
        for m in ADDR_RE.finditer(nbefore):
            if len(nbefore) - m.end() > ADDR_WINDOW:
                continue
            near = m
            if kind == 'норма':
                # Адрес засчитывается, только если ровно рядом с ним названа
                # ТА САМАЯ статья, где цитата и нашлась. Иначе это адрес
                # соседней ссылки: в `bankruptcy-transaction-challenge.md`
                # перед цитатой из п. 5 ст. 61.8 стояло «п. 16, абзац третий,
                # Постановления № 63», и без этой проверки абзац Пленума
                # сверялся с абзацами нормы.
                after = STAT_AFTER.match(nbefore[m.end():])
                before_st = STAT_BEFORE.search(nbefore[:m.start()])
                if not ((after and after.group(1) == art)
                        or (before_st and before_st.group(1) == art)):
                    continue
            else:
                # «п. 4 ст. 61.8, абзац первый» — адрес внутри статьи закона,
                # а не внутри пункта Пленума: у норм своя нумерация абзацев.
                if re.search(r'(?:ст\.|стать)\w*\s*[\d.]+[^.]{0,40}$', nbefore[:m.start()]):
                    continue
                # Между адресом и цитатой назван другой источник — значит, адрес
                # относится к предыдущей цитате в том же предложении, а не к этой.
                if re.search(r'(?:ст\.|стать)\w*\s*\d', nbefore[m.end():]):
                    continue
            addr = m                      # ближайший к цитате адрес
        if kind == 'норма' and addr is None and near is not None:
            other_art += 1                # адрес рядом есть, но он не про эту статью
        pm = None
        for m in PUNKT_RE.finditer(nbefore):
            if len(nbefore) - m.end() <= PUNKT_WINDOW:
                pm = m
        if addr is None and pm is None:
            no_addr += 1                  # цитата в корпусе, но адрес не назван
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
    for line, hits in ambiguous_ex:
        names = sorted(set(h[0] for h in hits))
        if len(names) == 1:
            where = ', '.join('п. %s абз. %d' % (h[1], h[2]) for h in hits[:6])
            print('\n[стр. %d] ⚠ НЕОДНОЗНАЧНО: %d совпадения внутри одного акта (%s): %s.'
                  % (line, len(hits), names[0], where))
            print('   Адрес не сверен: оборот не уникален, 60 символов не различают пункты.')
        else:
            print('\n[стр. %d] ⚠ НЕОДНОЗНАЧНО: цитата найдена в %d актах — %s.'
                  % (line, len(names), ', '.join(names)))
            print('   Адрес не сверен. Либо дубль файлов в корпусе, либо общий оборот.')
    print('\nИТОГ: адресов сверено %d, расхождений %d' % (checked, problems))
    print('     не сверено: вне корпуса %d, неоднозначно %d, адрес не назван %d, '
          'названа другая статья %d' % (outside, ambiguous, no_addr, other_art))
    if checked == 0:
        print('     ⚠ по этому файлу проверка адресов НЕ РАБОТАЛА: сверять было нечего.')
        print('       «расхождений 0» здесь НЕ значит «адреса верны».')
    return problems


def structure(acts):
    for name, punkts, kind, art in acts:
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
