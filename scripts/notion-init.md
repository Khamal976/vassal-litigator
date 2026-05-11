# Bootstrap Notion-слоя для vassal-litigator

Разовая операция: создать в Notion-workspace две базы (`Cases` и `Judges`) со схемой, которую ожидает `skills/notion-sync`, и записать их ID в файл конфига `notion-config.yaml`.

**Расположение конфига** (правила резолва -- из [shared/conventions.md](../shared/conventions.md) → «Notion-слой» → «Конфигурация»):
- По умолчанию: `~/.vassal/notion-config.yaml`.
- Переопределение через `$VASSAL_CONFIG_DIR` -- путь становится `$VASSAL_CONFIG_DIR/notion-config.yaml`. Используется для кросс-машинного синка через OneDrive/Dropbox/etc.

> Это **bootstrap, не sync.** Запускается один раз на установку плагина (или при пересоздании workspace). Регулярная синхронизация -- через `/vassal-litigator:sync-notion`.

---

## 0. Предварительные условия

- Notion-аккаунт с правами создавать базы.
- Notion MCP-сервер подключён к Claude Code и авторизован (проверь через `/mcp` или попробуй вызов `notion-search`).
- Решено, в каком родителе создавать базы:
  - **Вариант А** -- private workspace (только Сюзерен): пропустить родителя, базы будут на верхнем уровне.
  - **Вариант Б** -- внутри teamspace: получить `teamspace_id` через UI Notion (URL teamspace) или через `notion-search query_type: "internal"`.
  - **Вариант В** -- внутри существующей страницы (например, «Юридическая практика»): получить `page_id` страницы.

---

## Порядок создания

Cases ссылается на Judges и (с этапа 6.2b) на Counterparties через RELATION. Чтобы избежать заглушек, **рекомендуемый порядок**: 1. Judges → 2. Counterparties → 3. Cases (Cases создаётся последним со всеми relation-id, готовыми из шагов 1-2). Если у тебя bootstrap старой установки (до 6.2b) и Counterparties не нужна -- пропусти шаг 2 (Counterparties), и в DDL Cases уберёт ссылку `Оппонент`.

---

## 1. Создание базы `Judges`

Через MCP-tool `notion-create-database`:

```json
{
  "title": "Judges (vassal-litigator)",
  "description": "Профили судей, агрегируются из $VASSAL_GLOBAL_DIR/judges/ всех дел",
  "parent": { "type": "page_id", "page_id": "<id-родительской-страницы>" },
  "schema": "CREATE TABLE (\"ФИО\" TITLE, \"Суд\" RICH_TEXT, \"slug\" RICH_TEXT COMMENT 'Технический ключ -- {ФИО-slug}--{court-slug}', \"Стиль\" RICH_TEXT, \"Паттерны\" RICH_TEXT, \"Склонности\" RICH_TEXT, \"Дел с ним\" NUMBER, \"Last sync\" DATE)"
}
```

Запиши `data_source_id` -- пойдёт в `notion-config.yaml: notion.databases.judges`.

---

## 2. Создание базы `Counterparties` (этап 6.2b, опционально)

Через `notion-create-database`. Если не хочешь использовать Counterparties-слой -- пропусти этот шаг.

```json
{
  "title": "Counterparties (vassal-litigator)",
  "description": "Профили процессуальных оппонентов, агрегируются из $VASSAL_GLOBAL_DIR/counterparties/ всех дел",
  "parent": { "type": "page_id", "page_id": "<id-родительской-страницы>" },
  "schema": "CREATE TABLE (\"Организация\" TITLE, \"ИНН\" RICH_TEXT, \"ОГРН\" RICH_TEXT, \"slug\" RICH_TEXT COMMENT 'Технический ключ -- inn-{ИНН} или noinn-{slug-name}', \"Типовые доводы\" RICH_TEXT COMMENT 'Сжатый § 1 глобального профиля', \"Тактика\" RICH_TEXT COMMENT 'Сжатый § 2 глобального профиля', \"Представители\" RICH_TEXT COMMENT 'ФИО + годы активности', \"Дел с ним\" NUMBER, \"Last sync\" DATE)"
}
```

