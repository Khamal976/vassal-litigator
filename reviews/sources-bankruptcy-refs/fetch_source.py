# -*- coding: utf-8 -*-
"""Добор первоисточника с КонсультантПлюс прямым HTTP + локальным парсингом.

Зачем не WebFetch: WebFetch искажает дословные цитаты и один раз выдумал
структуру нормы (см. reference_practice_verification_tools). Здесь текст
берётся из HTML как есть, посимвольно, без участия модели.

Формат выхода подчинён двум потребителям:
  * verify_quotes.py    — ищет цитату посимвольно в тексте;
  * verify_addresses.py — считает пункты по шаблону '^N. ' и абзацы по строкам,
    поэтому ОДИН АБЗАЦ = ОДНА СТРОКА, между абзацами пустая строка.

Дисциплина: скрипт НИЧЕГО не выбрасывает молча. Всё, что удалено из тела
документа (рекламные врезки КонсультантПлюс, кнопки, баннеры), печатается
в отчёт — чтобы удаление попало в блок ПРОВЕНАНС осознанно.

Запуск:
    python fetch_source.py <URL> <выходной-файл.txt> --reason "почему добрано"
    python fetch_source.py <URL> --probe        # только посмотреть, не писать
"""
import sys, os, re, ssl, html, time, datetime, urllib.request, urllib.parse, argparse
from html.parser import HTMLParser

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
TIMEOUT = 30

# Контейнер тела документа на consultant.ru.
# Матч ТОЧНЫЙ по токену класса: подстрочный матч ловил 'full-text__wrapper'
# (кнопка «Открыть полный текст документа») и вносил её текст в тело акта.
BODY_CLASSES = ("document-page__content", "full-text")

# Врезки страницы. Ключ — токен класса, значение — как поступить:
#   'furniture' — реклама и навигация КонсультантПлюс, в файл не попадает;
#   'note'      — примечание редакции, уходит в хвост (по нему датируются редакции).
# Всё, что выброшено НЕ по этим классам, считается текстом документа
# (обычно шапка акта) и возвращается в тело. Разводить по тексту нельзя:
# и шапка акта, и врезка «Перспективы и риски» одинаково не помечены.
DROP_CLASSES = {
    "document__insert": "furniture", "doc-insert": "furniture",
    "doc-roll": "furniture", "document__roll": "furniture",
    # 'document__format' НЕ выбрасывается: вопреки названию в нём лежит шапка
    # акта («ПЛЕНУМ … ПОСТАНОВЛЕНИЕ от … N … О НЕКОТОРЫХ ВОПРОСАХ …»),
    # а не виджет выгрузки. В корпусе шапка есть — ppvas63-full-current.txt.
    "full-text__wrapper": "furniture", "full-text__button": "furniture",
    "document-page__notes": "furniture", "notes": "furniture",
    "bn": "furniture", "banner": "furniture", "seo-links": "furniture",
    "document-page__separator": "furniture", "pages": "furniture",
    "external-block": "furniture", "cookies": "furniture",
}
# Примечание редакции опознаётся по собственному зачину, а не по контейнеру:
# КонсультантПлюс кладёт его в тот же doc-insert, что и рекламу.
NOTE_PREFIX = "КонсультантПлюс"
BLOCK_TAGS = {"p", "div", "li", "tr", "h1", "h2", "h3", "h4", "blockquote", "br"}


