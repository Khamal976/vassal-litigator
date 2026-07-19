#!/bin/bash
# setup.sh — Установка зависимостей для vassal-litigator.
# Запускать один раз за сессию Cowork. Идемпотентный.
#
# Cowork-first (см. shared/conventions.md → «Cowork-first robustness»):
# песочница работает без root — sudo/apt заблокированы (флаг no-new-privileges).
# Поэтому НЕ используем `set -e` и НЕ полагаемся на sudo. Сначала ставим
# Python-зависимости (работают без root), затем — опционально, best-effort —
# системный OCR. Если системный OCR недоступен, основной путь — vision-OCR
# (рендер PDF→PNG + чтение моделью), см. skills/intake/SKILL.md.

echo "=== vassal-litigator: установка зависимостей ==="

# 1. Python-зависимости — ПЕРВЫМ и независимо (критично; ставятся без root).
#    extract_text.py зависит от pymupdf (import fitz).
PYDEPS="PyYAML pymupdf python-docx openpyxl"
echo "→ Python-зависимости ($PYDEPS)..."

# Ищем рабочий pip. `python3 -m pip` надёжнее голого `pip`: в песочнице `pip`
# в PATH может не быть вовсе, а прежняя версия скрипта звала именно его.
PIP=""
for cand in "python3 -m pip" "pip3" "pip"; do
    if $cand --version > /dev/null 2>&1; then PIP="$cand"; break; fi
done

if [ -z "$PIP" ]; then
    echo "✗ pip не найден (пробовал: python3 -m pip, pip3, pip) — Python-зависимости не поставить."
else
    # F.3: пишем в лог, а не в /dev/null. Боевой отказ (прокси, таймаут на
    # 25-МБ колесе pymupdf, PEP 668) раньше был невидим — пользователь видел
    # только «часть пакетов не установилась», без причины.
    PIP_LOG="${TMPDIR:-/tmp}/vassal-pip.log"
    : > "$PIP_LOG"
    # --timeout/--retries: pymupdf ~25 МБ, за прокси качается долго и срывается.
    PIP_OPTS="--timeout 60 --retries 3"
    # --break-system-packages: PEP 668 (externally-managed). На старых pip
    # флага нет — тогда вторая попытка без него.
    if ! $PIP install --break-system-packages -q $PIP_OPTS $PYDEPS >> "$PIP_LOG" 2>&1; then
        if ! $PIP install -q $PIP_OPTS $PYDEPS >> "$PIP_LOG" 2>&1; then
            echo "⚠️  Часть Python-пакетов не установилась. Причина:"
            # Сначала — строки, по которым видно, ЧТО именно случилось
            # (нет пакета / таймаут / прокси / SSL / PEP 668). Уведомления
            # pip об обновлении самого себя в диагностике только мешают.
            if grep -qiE 'ERROR|timed out|ProxyError|SSLError|externally-managed' "$PIP_LOG" 2>/dev/null; then
                grep -iE 'ERROR|timed out|ProxyError|SSLError|externally-managed|Retrying' "$PIP_LOG" \
                    | sort -u | head -n 5 | sed 's/^/    /'
            else
                tail -n 8 "$PIP_LOG" 2>/dev/null | sed 's/^/    /'
            fi
            echo "    Полный лог: $PIP_LOG"
            echo "    Если не встал pymupdf — PDF читаются через poppler (см. статус ниже)."
        fi
    fi
fi

# 2. Системный OCR (tesseract) — ОПЦИОНАЛЬНО, best-effort.
#    Без root обычно недоступно — это нормально: основной OCR-путь — vision.
if command -v tesseract &> /dev/null; then
    echo "✓ tesseract уже установлен"
else
    echo "→ Пробую tesseract (best-effort; требует root)..."
    { sudo apt-get update -qq && sudo apt-get install -y -qq tesseract-ocr tesseract-ocr-rus ; } 2>/dev/null \
        || echo "ℹ️  tesseract недоступен (нет root). OCR русских сканов — через vision (основной путь в Cowork)."
fi

# ocrmypdf — опционально (полезен только при наличии tesseract).
if ! command -v ocrmypdf &> /dev/null; then
    pip install --break-system-packages -q ocrmypdf 2>/dev/null || true
fi

# 2b. LibreOffice (soffice) — ОПЦИОНАЛЬНО, best-effort. Требует root (в Cowork обычно нет).
#     Использует build-submission: (1) офисные приложения RTF/XLSX/DOC/ODT → PDF для «Мой арбитр»;
#     (2) подсчёт листов свеже-напечатанного .docx (E.4.4/E.4.5). Недоступен — не критично:
#     копия «как есть» + флаг / листаж «уточнить вручную» (см. shared/conventions.md).
if command -v soffice &> /dev/null || command -v libreoffice &> /dev/null; then
    echo "✓ libreoffice (soffice) уже установлен"
else
    echo "→ Пробую libreoffice (best-effort; требует root)..."
    { sudo apt-get install -y -qq libreoffice-core libreoffice-writer libreoffice-calc ; } 2>/dev/null \
        || echo "ℹ️  libreoffice недоступен (нет root). build-submission: PDF-нормализация приложений и листаж .docx пропускаются с флагом — не критично."
fi

# 3. Статус.
echo ""
echo "=== Статус зависимостей ==="
check_cmd() { command -v "$1" &> /dev/null && echo "✓ $1" || echo "✗ $1 (нет; не критично при наличии vision)"; }
check_py()  { python3 -c "import $1" 2>/dev/null && echo "✓ python: $1" || echo "✗ python: $1 (НЕ установлен)"; }

check_py yaml
check_py fitz       # pymupdf — основной движок PDF в extract_text.py
check_py docx
check_py openpyxl
# poppler — запасной движок PDF (F.2): без pymupdf через него идут и извлечение
# текста (pdftotext), и рендер страниц для vision (pdftoppm).
check_cmd pdftotext
check_cmd pdftoppm
check_cmd tesseract
check_cmd ocrmypdf
check_cmd soffice

# F.5: вендоренный русский словарь. Прокидывание TESSDATA_PREFIX зашито только
# внутри `extract_text.py --spot-check`; прямой вызов tesseract его не увидит,
# поэтому печатаем готовую строку — в бою 16.07 словарь искали руками.
VASSAL_TESSDATA_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/tessdata"
if [ -s "$VASSAL_TESSDATA_DIR/rus.traineddata" ]; then
    echo "✓ rus.traineddata ($(wc -c < "$VASSAL_TESSDATA_DIR/rus.traineddata") байт)"
    echo "  для прямых вызовов: export TESSDATA_PREFIX=\"$VASSAL_TESSDATA_DIR\""
else
    echo "✗ rus.traineddata (нет или пустой) — tesseract-спот-сверка недоступна, остаётся vision"
fi

echo ""
if python3 -c "import fitz" 2>/dev/null; then
    echo "=== Готово. PDF читаются через pymupdf. tesseract не нужен: OCR-путь — vision. ==="
elif command -v pdftotext &> /dev/null; then
    echo "⚠️  === pymupdf не установлен — PDF идут через poppler (запасной путь, F.2). ==="
    echo "    Работает, но качество извлечения ниже: страницы с потерянными глифами"
    echo "    уходят на vision, пустые не отличаются от сканов. Причина отказа — в логе выше."
else
    echo "✗ === Ни pymupdf, ни poppler недоступны — PDF прочитать НЕЧЕМ. ==="
    echo "    Это блокирует приём документов. Разберите причину по логу выше."
fi