**Важно:** обратная relation `Дела` (Counterparties → Cases) на этом шаге не создаётся -- она появится автоматически как dual, когда в Cases будет создано поле `Оппонент` со ссылкой сюда (шаг 3).

Запиши `data_source_id` -- пойдёт в `notion-config.yaml: notion.databases.counterparties`.

---

## 3. Создание базы `Cases`

Через MCP-tool `notion-create-database`. Передать:

```json
{
  "title": "Cases (vassal-litigator)",
  "description": "Реестр всех дел, синхронизируется из локального .vassal/case.yaml каждого дела",
  "parent": { "type": "page_id", "page_id": "<id-родительской-страницы>" },
  "schema": "CREATE TABLE (\"Номер дела\" TITLE, \"Суд\" SELECT('АС Красноярского края':blue, 'АС Москвы':orange, 'АС СПб':green, 'СОЮ':gray, '3-й ААС':purple, 'АС МО':red), \"Наш клиент\" RICH_TEXT, \"Истец\" RICH_TEXT, \"Ответчик\" RICH_TEXT, \"Наша роль\" SELECT('истец':blue, 'ответчик':red, 'третье лицо':gray, 'заявитель':green, 'заинтересованное лицо':orange), \"Стадия\" SELECT('Досудебная':gray, '1 инстанция':blue, '1 инстанция (приостановлено)':yellow, 'Апелляция':orange, 'Кассация':red, 'Исполнение':green, 'Закрыто':default), \"Статус\" SELECT('active':blue, 'paused':yellow, 'closed':gray, 'won':green, 'lost':red) COMMENT 'Ручное поле -- не перезаписывается sync', \"Следующее заседание\" DATE, \"Судья\" RELATION('<judges-data-source-id>'), \"Оппонент\" RELATION('<counterparties-data-source-id>') COMMENT 'Опционально -- убрать если шаг 2 пропущен', \"Путь к папке\" RICH_TEXT COMMENT 'Хранит %OneDrive%\\\\<rel-path> для кросс-машинной кликабельности через копипаст в Explorer', \"Last sync\" DATE)"
}
```

**Важно:**
- `<id-родительской-страницы>` -- ID из шага 0 (для варианта А -- параметр `parent` можно опустить).
- `<judges-data-source-id>` -- из ответа шага 1.
- `<counterparties-data-source-id>` -- из ответа шага 2. Если шаг 2 был пропущен -- убери `\"Оппонент\" RELATION(...)` из CREATE TABLE; это поле можно добавить позже через `notion-update-data-source` (см. также «Миграция этапа 6.2 → 6.2b» в разделе 7).

После создания запиши `data_source_id` из `<data-source>` тега ответа -- это ID, который пойдёт в `notion-config.yaml: notion.databases.cases`.

---

## 4. Заполнение конфига

### 4.1. Реши, где файл будет жить

**Вариант А -- одна машина (по умолчанию):** `~/.vassal/notion-config.yaml`. Никаких env vars не нужно.

**Вариант Б -- две и более машины с синком через облако (OneDrive/Dropbox/Yandex.Disk):** положи файл в синхронизируемую папку и укажи путь через `$VASSAL_CONFIG_DIR` + `$VASSAL_GLOBAL_DIR`.

**Тонкость на Windows:** `setx VAR "значение"` создаёт env var типа `REG_SZ` -- литеральная строка без раскрытия `%VAR%`-плейсхолдеров. На двух Windows-машинах с разными именами пользователя пришлось бы поставить разные значения (`C:\Users\kholv\...` vs `C:\Users\другой\...`).

**Решение -- `REG_EXPAND_SZ` через `reg add`.** Этот тип заставляет Windows раскрывать `%VAR%` при запуске каждого нового процесса. Если использовать встроенную Windows-переменную `%OneDrive%` (которую OneDrive-клиент сам выставляет в `C:\Users\{текущий_user}\OneDrive`), то на обеих машинах ставится **одно и то же значение** -- Windows автоматически подставит правильный профиль.

```cmd
reg add HKCU\Environment /v VASSAL_GLOBAL_DIR /t REG_EXPAND_SZ /d "%OneDrive%\Документы\Claude Cowork\.vassal-global" /f
reg add HKCU\Environment /v VASSAL_CONFIG_DIR /t REG_EXPAND_SZ /d "%OneDrive%\Документы\Claude Cowork\.vassal" /f
```

