## [vassal-litigator] этап 6.1 -- 2026-05-11

### Fixed
- **Кросс-машинная проблема пути к notion-config.** В этапе 6 путь `~/.vassal/notion-config.yaml` был захардкожен. На Windows `~` резолвится в `C:\Users\{имя}\` -- разные имена пользователей на разных машинах превращали путь в разные физические места без синхронизации. Симметрично проблема существовала бы и для `$VASSAL_GLOBAL_DIR` без env var override (он уже был в этапе 6).

### Added
- Новая переменная окружения `VASSAL_CONFIG_DIR` -- симметричный близнец `VASSAL_GLOBAL_DIR`. По умолчанию `~/.vassal/`. Если задана -- путь к конфигу становится `$VASSAL_CONFIG_DIR/notion-config.yaml`. Типовой сценарий: положить конфиг в OneDrive/Dropbox/Yandex.Disk-папку, на каждой машине установить env var на её локальный путь -- так на двух Windows-машинах с разными именами пользователей работает один и тот же синкаемый файл.

### Changed
- `skills/notion-sync/SKILL.md`: Phase 0 шаг 1 -- явный резолв `$VASSAL_CONFIG_DIR` с fallback на `~/.vassal/`. Раздел «Конфигурация» обновлён под новый путь. Постусловия -- упомянут резолв.
- `commands/sync-notion.md`, `commands/init-case.md`, `skills/analyze-hearing/SKILL.md`, `skills/appeal/SKILL.md`, `skills/cassation/SKILL.md`: хуки и предусловия проверяют конфиг по разрезолвленному пути, а не по жёстко прописанному `~/.vassal/`.
- `shared/conventions.md`: раздел «Notion-слой» → «Конфигурация» расширен описанием `$VASSAL_CONFIG_DIR`. Таблица «Внешние зависимости» обновлена.
- `scripts/notion-init.md`: расширенный раздел 3.1 -- два варианта хранения (А -- одна машина с `~/.vassal/`; Б -- кросс-машинный синк через `reg add /t REG_EXPAND_SZ` с встроенной Windows-переменной `%OneDrive%`); готовые команды; альтернативы (`%USERPROFILE%\OneDrive`, жёсткий путь через `setx`).
- `scripts/notion-config.example.yaml`: header дополнен инструкцией по env var.
- `shared/conventions.md`: подсказка по `REG_EXPAND_SZ` для Windows -- ключевая деталь: `setx` создаёт `REG_SZ` без раскрытия `%VAR%`, поэтому для кросс-машинной конфигурации не годится; нужен `reg add /t REG_EXPAND_SZ`.

### Note about Windows `reg add` vs `setx`
Изначально в этой же ветке предлагалось использовать `setx VASSAL_*_DIR "C:\Users\{имя}\OneDrive\..."`, что требовало знать имя пользователя на каждой машине. Лучшее решение -- `reg add /t REG_EXPAND_SZ /d "%OneDrive%\Документы\Claude Cowork\.vassal-..."`: значение хранится **с литералом `%OneDrive%`**, а Windows раскрывает его под каждого пользователя при создании нового процесса. Одна команда, два разных результата на двух машинах. См. `scripts/notion-init.md` §3.1 для готовых команд.

## [vassal-litigator] этап 6 рефакторинга -- 2026-05-10

### Added
- Кросс-дельная память (`$VASSAL_GLOBAL_DIR/`, по умолчанию `~/.vassal-global/`):
  - `judges/{ФИО-slug}--{court-slug}.md` -- накопительный профиль судьи по всем делам Сюзерена с этой парой (судья × суд). Двойная запись из `analyze-hearing` (устные паттерны) и `draft-judgment` (письменный стиль). Аппенд-only с маркерами `(дело {номер}, {дата})`.
  - `counterparties/inn-{ИНН}.md` (или `noinn-{slug}.md`) -- накопительный профиль оппонента по всем делам с ним. Двойная запись из `add-opponent` (письменные паттерны) и `analyze-hearing` (устные). Те же правила накопления.
  - Конфигурируемый путь через переменную `VASSAL_GLOBAL_DIR` -- сценарий синка между машинами через облачный диск.
  - Фиксация в `shared/conventions.md` → раздел «Глобальная память (кросс-дельная)»; в `ARCHITECTURE.md` → раздел 15.
- Notion-слой MVP (опционально):
  - `skills/notion-sync/SKILL.md` -- односторонний push в две Notion-базы (Cases + Judges), idempotent upsert, dedup по `case.number` / `slug`, `fields_manual_only` для ручных полей юриста.
  - `commands/sync-notion.md` -- ручной триггер `/vassal-litigator:sync-notion` с флагами `--dry-run`, `--force`.
  - `scripts/notion-init.md` + `scripts/notion-config.example.yaml` -- bootstrap-инструкция (разовая) и шаблон `~/.vassal/notion-config.yaml`.
  - Опциональные не-блокирующие хуки в `init-case`, `analyze-hearing`, `appeal`, `cassation` -- предлагают синк только при наличии конфига.

### Changed
- `analyze-hearing/SKILL.md`: Phase 1 шаг 3.1 -- чтение глобального профиля судьи; Phase 6 шаги 10.1-10.2 -- двойная запись в `$VASSAL_GLOBAL_DIR/judges/` и `counterparties/`. Новый раздел «Формат глобального профиля судьи». Локальный `judge-profile.md` теперь содержит во frontmatter `shared_profile:`.
- `draft-judgment/SKILL.md`: Phase 1 шаг 5.1 -- чтение глобального профиля; Phase 2 шаг 9 -- двойная запись (раздел 7 «Письменный стиль решений») в глобальный.
- `add-opponent/SKILL.md`: Phase 1 шаг 2.1 -- чтение глобального профиля оппонента; Phase 4 шаг 19 -- двойная запись в `$VASSAL_GLOBAL_DIR/counterparties/`. Новый раздел «Формат глобального профиля оппонента».
- `prepare-hearing/SKILL.md`: Phase 1 шаг 3.1 -- чтение обоих глобальных профилей (судья + оппонент). Раздел «Работа с профилем судьи» расширен под три источника по приоритету.
- `build-position/SKILL.md`: Phase 1 шаг 4.1 -- чтение глобального оппонента. Блок «Прогноз аргументов оппонента» -- учёт повторяющихся доводов из прошлых дел.
- `appeal/SKILL.md`: Phase 1 шаг 9.1 -- чтение обоих глобальных профилей. Phase 7 -- хук Notion.
- `cassation/SKILL.md`: Phase 1 шаг 8.1 -- чтение обоих глобальных профилей; red team-субагент использует профиль оппонента. Phase 7 -- хук Notion.
- `shared/conventions.md`: новые разделы «Глобальная память (кросс-дельная)» и «Notion-слой»; таблица «Внешние зависимости» дополнена Notion MCP и notion-config.yaml.
- `shared/case-schema.yaml`: уточнено использование `parties[].inn`/`ogrn` как ключа дедупликации для глобальной памяти.
- `commands/init-case.md`: шаг 7 -- опциональный хук Notion.
- `ARCHITECTURE.md`: раздел 2 -- добавлены `notion-sync` и `notion-init.md`/`notion-config.example.yaml`; раздел 9 -- ортогональный слой глобальной памяти и опциональный Notion-слой; **новый раздел 15** -- «Кросс-дельная память».

Закрывает п.22-23 этапа 6 из FINAL-REPORT.md и антипаттерн §3.10 «Изоляция кросс-дельной памяти».

## [vassal-litigator] v0.4.0 -- 2026-03-27

### Added
- Фаза 4 -- Обжалование и прогнозирование:
  - `draft-judgment` -- скилл + команда проекта судебного акта (цифровой профиль судьи по Мошкину, анализ стиля по 3-5 решениям, Opus-генерация)
  - `appeal` -- скилл + команда апелляционной жалобы (систематический поиск оснований по ст. 270 АПК РФ / ст. 330 ГПК РФ, стресс-тест, Opus-анализ)
  - `cassation` -- скилл + команда кассационной жалобы (проверка только применения норм права, сравнительный анализ двух инстанций, обязательные ссылки на ВС РФ)

### Changed
- plugin.json: версия 0.3.0 -> 0.4.0

## [vassal-litigator] v0.3.0 -- 2026-03-26

### Added
- Фаза 3 -- Ведение дела:
  - `add-evidence` -- скилл + команда приема дополнительных доказательств от клиента
  - `add-opponent` -- скилл + команда приема документов оппонента (с экспресс-анализом аргументов)
  - `prepare-hearing` -- скилл + команда подготовки к заседанию (red team/blue team, генерация процессуального документа через arbitrum-docx)
  - `analyze-hearing` -- скилл + команда анализа транскрипции заседания (внутренний отчет + отчет для клиента)

## [vassal-litigator] v0.2.0 -- 2026-03-26

### Added
- Фаза 2 -- Анализ:
  - `legal-review` -- скилл + команда предварительного правового анализа документов (Opus)
  - `build-position` -- скилл + команда формирования правовой позиции (Opus, 7 блоков, аудируемый формат)
- Конвенции: дата-префикс в именах файлов, источники по названиям документов (не doc-ID)

### Changed
- shared/conventions.md -- добавлены правила дата-префикса и источников

## [vassal-litigator] v0.1.0 -- 2026-03-26

### Added
- Архитектура v0.2.0-draft (ARCHITECTURE.md)
- Фаза 1 — Фундамент:
  - `init-case` — команда инициализации дела (case.yaml, index.yaml, структура папок)
  - `intake` — скилл + команда приёма материалов клиента (OCR, переименование, md-зеркала, preview→apply)
  - `catalog` — скилл + команда каталогизации документов (xlsx-таблица, обогащение summary)
  - `update-index` — скилл + команда верификации и обновления индекса
- shared/ — конвенции, схемы (case.yaml, index.yaml), шаблон md-зеркала
- scripts/ — setup.sh (установка зависимостей), extract_text.py (извлечение текста из PDF/DOCX/изображений)
- plugin.json, .mcp.json