class DocExtractor(HTMLParser):
    """Собирает текст тела документа; врезки складывает отдельно, не теряя их."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.depth = 0                 # глубина тегов внутри тела
        self.in_body = False
        self.body_depth = None
        self.skip_depth = None         # глубина, на которой начался выброшенный блок
        self.skip_class = None         # класс, велевший выбросить
        self.parts = []                # куски тела
        self.dropped = []              # [(класс, текст)] — что выброшено и почему
        self._drop_buf = []
        self._silent = 0               # script/style

    # --- служебное -------------------------------------------------------
    @staticmethod
    def _classes(attrs):
        d = dict(attrs)
        return d.get("class", "").split()

    @staticmethod
    def _drop_kind(tokens):
        """Какой класс велел выбросить блок и с каким намерением."""
        for t in tokens:
            if t in DROP_CLASSES:
                return t, DROP_CLASSES[t]
        return None, None

    def _emit(self, text):
        if self.skip_depth is not None:
            self._drop_buf.append(text)
        else:
            self.parts.append(text)

    # --- обработчики -----------------------------------------------------
    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._silent += 1
            return
        toks = self._classes(attrs)

        if not self.in_body:
            if any(c in toks for c in BODY_CLASSES):
                self.in_body = True
                self.body_depth = self.depth
            self.depth += 1
            return

        # уже внутри тела
        if self.skip_depth is None:
            cls, kind = self._drop_kind(toks)
            if kind:
                self.skip_depth = self.depth
                self.skip_class = cls
                self._drop_buf = []
        if tag in BLOCK_TAGS:
            self._emit("\n")
        self.depth += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self._silent = max(0, self._silent - 1)
            return
        self.depth -= 1
        if self.in_body:
            if self.skip_depth is not None and self.depth <= self.skip_depth:
                txt = re.sub(r"\s+", " ", "".join(self._drop_buf)).strip()
                if txt:
                    self.dropped.append((self.skip_class, txt))
                self.skip_depth = None
                self.skip_class = None
                self._drop_buf = []
            elif self.body_depth is not None and self.depth < self.body_depth:
                self.in_body = False
            if tag in BLOCK_TAGS:
                self._emit("\n")

    def handle_data(self, data):
        if self._silent or not self.in_body:
            return
        self._emit(data)


def clean(raw_text):
    """Один абзац = одна строка, пустая строка между абзацами."""
    text = html.unescape(raw_text)
    text = text.replace(" ", " ").replace("​", "")
    lines = []
    for chunk in text.split("\n"):
        s = re.sub(r"[ \t]+", " ", chunk).strip()
        if s:
            lines.append(s)
    # склейка мусорных однобуквенных остатков не делается: лучше видеть как есть
    return "\n\n".join(lines)


def fetch(url, attempts=8):
    """Забрать страницу. TLS у consultant.ru рвётся с перебоями.

    Наблюдался ssl.SSLError [DECRYPTION_FAILED_OR_BAD_RECORD_MAC] на случайных
    запросах при исправном канале. Без ретрая часть источников недобиралась бы
    молча — на три десятка запросов это гарантированный пропуск.
    """
    last = None
    for n in range(attempts):
        try:
            return _fetch_once(url)
        except Exception as e:                     # noqa: BLE001 — важно любое
            last = e
            if n + 1 < attempts:
                # Отказы идут очередями (похоже на ограничение частоты, а не на
                # разрыв канала): короткая выдержка их не перебивает.
                time.sleep(min(30, 3 * 2 ** n))
    raise last


def _fetch_once(url):
    ctx = ssl.create_default_context()
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=TIMEOUT, context=ctx) as r:
        raw = r.read()
        ctype = r.headers.get("Content-Type", "")
    enc = "utf-8"
    m = re.search(r"charset=([\w-]+)", ctype, re.I)
    if m:
        enc = m.group(1)
    # Гарант отдаёт windows-1251; декодирование как utf-8 молча рушит текст
    try:
        return raw.decode(enc)
    except UnicodeDecodeError:
        return raw.decode("windows-1251", "replace")


LANDING_RE = re.compile(r"^https://www\.consultant\.ru/document/(cons_doc_LAW_\d+)/?$")


def section_links(html_src, law_id):
    """Разделы, на которые КонсультантПлюс разбил длинный акт.

    Титульная страница разбитого документа содержит ТОЛЬКО оглавление: у
    Постановления Пленума ВАС № 35 это 796 знаков вместо всего текста. Без
    прохода по разделам в корпус молча ложится огрызок под видом акта.
    Порядок ссылок на странице = порядок разделов в документе.
    """
    hrefs = re.findall(r'href="(/document/%s/[0-9a-f]{20,}/)"' % re.escape(law_id), html_src)
    return ["https://www.consultant.ru" + h for h in dict.fromkeys(hrefs)]


def extract(html_src):
    ex = DocExtractor()
    ex.feed(html_src)
    return clean("".join(ex.parts)), ex.dropped


def pagination_links(html_src, base_url):
    """Ссылки постраничной разбивки документа, если КонсультантПлюс её сделал."""
    m = re.search(r'<div[^>]*class="[^"]*\bpages\b[^"]*"(.*?)</div>', html_src, re.S)
    if not m:
        return []
    out = []
    for href in re.findall(r'href="([^"]+)"', m.group(1)):
        full = urllib.parse.urljoin(base_url, href) if "://" not in href else href
        if full not in out:
            out.append(full)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("out", nargs="?")
    ap.add_argument("--reason", default="")
    ap.add_argument("--title", default="")
    ap.add_argument("--probe", action="store_true")
    # Дата добора берётся у системы. Прежде здесь стояла константа дня, когда
    # скрипт писался: каждый следующий добор молча помечался задним числом,
    # а ПРОВЕНАНС — единственное, чем файл корпуса отличается от текста ниоткуда.
    ap.add_argument("--date", default=datetime.date.today().isoformat())
    a = ap.parse_args()

    src = fetch(a.url)
    ex = DocExtractor()
    ex.feed(src)
    body = clean("".join(ex.parts))

    # Длинный акт разбит на разделы: титульная страница держит одно оглавление.
    # Ссылки на разделы есть только у титульной страницы; у страницы раздела
    # такие же ссылки ведут на соседние статьи, и идти по ним нельзя.
    sections = []
    m = LANDING_RE.match(a.url.strip())
    if m:
        sections = section_links(src, m.group(1))
    if sections:
        print("документ разбит на разделы: %d — собираю целиком" % len(sections))
        pieces = []
        for i, s in enumerate(sections, 1):
            if i > 1:
                time.sleep(1.5)          # не частить: сервер отвечает отказами
            sub_body, sub_dropped = extract(fetch(s))
            if sub_body.strip():
                pieces.append(sub_body)
            ex.dropped.extend(sub_dropped)
            print("   раздел %d/%d: %d знаков" % (i, len(sections), len(sub_body)))
        if pieces:
            # Титульную страницу выбрасывать НЕЛЬЗЯ: у Постановления Пленума ВС
            # № 25 она несёт сам текст пунктов 1-16 (включая п. 12 об убытках),
            # а у Постановления Пленума ВАС № 35 — только оглавление. Отличать
            # по размеру ненадёжно, поэтому титульная идёт первой, а её абзацы,
            # повторившиеся в разделах (оглавление), снимаются как дубли.
            sec_text = "\n\n".join(pieces)
            sec_set = {p.strip() for p in sec_text.split("\n\n") if p.strip()}
            head_paras = [p for p in body.split("\n\n")
                          if p.strip() and p.strip() not in sec_set]
            dropped_dupes = len([p for p in body.split("\n\n") if p.strip()]) - len(head_paras)
            print("   титульная: своих абзацев %d, дублей с разделами снято %d"
                  % (len(head_paras), dropped_dupes))
            body = ("\n\n".join(head_paras) + "\n\n" + sec_text) if head_paras else sec_text

    # Три судьбы выброшенного блока, различаемые по классу-источнику:
    #   примечание редакции  -> хвост файла (по нему датируются пункты);
    #   реклама/навигация    -> не попадает в файл вовсе;
    #   выброшено не по классу врезки -> это текст документа (шапка акта),
    #                                    возвращается в тело.
    notes, furniture, reclaimed = [], [], []
    for cls, txt in ex.dropped:
        if txt.lstrip().startswith(NOTE_PREFIX):
            notes.append(txt)
        elif cls is not None:
            furniture.append((cls, txt))
        else:
            reclaimed.append(txt)
    if reclaimed:
        body = "\n\n".join(reclaimed) + "\n\n" + body
    ex.dropped = notes

    pages = pagination_links(src, a.url)

    report = {
        "url": a.url,
        "chars": len(body),
        "paragraphs": len([l for l in body.split("\n\n") if l]),
        "konsultant_notes": len(ex.dropped),
        "furniture_removed": len(furniture),
        "reclaimed_to_body": len(reclaimed),
        "sibling_links": len(pages),
    }
    for k, v in report.items():
        print("%-18s %s" % (k, v))
    if ex.dropped:
        print("--- ПРИМЕЧАНИЯ КонсультантПлюс (в хвост файла, не текст акта) ---")
        for d in ex.dropped[:25]:
            print("  [%d] %s" % (len(d), d[:160]))
    if furniture:
        print("--- УДАЛЕНО КАК РЕКЛАМА/НАВИГАЦИЯ (проверить, что не текст нормы) ---")
        for cls, d in furniture[:25]:
            print("  [%s][%d] %s" % (cls, len(d), d[:140]))
    if reclaimed:
        print("--- ВОЗВРАЩЕНО В ТЕЛО (шапка акта и т.п.) ---")
        for d in reclaimed[:10]:
            print("  [%d] %s" % (len(d), d[:140]))

    if a.probe or not a.out:
        return

    head = []
    if a.title:
        head.append(a.title)
    head.append("")
    head.append("ПРОВЕНАНС")
    head.append("Источник: КонсультантПлюс, страница документа")
    head.append(a.url)
    head.append("Получено: %s, прямой HTTP + локальный парсинг (fetch_source.py)." % a.date)
    if a.reason:
        head.append("Причина добора: " + a.reason)
    if ex.dropped:
        head.append("Примечания редакции (%d шт.) вынесены в конец файла под заголовок"
                    % len(ex.dropped))
        head.append("«ВРЕЗКИ КонсультантПлюс» — они НЕ текст акта, но по ним датируются редакции.")
    if furniture:
        head.append("Удалены рекламные и навигационные врезки страницы (%d шт.): %s."
                    % (len(furniture), ", ".join(sorted({c for c, _ in furniture}))))
    head.append("-" * 70)
    head.append("")

    tail = ""
    if ex.dropped:
        tail = ("\n\n" + "=" * 70 +
                "\nВРЕЗКИ КонсультантПлюс — НЕ ТЕКСТ АКТА, цитировать как акт нельзя.\n" +
                "=" * 70 + "\n\n" +
                "\n\n".join(ex.dropped) + "\n")

    with open(a.out, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(head) + body + tail)
    print("written ->", a.out)


if __name__ == "__main__":
    main()