Эта пара команд работает **одинаково на обеих машинах**, без подстановки имени пользователя. Запуск -- из обычного `cmd.exe` (не из MSYS Bash, чтобы кириллица не пострадала; либо через PowerShell с `-Command`).

После `reg add` env vars подхватываются только новыми процессами -- перезапусти Claude Code (и любые другие инструменты, которые должны их видеть).

**Альтернативы `%OneDrive%`:**
- `%USERPROFILE%\OneDrive\...` -- работает даже без OneDrive-клиента, при условии что OneDrive в дефолтной локации. Менее семантически точно, но не требует, чтобы переменная `%OneDrive%` была определена.
- Полный жёсткий путь без переменных -- если на разных машинах OneDrive в нестандартных локациях и нужно явно указать каждой; тогда `setx` (REG_SZ) разными значениями на каждой машине.

**Linux/macOS:** просто `export VASSAL_GLOBAL_DIR=...` в `~/.bashrc`/`~/.zshrc`. На Unix `~` уже резолвится одинаково везде, проблема кросс-машинной адресации стоит мягче. Облачный синк тоже через переменную с явным абсолютным путём.

**Проверка**, что значение в реестре имеет правильный тип и литерал:
```cmd
reg query HKCU\Environment /v VASSAL_GLOBAL_DIR
```
Должно вывести `REG_EXPAND_SZ` и значение с `%OneDrive%` (без раскрытия).

### 4.2. Создай файл

Для варианта А:
```bash
mkdir -p ~/.vassal
touch ~/.vassal/notion-config.yaml
```

Для варианта Б (Windows / Git Bash):
```bash
mkdir -p "/c/Users/{имя}/OneDrive/Документы/Claude Cowork/.vassal"
touch "/c/Users/{имя}/OneDrive/Документы/Claude Cowork/.vassal/notion-config.yaml"
```

Шаблон содержимого -- в [notion-config.example.yaml](./notion-config.example.yaml). Скопируй и подставь свои `data_source_id`:

```yaml
notion:
  workspace_id: "<id-workspace-если-нужно-для-фильтров>"   # опционально
  databases:
    judges: "<data-source-id-из-шага-1>"
    counterparties: "<data-source-id-из-шага-2>"   # опционально, удали если шаг 2 пропущен
    cases: "<data-source-id-из-шага-3>"
  fields_manual_only:
    cases:
      - "Статус"           # юрист правит won/lost вручную, sync не трогает
  fields_map:
    cases:
      title: "Номер дела"
      court: "Суд"
      our_client: "Наш клиент"
      plaintiff: "Истец"
      defendant: "Ответчик"
      our_role: "Наша роль"
      stage: "Стадия"
      next_hearing: "Следующее заседание"
      judge_relation: "Судья"
      opponent_relation: "Оппонент"
      folder_url: "Путь к папке"
      last_sync: "Last sync"
    judges:
      title: "ФИО"
      court: "Суд"
      slug: "slug"
      style: "Стиль"
      patterns: "Паттерны"
      tendencies: "Склонности"
      cases_count: "Дел с ним"
      last_sync: "Last sync"
    counterparties:
      title: "Организация"
      inn: "ИНН"
      ogrn: "ОГРН"
      slug: "slug"
      typical_arguments: "Типовые доводы"
      tactics: "Тактика"
      representatives: "Представители"
      cases_count: "Дел с ним"
      last_sync: "Last sync"
```

**Опционально (для команд из нескольких юристов):**
```yaml
notion:
  owner: "Стригов Я. А."   # передаётся как property во все базы для фильтрации в views
```

---

## 5. Проверка

Запусти `/vassal-litigator:sync-notion --dry-run` в каком-нибудь существующем деле:
- Скилл должен прочитать конфиг, прочитать `case.yaml`, собрать properties и **показать** их Сюзерену без upsert в Notion.
- Если Сюзерен видит в выводе ожидаемые поля -- bootstrap прошёл корректно.
- Запусти без `--dry-run` -- запись должна появиться в Notion.

---

## 6. Что делать, если bootstrap прошёл с ошибкой

