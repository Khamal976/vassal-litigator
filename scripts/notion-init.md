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

## 1. Создание базы `Cases`

Через MCP-tool `notion-create-database`. Передать:

```json
{
  "title": "Cases (vassal-litigator)",
  "description": "Реестр всех дел, синхронизируется из локального .vassal/case.yaml каждого дела",
  "parent": { "type": "page_id", "page_id": "<id-родительской-страницы>" },
  "schema": "CREATE TABLE (\"Номер дела\" TITLE, \"Суд\" SELECT('АС Красноярского края':blue, 'АС Москвы':orange, 'АС СПб':green, 'СОЮ':gray, '3-й ААС':purple, 'АС МО':red), \"Наш клиент\" RICH_TEXT, \"Истец\" RICH_TEXT, \"Ответчик\" RICH_TEXT, \"Наша роль\" SELECT('истец':blue, 'ответчик':red, 'третье лицо':gray, 'заявитель':green, 'заинтересованное лицо':orange), \"Стадия\" SELECT('Досудебная':gray, '1 инстанция':blue, '1 инстанция (приостановлено)':yellow, 'Апелляция':orange, 'Кассация':red, 'Исполнение':green, 'Закрыто':default), \"Статус\" SELECT('active':blue, 'paused':yellow, 'closed':gray, 'won':green, 'lost':red) COMMENT 'Ручное поле -- не перезаписывается sync', \"Следующее заседание\" DATE, \"Судья\" RELATION('<judges-data-source-id>'), \"Путь к папке\" URL, \"Last sync\" DATE)"
}
```

**Важно:**
- `<id-родительской-страницы>` -- ID из шага 0 (для варианта А -- параметр `parent` можно опустить).
- `<judges-data-source-id>` -- появится **после** создания базы Judges (см. шаг 2). На этом шаге вместо relation создай заглушку: убери `\"Судья\" RELATION(...)` из CREATE TABLE и добавь её отдельно через `notion-update-data-source` после создания Judges.

Альтернативный порядок (рекомендуется): сначала создать Judges (шаг 2), получить её `data_source_id`, потом создать Cases уже с правильным relation.

После создания запиши `data_source_id` из `<data-source>` тега ответа -- это ID, который пойдёт в `notion-config.yaml: notion.databases.cases`.

---

## 2. Создание базы `Judges`

Через `notion-create-database`:

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

## 3. Заполнение конфига

### 3.1. Реши, где файл будет жить

**Вариант А -- одна машина (по умолчанию):** `~/.vassal/notion-config.yaml`. Никаких env vars не нужно.

**Вариант Б -- две и более машины с синком через облако (OneDrive/Dropbox/Yandex.Disk):** положи файл в синхронизируемую папку и укажи путь через `$VASSAL_CONFIG_DIR`. Типовая конфигурация на Windows:
```
C:\Users\{имя}\OneDrive\Документы\Claude Cowork\.vassal\notion-config.yaml
```
плюс на каждой машине:
```cmd
setx VASSAL_CONFIG_DIR "C:\Users\{имя}\OneDrive\Документы\Claude Cowork\.vassal"
```
(имя пользователя на каждой машине своё; путь до OneDrive-корня от него и зависит).

Это решает проблему: на разных Windows-машинах `~` резолвится в `C:\Users\kholv\` и `C:\Users\другой\` -- два разных места без синхронизации. Явный путь через env var обходит этот разрыв.

**То же относится к `$VASSAL_GLOBAL_DIR`** (путь к глобальной памяти `judges/` + `counterparties/`) -- логически парная переменная, обычно ставится в соседнюю подпапку синхронизируемого корня:
```cmd
setx VASSAL_GLOBAL_DIR "C:\Users\{имя}\OneDrive\Документы\Claude Cowork\.vassal-global"
```

### 3.2. Создай файл

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
    cases: "<data-source-id-из-шага-1>"
    judges: "<data-source-id-из-шага-2>"
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
```

**Опционально (для команд из нескольких юристов):**
```yaml
notion:
  owner: "Стригов Я. А."   # передаётся как property в обе базы для фильтрации в views
```

---

## 4. Проверка

Запусти `/vassal-litigator:sync-notion --dry-run` в каком-нибудь существующем деле:
- Скилл должен прочитать конфиг, прочитать `case.yaml`, собрать properties и **показать** их Сюзерену без upsert в Notion.
- Если Сюзерен видит в выводе ожидаемые поля -- bootstrap прошёл корректно.
- Запусти без `--dry-run` -- запись должна появиться в Notion.

---

## 5. Что делать, если bootstrap прошёл с ошибкой

**Базы созданы дважды (повторный запуск шагов 1-2):**
- Удалить дубликаты в Notion вручную.
- Обновить `data_source_id` в конфиге на актуальные.

**`relation` Cases→Judges не работает (была создана до Judges):**
- Через `notion-update-data-source` добавить колонку `Судья` типа `RELATION('<judges-data-source-id>')` в Cases.
- Если в Cases уже есть записи без relation -- следующий sync (для тех же дел) проставит relation автоматически.

**MCP не отвечает на create_database:**
- Проверить `/mcp` -- авторизован ли Notion MCP.
- Проверить, что у токена есть права создавать базы в выбранном parent.
- Альтернатива: создать базы вручную в UI Notion и выписать их `data_source_id` (открыть базу как полную страницу → URL вида `notion.so/{workspace}/{database-id}?v={view-id}`; через `notion-fetch` по этой URL получить data_source_id).

---

## 6. Расширения после MVP

В эту bootstrap-инструкцию можно дописать создание баз `Hearings`, `Counterparties`, `Deadlines`, `Templates` (см. [NOTION-INTEGRATION-PROPOSAL.md](../NOTION-INTEGRATION-PROPOSAL.md) §2). Для MVP -- только `Cases` + `Judges`. Расширение -- отдельный этап (не входит в этап 6 рефакторинга).

При расширении конфиг расширяется аналогично:
```yaml
notion:
  databases:
    cases: "..."
    judges: "..."
    counterparties: "..."   # новое
    deadlines: "..."        # новое
```

И в `skills/notion-sync/SKILL.md` добавляются новые фазы upsert.
