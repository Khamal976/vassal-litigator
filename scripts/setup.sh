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
echo "→ Python-зависимости (PyYAML, pymupdf, python-docx, openpyxl)..."
pip install --break-system-packages -q PyYAML pymupdf python-docx openpyxl 2>/dev/null \
    || pip install -q PyYAML pymupdf python-docx openpyxl 2>/dev/null \
    || echo "⚠️  Часть Python-пакетов не установилась — см. статус ниже."

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
check_py fitz       # pymupdf — нужен extract_text.py
check_py docx
check_py openpyxl
check_cmd tesseract
check_cmd ocrmypdf
check_cmd soffice

echo ""
echo "=== Готово. Если tesseract недоступен — это ок: основной OCR-путь — vision. ==="