**Базы созданы дважды (повторный запуск шагов 1-3):**
- Удалить дубликаты в Notion вручную.
- Обновить `data_source_id` в конфиге на актуальные.

**`relation` Cases→Judges не работает (была создана до Judges):**
- Через `notion-update-data-source` добавить колонку `Судья` типа `RELATION('<judges-data-source-id>')` в Cases.
- Если в Cases уже есть записи без relation -- следующий sync (для тех же дел) проставит relation автоматически.

**`relation` Cases→Counterparties не работает / Cases создана без `Оппонент`:**
- См. раздел 7 «Миграция этапа 6.2 → 6.2b».

**MCP не отвечает на create_database:**
- Проверить `/mcp` -- авторизован ли Notion MCP.
- Проверить, что у токена есть права создавать базы в выбранном parent.
- Альтернатива: создать базы вручную в UI Notion и выписать их `data_source_id` (открыть базу как полную страницу → URL вида `notion.so/{workspace}/{database-id}?v={view-id}`; через `notion-fetch` по этой URL получить data_source_id).

---

## 7. Миграция этапа 6.2 (для существующих установок)

Если базы `Cases` и `Judges` уже созданы по версии до этапа 6.2, и в них есть данные -- нужны разовые миграции схемы. Шаги ниже **идемпотентны** -- безопасно запускать повторно. Подразделы независимы -- можно делать в любом порядке, **6.2c -- чисто в коде плагина**, в Notion миграция не нужна.

### 6.2a -- `Cases.Путь к папке`: URL → RICH_TEXT

**Зачем:** старый URL-формат (`file:///C:/Users/kholv/...`) не открывается на второй машине -- абсолютный путь привязан к имени пользователя. Новый формат (`%OneDrive%\Работа\case-A`) копипастится в адресную строку Explorer, Windows раскрывает плейсхолдер локально на каждой машине.

**Шаги:**

1. Через UI Notion: открой базу `Cases (vassal-litigator)` → шестерёнка свойств `Путь к папке` → **Edit property** → тип → выбрать `Text` (это и есть `RICH_TEXT`). Notion **сохранит существующие значения** как текстовые литералы (`file:///C:/...` останется строкой), не потеряет данные.
2. Альтернатива через MCP-tool `notion-update-data-source` -- передать команду `ALTER COLUMN "Путь к папке" TYPE RICH_TEXT`. Точный синтаксис -- зависит от текущей версии Notion API; UI-путь надёжнее.
3. После смены типа -- запусти `/vassal-litigator:sync-notion` на каком-нибудь существующем деле. Скилл **перезапишет** значение в новом формате (`%OneDrive%\<rel-path>`). Старые `file:///...`-значения постепенно вытеснятся при очередных синках каждого дела.
4. Принудительный backfill всех дел: пробежаться `/vassal-litigator:sync-notion` по каждой папке дела (или через batch-скрипт; для 10-20 дел вручную нормально).

**Проверка:** в Notion открой любую карточку Cases, в поле `Путь к папке` должно быть `%OneDrive%\...` (а не `file:///...`). Скопируй значение, вставь в адресную строку Explorer -- папка должна открыться (Windows раскроет `%OneDrive%`).

**Если что-то пошло не так:**
- Property заблокирована (есть формулы/relation, ссылающиеся на этот тип) -- их в этом property не должно быть, но если ругается -- через UI создай новое property `Путь к папке (текст)`, скопируй значения, удали старое, переименуй новое.
- На машине sync'а `$env:OneDrive` пуст -- `notion-sync` запишет абсолютный путь и выведет warning. Решение: установить OneDrive или работать через `%USERPROFILE%\OneDrive\...` (см. SKILL.md → «Формирование значения Cases.Путь к папке»).

### 6.2b -- создать базу `Counterparties` + добавить `Оппонент` RELATION в Cases

**Зачем:** до 6.2b глобальные профили оппонентов накапливались только локально в `$VASSAL_GLOBAL_DIR/counterparties/`. С 6.2b они дополнительно пушатся в Notion-базу `Counterparties` для дашборда «у меня N дел против ООО Х, вот его типовые доводы».

**Шаги:**

1. **Создай базу `Counterparties`** -- скопируй JSON из раздела 2 этого файла и выполни `notion-create-database`. Запиши `data_source_id`.

