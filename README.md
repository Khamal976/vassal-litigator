# vassal-litigator

Плагин для [Claude Cowork](https://claude.ai), помогающий юристу вести судебные дела — от первичного приёма материалов клиента до кассационной жалобы.

## Возможности

**Приём и систематизация документов** — OCR сканов и фотографий, переименование файлов по содержимому, создание текстовых зеркал, автоматическое ведение реестра документов дела.

**Правовой анализ** — квалификация спора, проверка сроков исковой давности, определение подсудности, оценка полноты доказательственной базы, формирование правовой позиции с оценкой рисков.

**Подготовка к заседаниям** — стресс-тест позиции (red team / blue team), генерация процессуальных документов (отзывы, ходатайства, пояснения); оформление в `.docx` по фирменной типографике через встроенный `format-doc` (headless, детерминированно).

**Анализ заседаний** — разбор транскрипций: речевые паттерны судьи, уклончивые ответы оппонента, рекомендации по тактике.

**Обжалование** — подготовка апелляционных и кассационных жалоб с систематическим поиском оснований по АПК/ГПК РФ, проект судебного решения с учётом стиля конкретного судьи.

## Скиллы (23)

| Фаза | Скилл | Описание |
|------|-------|----------|
| Фундамент | `init-case` | Инициализация дела: структура папок + карточка |
| | `intake` | Приём и обработка материалов клиента |
| | `catalog` | Генерация xlsx-таблицы документов |
| | `update-index` | Верификация и синхронизация реестра |
| Анализ | `study-evidence` | Исследование фактуры доказательств → досье со ссылками на лист |
| | `legal-review` | Комплексный правовой анализ |
| | `build-position` | Формирование правовой позиции |
| | `revise-position` | Обратное распространение правок позиции по памяти дела (леджер отзывов) |
| Досудебная стадия | `draft-claim` | Досудебная претензия либо ответ на входящую претензию |
| Ведение дела | `add-evidence` | Приём доп. доказательств от клиента |
| | `add-opponent` | Приём и анализ документов оппонента |
| | `prepare-hearing` | Подготовка к заседанию |
| | `argument-map` | Карта доводов сторон — таблица по узлам спора (2 версии: чистая для суда + рабочая) |
| | `analyze-hearing` | Анализ транскрипции заседания |
| | `settlement` | Примирение: мировое / отказ / признание иска |
| Обжалование | `draft-judgment` | Проект судебного решения |
| | `appeal` | Апелляционная жалоба |
| | `cassation` | Кассационная жалоба |
| Исполнение | `enforcement-adjustment` | Отсрочка, рассрочка, изменение способа и порядка исполнения (ст. 324 АПК / ст. 203, 434 ГПК / ст. 358 КАС); возражения и прекращение отсрочки |
| На подачу | `format-doc` | Оформление .docx по фирменной типографике (headless, детерминированно) |
| | `build-submission` | Сборка нумерованного комплекта на подачу |
| Sync | `notion-sync` | Опц. push метаданных дел и профилей судей в Notion (Cases + Judges) |
| | `backfill-global` | Разовый перенос локальной аналитики в глобальную память |
| | `index-samples` | Разовое наполнение каталога образцов — указателя «по вопросу X был документ типа Y в деле Z» |

**Кросс-дельная память** (этап 6): профили судей и оппонентов, а также **каталог образцов** (`samples/` — указатель «по вопросу X был документ типа Y в деле Z», без текста и без абсолютных путей) накапливаются в `$VASSAL_GLOBAL_DIR/` (по умолчанию `~/.vassal-global/`) -- читаются всеми скиллами как фон до анализа. На двух машинах с разными именами пользователей -- через `reg add /t REG_EXPAND_SZ` с `%OneDrive%`. См. [shared/conventions.md](shared/conventions.md) → «Глобальная память» и [ARCHITECTURE.md §15](ARCHITECTURE.md).

**Открытые задачи и ограничения** -- [OPEN-ITEMS.md](OPEN-ITEMS.md) (живой трекер).

## Установка

### 1. Установите как плагин Claude Cowork

Скачайте `.plugin`-файл из [Releases](../../releases) или клонируйте репозиторий:

```bash
git clone https://github.com/YOUR_USERNAME/vassal-litigator.git
```

### 2. Установите зависимости

**Linux / Cowork:**

```bash
cd vassal-litigator
chmod +x scripts/setup.sh
./scripts/setup.sh
```

**Windows (PowerShell):** `setup.sh` — bash-скрипт и в PowerShell не исполняется, поэтому для Windows отдельный установщик:

```bash
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
```

Либо вручную одной строкой:

```bash
python -m pip install PyYAML pymupdf python-docx openpyxl
```

Скрипт установит Python-пакеты `PyYAML`, `pymupdf`, `python-docx`, `openpyxl` (в Linux-версии дополнительно, best-effort — `tesseract-ocr` для опциональной спот-сверки; основной путь OCR — vision).

**Проверка, что зависимости действительно доступны** (проверяется импортом, а не сообщением менеджера пакетов):

```bash
python scripts/analyze_table.py --selftest
```

⚠️ На Windows вызывайте `python`, а не `python3`: последний часто оказывается заглушкой Windows, ведущей на другую сборку без зависимостей. Подробное правило — `shared/conventions.md` → «Единый паттерн feature detection + fallback», п. 0.

### 3. Глобальная память (рекомендуется задать сразу)

Профили судей и оппонентов накапливаются в `$VASSAL_GLOBAL_DIR/` и переиспользуются между делами. **Если переменную не задать**, плагин пишет в резервный `~/.vassal-global/` — а в песочнице Cowork этот путь **очищается между сессиями**, и накопленные наблюдения не сохранятся (плагин предупредит об этом при первой записи, но лучше задать путь заранее).

Задайте `VASSAL_GLOBAL_DIR` на синхронизируемую папку (OneDrive / Яндекс.Диск) — тогда память переживает сессии и синкается между машинами:

```powershell
# Windows, кросс-машинно (одна команда работает на всех машинах одного пользователя):
reg add "HKCU\Environment" /v VASSAL_GLOBAL_DIR /t REG_EXPAND_SZ /d "%OneDrive%\Документы\Claude Cowork\.vassal-global" /f
```

```bash
# Linux / macOS (в ~/.bashrc или ~/.zshrc):
export VASSAL_GLOBAL_DIR="$HOME/OneDrive/vassal-global"
```

**После `reg add` перезапустите Claude Code** — переменные окружения подхватываются только новыми процессами. Полная инструкция (в т.ч. почему `setx` не подходит и как задать `VASSAL_CONFIG_DIR` соседним подкаталогом) — [scripts/notion-init.md](scripts/notion-init.md) §4.1.

### 4. Связанный плагин (опционально)

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
├── commands/                 # Slash-команды (23)
├── skills/                   # Скиллы (23)
│   ├── init-case/
│   ├── intake/
│   ├── catalog/
│   ├── update-index/
│   ├── study-evidence/
│   ├── legal-review/
│   │   └── references/       # Справочники по срокам, подсудности, досудебному порядку
│   ├── build-position/
│   ├── revise-position/
│   ├── draft-claim/            # Досудебная претензия / ответ на неё (правовой профиль — у legal-review)
│   ├── add-evidence/
│   ├── add-opponent/
│   ├── prepare-hearing/
│   ├── argument-map/
│   ├── analyze-hearing/
│   ├── settlement/
│   ├── draft-judgment/
│   ├── appeal/
│   ├── cassation/
│   ├── enforcement-adjustment/ # Отсрочка / рассрочка / изменение способа исполнения (профиль — у legal-review)
│   ├── build-submission/
│   ├── format-doc/             # Headless-оформление .docx (references/style-spec.md)
│   ├── backfill-global/
│   ├── index-samples/
│   └── notion-sync/
├── shared/                   # Общие схемы и конвенции
│   ├── conventions.md
│   ├── case-schema.yaml
│   ├── index-schema.yaml
│   └── mirror-template.md
├── scripts/                  # Утилиты
│   ├── setup.sh                 # Linux/Cowork
│   ├── setup.ps1                # Windows (PowerShell)
│   ├── extract_text.py
│   ├── tessdata/             # Вендоренный rus.traineddata для OCR
│   ├── notion-init.md
│   └── build-plugin.ps1
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
