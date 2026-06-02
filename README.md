# vassal-litigator

Плагин для [Claude Cowork](https://claude.ai), помогающий юристу вести судебные дела — от первичного приёма материалов клиента до кассационной жалобы.

## Возможности

**Приём и систематизация документов** — OCR сканов и фотографий, переименование файлов по содержимому, создание текстовых зеркал, автоматическое ведение реестра документов дела.

**Правовой анализ** — квалификация спора, проверка сроков исковой давности, определение подсудности, оценка полноты доказательственной базы, формирование правовой позиции с оценкой рисков.

**Подготовка к заседаниям** — стресс-тест позиции (red team / blue team), генерация процессуальных документов (отзывы, ходатайства, пояснения) через связанный плагин `arbitrum-docx`.

**Анализ заседаний** — разбор транскрипций: речевые паттерны судьи, уклончивые ответы оппонента, рекомендации по тактике.

**Обжалование** — подготовка апелляционных и кассационных жалоб с систематическим поиском оснований по АПК/ГПК РФ, проект судебного решения с учётом стиля конкретного судьи.

## Скиллы (12)

| Фаза | Скилл | Описание |
|------|-------|----------|
| Фундамент | `intake` | Приём и обработка материалов клиента |
| | `catalog` | Генерация xlsx-таблицы документов |
| | `update-index` | Верификация и синхронизация реестра |
| Анализ | `legal-review` | Комплексный правовой анализ |
| | `build-position` | Формирование правовой позиции |
| Ведение дела | `add-evidence` | Приём доп. доказательств от клиента |
| | `add-opponent` | Приём и анализ документов оппонента |
| | `prepare-hearing` | Подготовка к заседанию |
| | `analyze-hearing` | Анализ транскрипции заседания |
| Обжалование | `draft-judgment` | Проект судебного решения |
| | `appeal` | Апелляционная жалоба |
| | `cassation` | Кассационная жалоба |
| Sync | `notion-sync` | Опц. push метаданных дел и профилей судей в Notion (Cases + Judges) |

**Кросс-дельная память** (этап 6): профили судей и оппонентов накапливаются в `$VASSAL_GLOBAL_DIR/` (по умолчанию `~/.vassal-global/`) -- читаются всеми скиллами как фон до анализа. На двух машинах с разными именами пользователей -- через `reg add /t REG_EXPAND_SZ` с `%OneDrive%`. См. [shared/conventions.md](shared/conventions.md) → «Глобальная память» и [ARCHITECTURE.md §15](ARCHITECTURE.md).

**Открытые задачи и ограничения** -- [OPEN-ITEMS.md](OPEN-ITEMS.md) (живой трекер).

## Установка

### 1. Установите как плагин Claude Cowork

Скачайте `.plugin`-файл из [Releases](../../releases) или клонируйте репозиторий:

```bash
git clone https://github.com/YOUR_USERNAME/vassal-litigator.git
```

### 2. Установите зависимости

```bash
cd vassal-litigator
chmod +x scripts/setup.sh
./scripts/setup.sh
```

Скрипт установит: `tesseract-ocr` (для OCR), а также Python-пакеты `python-docx`, `openpyxl`, `pymupdf`.

### 3. Связанный плагин (опционально)

Для генерации процессуальных документов в `.docx` рекомендуется создать скилл или плагин для создания документов по используемому вами шаблону.

## Быстрый старт

1. Создайте новое дело: `/vassal-litigator:init-case`
2. Положите документы клиента в папку «Входящие документы/»
3. Обработайте: `/vassal-litigator:intake`
4. Далее по ситуации: `catalog` → `legal-review` → `build-position` → `prepare-hearing` и т.д.

## Маршрутизация моделей

| Задача | Модель |
|--------|--------|
| OCR, md-зеркала, саммари | Haiku |
| Систематизация, таблицы | Sonnet |
| Правовой анализ, позиции, жалобы | Opus |

## Структура проекта

```
vassal-litigator/
├── .claude-plugin/
│   └── plugin.json          # Манифест плагина
├── commands/                 # Slash-команды (13)
├── skills/                   # Скиллы (12)
│   ├── intake/
│   ├── catalog/
│   ├── legal-review/
│   │   └── references/       # Справочники по срокам, подсудности, досудебному порядку
│   ├── build-position/
│   ├── add-evidence/
│   ├── add-opponent/
│   ├── prepare-hearing/
│   ├── analyze-hearing/
│   ├── draft-judgment/
│   ├── appeal/
│   ├── cassation/
│   └── update-index/
├── shared/                   # Общие схемы и конвенции
│   ├── conventions.md
│   ├── case-schema.yaml
│   ├── index-schema.yaml
│   └── mirror-template.md
├── scripts/                  # Утилиты
│   ├── setup.sh
│   └── extract_text.py
├── ARCHITECTURE.md           # Подробная архитектура
├── CHANGELOG.md
├── OPEN-ITEMS.md             # Живой трекер открытых задач и ограничений
└── FINAL-REPORT.md           # Историческая ревизия плагина и план рефакторинга
```

## Сборка дистрибутива

```powershell
pwsh scripts/build-plugin.ps1
# или, если pwsh нет: powershell -File scripts/build-plugin.ps1
```

Версия берётся из `.claude-plugin/plugin.json`, артефакт ложится в `dist/vassal-litigator-<version>.plugin`. Скрипт пакует whitelist (`.claude-plugin`, `.mcp.json`, `commands/`, `skills/`, `scripts/`, `shared/`, `README.md`, `CHANGELOG.md`, `LICENSE`) в корень zip с forward-slash путями — формат, который требует валидатор Cowork.

**Pre-flight description-length check.** Перед упаковкой скрипт читает frontmatter каждого `skills/*/SKILL.md` (учитывая folded `description: >`) и аборtает сборку, если длина `description` превышает 1024 символа -- жёсткий лимит валидатора Cowork, который иначе вернёт generic «Plugin validation failed» без указания файла ([#56376](https://github.com/anthropics/claude-code/issues/56376)). Для `commands/*.md` лимит мягче: предупреждение при > 250 символов (порог отображения по [#44780](https://github.com/anthropics/claude-code/issues/44780)), без abort.

## Лицензия

GPL-3.0. См. [LICENSE](LICENSE).

## Автор

Ian ([@strigov](https://github.com/strigov))