2. **Добавь `Оппонент` RELATION в Cases** -- через UI Notion: открой базу `Cases (vassal-litigator)` → правая часть таблицы → **+ New property** → тип `Relation` → выбрать `Counterparties (vassal-litigator)` → **Show on Counterparties** = ON (это создаёт обратную связь `Дела` автоматически) → название = `Оппонент`.

   Альтернатива через MCP: `notion-update-data-source` команда `ADD COLUMN "Оппонент" RELATION('<counterparties-data-source-id>')`.

3. **Обнови конфиг** `notion-config.yaml`:
   ```yaml
   notion:
     databases:
       counterparties: "<data-source-id из шага 1>"   # добавить
     fields_map:
       cases:
         opponent_relation: "Оппонент"                 # добавить
       counterparties:                                  # добавить весь блок
         title: "Организация"
         inn: "ИНН"
         ogrn: "ОГРН"
         slug: "slug"
         typical_arguments: "Типовые доводы"
         tactics: "Тактика"
         representatives: "Представители"
         cases_count: "Дел с ним"
         last_sync: "Last sync"
   ```

4. **Запусти `/vassal-litigator:sync-notion`** на любом деле с оппонентом. Скилл создаст запись в Counterparties и установит relation `Cases.Оппонент → Counterparties`. При синке каждого следующего дела -- профиль накапливается («Дел с ним» инкрементируется, оппонент по `slug` дедупится).

**Проверка:** в Notion открой созданную карточку Counterparties → справа должен быть блок `Дела` со ссылкой на карточку Cases этого дела. Если связи нет -- проверь, что в Cases.Оппонент стоит правильная relation (а не другая база).

**Если что-то пошло не так:**
- `Оппонент` RELATION не создалась с DUAL (обратная `Дела` не появилась в Counterparties) -- через UI на свойстве `Оппонент` в Cases поменяй настройку `Show on Counterparties` на ON.
- `notion-sync` не находит конфиг `notion.databases.counterparties` -- проверь, что обновил `notion-config.yaml` после миграции (шаг 3 выше).

### 6.2c -- дедуп профиля оппонента `inn-/noinn-` (только локально, миграция в Notion не нужна)

**Что изменилось:** `add-opponent` и `legal-review` теперь умеют детектировать «теневой дубль» (когда на одного оппонента в `$VASSAL_GLOBAL_DIR/counterparties/` есть и `inn-{ИНН}.md`, и `noinn-{slug}.md`) и предупреждают Сюзерена. Это **только правки в SKILL.md** -- никаких изменений в Notion-схеме не требуется.

**Что нужно от Сюзерена:** проверить, есть ли уже накопленные теневые дубли в `$VASSAL_GLOBAL_DIR/counterparties/`:
```powershell
Get-ChildItem "$env:VASSAL_GLOBAL_DIR\counterparties\" -Filter "noinn-*.md" | ForEach-Object {
  $slug = $_.BaseName -replace '^noinn-',''
  Write-Host "noinn-$slug -- проверь, нет ли inn-...md с тем же display_name во frontmatter"
}
```
Если найдены -- мёрджить вручную по инструкции из [skills/add-opponent/SKILL.md](../skills/add-opponent/SKILL.md) → «Дедуп оппонента: inn-/noinn- теневой дубль». После мёрджа `notion-sync` синканёт чистого канонического оппонента.

---

## 8. Расширения после MVP

В эту bootstrap-инструкцию можно дописать создание баз `Hearings`, `Deadlines`, `Templates` (см. [NOTION-INTEGRATION-PROPOSAL.md](../NOTION-INTEGRATION-PROPOSAL.md) §2). С этапа 6.2b обязательны `Cases` + `Judges` + `Counterparties`. Остальные -- зона будущих этапов.

При расширении конфиг расширяется аналогично:
```yaml
notion:
  databases:
    cases: "..."
    judges: "..."
    counterparties: "..."
    hearings: "..."        # новое в этапе 7+
    deadlines: "..."       # новое в этапе 7+
    templates: "..."       # новое в этапе 7+
```

И в `skills/notion-sync/SKILL.md` добавляются новые фазы upsert.
