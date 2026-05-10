---
name: notion-sync
description: >
  Синхронизация метаданных дела и глобального профиля судьи в Notion (push, односторонне).
  Используй этот скилл, когда юрист говорит «обнови Notion», «синхронизируй с Notion»,
  «отправь в Notion», «обнови дашборд», «синк по делу в Notion», «push в Notion»,
  «обнови карточку дела в Notion», «обнови судью в Notion», «sync notion».
  Также используй автоматически (по хуку) после init-case, analyze-hearing, appeal,
  cassation -- по правилу из SKILL.md «Авто-триггеры».
---

# notion-sync -- Синхронизация с Notion

Push метаданных дела (`case.yaml`) и глобального профиля судьи в две базы Notion: `Cases` и `Judges`. Источник правды -- локальный (`.vassal/` дела + `$VASSAL_GLOBAL_DIR/judges/`); Notion получает односторонний push для дашборда и кросс-дельной видимости. Обратный синк не делается -- это сознательный архитектурный выбор (см. [NOTION-INTEGRATION-PROPOSAL.md](../../NOTION-INTEGRATION-PROPOSAL.md) §4).

## Ключевой принцип: Notion -- зеркало, не источник

> Источник правды -- `.vassal/` дела и `$VASSAL_GLOBAL_DIR/`. Notion -- одностороннее зеркало для удобства просмотра и кросс-дельной памяти.

Конфликты разрешаются просто: при upsert поля из локальной правды **перезаписывают** Notion-запись, **кроме** тех, что помечены в конфиге как `fields_manual_only` (например, `Статус` = won/lost -- проставляется юристом вручную в Notion и не затирается).

## Предварительные условия

- Дело инициализировано: `.vassal/case.yaml` существует.
- Notion-конфиг настроен: файл `$VASSAL_CONFIG_DIR/notion-config.yaml` существует, содержит ID баз `cases` и `judges` (см. шаблон в [scripts/notion-init.md](../../scripts/notion-init.md)). Путь резолвится по правилам из [shared/conventions.md](../../shared/conventions.md) → «Notion-слой» → «Конфигурация»: `$VASSAL_CONFIG_DIR` если задана, иначе `~/.vassal/`.
- Notion MCP-сервер подключён и аутентифицирован (проверка -- через `notion-search` или `notion-fetch`).
- Если конфига нет -- скилл **не падает**, а: (а) предупреждает Сюзерена; (б) предлагает запустить bootstrap по `scripts/notion-init.md`; (в) выходит без изменений.

## Алгоритм

### Фаза 0 -- Загрузка конфига и pre-flight

1. **Резолв пути конфига:**
   - Прочитай переменную окружения `VASSAL_CONFIG_DIR` (через `Bash` -- `echo $VASSAL_CONFIG_DIR` или `printenv VASSAL_CONFIG_DIR`).
   - Если задана и непустая -- путь конфига = `$VASSAL_CONFIG_DIR/notion-config.yaml`.
   - Иначе -- путь конфига = `~/.vassal/notion-config.yaml`.
2. Прочитай файл конфига. Если файла нет -- предупреди Сюзерена шаблоном:
   ```
   ВНИМАНИЕ. Notion-конфиг не настроен.
   Сделано: ничего, синк пропущен.
   Искал по пути: {фактически проверенный путь}
   Что нужно от Сюзерена: запустить bootstrap по scripts/notion-init.md
       (создать две базы Cases + Judges в Notion и записать их ID в файл конфига).
   После настройки -- повторно запустить /vassal-litigator:sync-notion.
   ```
   Завершиться без изменений (выход 0). **НЕ создавать пустой конфиг автоматически** -- Сюзерен должен решить, в каком workspace хранить.
3. Валидируй конфиг:
   - Обязательные поля: `notion.databases.cases` (ID), `notion.databases.judges` (ID).
   - Опциональные: `notion.databases.counterparties` (для будущего расширения), `notion.fields_manual_only`.
4. **Feature detection Notion MCP** (по паттерну `shared/conventions.md` → «Внешние зависимости и fallback»):
   - Попытка короткого `notion-search` с минимальным запросом для проверки авторизации.
   - Если MCP недоступен / не авторизован → graceful degradation: не падать, предупредить Сюзерена, отметить факт в `.vassal/notion-sync.log`, выйти без изменений.

### Фаза 1 -- Чтение локальных источников правды

4. Прочитай `.vassal/case.yaml` -- стороны, суд, судья, статус, следующее заседание, наш клиент.
5. Прочитай `.vassal/history.md` (последние 20 строк) -- для эвристики стадии (pending_appeal, completed и т.п.), если `case.status` не выставлен явно.
6. **Глобальный профиль судьи** (для базы `Judges`): по правилам слагов из [shared/conventions.md](../../shared/conventions.md) → «Глобальная память (кросс-дельная)»:
   - Разрезолви `$VASSAL_GLOBAL_DIR` (по умолчанию `~/.vassal-global/`).
   - Имя файла: `judges/{ФИО-slug}--{court-slug}.md` по `case.judge` и `case.court`.
   - Если файл существует -- прочитай frontmatter (`cases`, `hearings_total`, `last_updated`) и тело (разделы 1-7 с агрегированными наблюдениями).
   - Если файла нет -- в Notion создаётся/обновляется минимальная запись по судье (только ФИО + суд + связь с делом), без блоков «Стиль», «Паттерны», «Склонности».

### Фаза 2 -- Upsert в `Cases`

7. **Поиск существующей записи по `case.number`** через `notion-search` (внутри data source `cases`):
   - Запрос: `case.number` (точная строка, например «А33-12345/2026»).
   - Если найдена -- получи её `page_id` для update.
   - Если не найдена -- создай новую через `notion-create-pages`.
8. **Сборка properties** (имена -- из конфига `notion.fields_map.cases`, по умолчанию):

| Property | Источник | Notion-тип |
|---|---|---|
| `Номер дела` (title) | `case.number` (или `temp-{слаг}` если null) | TITLE |
| `Суд` | `case.court` | SELECT (auto-create option) |
| `Наш клиент` | `case.our_client` → `parties[party_id == our_client.party_id].short_name` | RICH_TEXT |
| `Истец` | `parties[role == "Истец"][0].short_name` | RICH_TEXT |
| `Ответчик` | `parties[role == "Ответчик"][0].short_name` | RICH_TEXT |
| `Наша роль` | роль `parties[party_id == our_client.party_id].role` | SELECT |
| `Стадия` | вывод по `case.status` (см. таблицу маппинга ниже) | SELECT |
| `Следующее заседание` | `case.next_hearing` | DATE |
| `Судья` | relation → запись в `Judges` (см. фазу 3) | RELATION |
| `Путь к папке` | абсолютный путь корня дела (через `file:///` URL для удобного клика) | URL |
| `Last sync` | now() ISO date | DATE |

   Маппинг `case.status` → Notion `Стадия`:
   - `active` → «1 инстанция»
   - `suspended` → «1 инстанция (приостановлено)»
   - `pending_appeal` → «Апелляция»
   - `pending_cassation` → «Кассация»
   - `completed` → «Исполнение»
   - `archived` → «Закрыто»

9. **`fields_manual_only`** -- из конфига (например, `Статус: won/lost/active`). Эти поля **не передаются** в Notion при upsert (читаются и игнорируются). Юрист правит их в Notion вручную.

10. Выполни upsert через `notion-create-pages` (для новой) или `notion-update-page` с `command: "update_properties"` (для существующей).

### Фаза 3 -- Upsert в `Judges` и связь с делом

11. **Только если `case.judge` не null:**
12. **Ключ дедупликации в `Judges`** -- комбинация `slug` (если глобальный профиль есть) ИЛИ `ФИО` + `Суд`. Поиск через `notion-search` в data source `judges`:
    - Запрос: `case.judge` (точная строка ФИО).
    - Из результатов выбери запись с совпадающим полем `Суд` = `case.court`. Если несколько -- предупреди Сюзерена и используй первую (по `Last sync` desc).
    - Если не найдена -- создай новую.
13. **Сборка properties** (имена -- из конфига `notion.fields_map.judges`, по умолчанию):

| Property | Источник | Notion-тип |
|---|---|---|
| `ФИО` (title) | `case.judge` | TITLE |
| `Суд` | `case.court` | RICH_TEXT (или SELECT) |
| `slug` | `slug` из глобального профиля (или собранный по правилам) | RICH_TEXT |
| `Стиль` | глобальный профиль § 1 «Общий стиль» -- сжать до 2-3 предложений | RICH_TEXT |
| `Паттерны` | глобальный профиль § 3 «Паттерны вопросов» + § 4 «Триггеры» -- сжать | RICH_TEXT |
| `Склонности` | глобальный профиль § 2 «Предпочтения в аргументации» + § 5 «Подход к доказательствам» -- сжать | RICH_TEXT |
| `Дел с ним` | количество в `cases:` глобального профиля (или 1 если только текущее) | NUMBER |
| `Last sync` | now() ISO date | DATE |

    **Если глобального профиля нет** -- `Стиль`, `Паттерны`, `Склонности` оставить пустыми (или заполнить меткой «Профиль не наполнен -- запусти analyze-hearing/draft-judgment»).

14. Upsert через `notion-create-pages` / `notion-update-page`.
15. **Свяжи запись `Cases` (из фазы 2) с записью `Judges`** через property `Судья` (RELATION). Если запись `Cases` уже была создана без relation -- сделай дополнительный update с заполненной relation.

### Фаза 4 -- Логирование и отчёт

16. **Запиши в `.vassal/notion-sync.log`**:
    ```
    [{ISO timestamp}] sync OK / FAIL
      cases: created/updated, page_id: <id>
      judges: created/updated, page_id: <id>, slug: <slug>
      errors (if any): <message>
    ```
    Файл аппенд-only, ротация не нужна (короткие записи).

17. **Запиши в `.vassal/history.md`** короткую запись:
    ```
    ### {ЧЧ:ММ} -- Синхронизация с Notion (notion-sync)
    - Cases: {created|updated}, page_id: <id>
    - Judges: {created|updated|skipped (нет судьи)}, page_id: <id>
    - Статус: OK / частичный сбой ({что упало})
    ```

18. **Покажи Сюзерену короткую сводку** (без избыточных деталей):
    ```
    Notion-синк выполнен:
      Cases   → дело {номер}: {created|updated}
      Judges  → судья {ФИО}: {created|updated|skipped}
    Записи доступны в workspace: {workspace URL из конфига или generic}
    ```

## Постусловия

Перед завершением `apply` сверься с чек-листом из [shared/conventions.md](../../shared/conventions.md) → «Постусловия скиллов» категория 4 (служебные). Минимум:

- Путь к Notion-конфигу разрезолвен (через `$VASSAL_CONFIG_DIR` или fallback `~/.vassal/`); конфиг прочитан и валиден ИЛИ скилл вышел с явным предупреждением Сюзерену (без изменений).
- Notion MCP проверен на доступность ИЛИ зафиксировано в логе как недоступный (без изменений).
- Если синк выполнен:
  - Запись в `Cases` создана/обновлена ровно одна (по dedup-ключу `case.number`).
  - Запись в `Judges` создана/обновлена ровно одна (если `case.judge` не null).
  - Relation `Cases.Судья → Judges` установлена.
  - Поля из `fields_manual_only` **не перезаписаны**.
  - `.vassal/notion-sync.log` обновлён.
  - `.vassal/history.md` обновлён.
- Если синк прерван -- частичные изменения в Notion помечены в `.vassal/notion-sync.log` с уровнем `PARTIAL`, чтобы при следующем запуске можно было докрутить.

## Конфигурация

Файл: `$VASSAL_CONFIG_DIR/notion-config.yaml` (по умолчанию `~/.vassal/notion-config.yaml`). Один на пользователя, не на дело. Правила резолва пути -- в [shared/conventions.md](../../shared/conventions.md) → «Notion-слой» → «Конфигурация».

Полный шаблон и описание полей -- в [scripts/notion-init.md](../../scripts/notion-init.md). Минимальный пример:

```yaml
notion:
  workspace_id: "your-workspace-id"
  databases:
    cases: "data-source-id-from-create-database"
    judges: "data-source-id-from-create-database"
  fields_manual_only:
    cases: ["Статус"]
  fields_map:
    # опционально -- если в Notion поля переименованы, указать соответствие
    cases:
      title: "Номер дела"
      court: "Суд"
      # ...
    judges:
      title: "ФИО"
      court: "Суд"
      # ...
```

**Токен Notion** -- через MCP-auth, в плагине не хранится. Если MCP не авторизован -- сообщение от MCP-сервера «требуется авторизация» Сюзерен видит через инфраструктуру Cowork; скилл воспринимает это как недоступную зависимость.

## Идемпотентность

- **Дедуп по `case.number`** -- основной ключ для `Cases`. При двух последовательных запусках на одно дело -- update, не дубль.
- **Дедуп по `slug`** -- основной для `Judges`. Поиск по `slug` имеет приоритет над поиском по ФИО+Суд (на случай переименования судьи или суда -- редкий, но возможный кейс).
- **Дело без номера** (`case.number == null`) -- временный ключ `temp-{уникальный slug}`. При появлении реального номера в `case.yaml` следующий sync обновит title, но запись в Notion **останется той же** -- дедуп по внутреннему vassal-litigator id (можно добавить отдельное hidden-поле `vassal_id` для жёсткой связки; в MVP -- по title).

## Авто-триггеры (хуки в других скиллах)

Скилл вызывается автоматически (как мягкая рекомендация) в конце:
- `init-case` -- сразу после создания дела, чтобы запись в Cases появилась с самого старта.
- `analyze-hearing` -- после apply, чтобы обновить судью (новые наблюдения) и `Следующее заседание`.
- `appeal` / `cassation` -- после apply, чтобы обновить `Стадия` (pending_appeal / pending_cassation) и `Last sync`.

Реализация хука в каждом из этих скиллов -- одна строка в финальной фазе:
```
(опционально) Предложи Сюзерену: «Синхронизировать с Notion? [/vassal-litigator:sync-notion]»
Если по пути `$VASSAL_CONFIG_DIR/notion-config.yaml` (или fallback `~/.vassal/notion-config.yaml` -- см. правила резолва) конфига нет -- НЕ предлагать (см. предусловия notion-sync).
```

Хуки **не блокирующие** -- скилл-инициатор завершается успешно, даже если Сюзерен отказался от sync или sync упал.

## Граничные случаи

- **Дело без судьи** (`case.judge == null`) → синкаются только `Cases`, `Judges` пропускается. Сообщение в логе: «Judges skipped: no judge in case.yaml».
- **Несколько судей** (коллегия в апелляции/кассации) → текущий MVP синкает только `case.judge` (первая инстанция). Расширение под коллегиальные составы -- отдельный тикет, не в этапе 6.
- **Notion rate limit** при первом массовом backfill из 50+ дел → пакетировать (sleep 1с между запросами); это сценарий не automated-sync, а отдельного скрипта `notion-backfill` (вне scope этапа 6).
- **Сетевая ошибка в середине sync** (Cases прошёл, Judges упал) → `notion-sync.log` фиксирует `PARTIAL: cases OK, judges FAIL ({reason})`; следующий запуск идемпотентно докрутит Judges + relation.
- **Опция `--private-case`** (NOTION-INTEGRATION-PROPOSAL.md §6) -- если в `case.yaml` есть поле `case.private: true` (зарезервировано на будущее), скилл **не синкает** это дело и явно сообщает Сюзерену. В MVP поле не используется -- если задано, скилл его уважает; если нет -- синк выполняется по умолчанию.
- **Команда из нескольких юристов на одной workspace** -- зона расширения (поле `Owner` в Cases, фильтрация). MVP однопользовательский; опционально в конфиге `notion.owner: "ФИО"` -- передаётся как property и используется фильтрами views.

## Маршрутизация моделей

- **Sonnet (основной поток)** -- чтение конфига, чтение `case.yaml`/`history.md`, сборка properties, вызов MCP. Это задачи структурирования, не глубокой аналитики.
- **Haiku** -- сжатие глобального профиля судьи в краткие текстовые блоки для Notion-properties (§ Стиль / Паттерны / Склонности): «дай 2-3 предложения по разделу X». Делегируется субагенту с `model: "haiku"`.
- **Opus** -- не используется. Если потребуется (например, для классификации `Стадии` по неполному `case.yaml`) -- отдельным субагентом, но в MVP не нужен.

## Что НЕ делает этот скилл

- **Не синкает приватные данные** -- тексты документов, позиции, аналитику, транскрипции, расчёты. Только метаданные дела и агрегированные паттерны судьи.
- **Не делает обратный синк (Notion → локально).** Если юрист правит Notion-запись -- эти правки **не приходят** в `case.yaml`. Это сознательный выбор: local-first архитектура, иначе конфликты разрешать слишком сложно. Pull (вручную, по запросу: «обнови по судье из Notion») -- зона будущего расширения, см. NOTION-INTEGRATION-PROPOSAL.md §4.
- **Не создаёт базы Notion** -- это разовая bootstrap-операция, выполняется по [scripts/notion-init.md](../../scripts/notion-init.md), не каждым sync.
- **Не валидирует схему Notion-баз** -- предполагается, что bootstrap выполнен корректно. Если поля переименованы -- маппинг через `fields_map` в конфиге.
- **Не синкает Counterparties** -- в MVP scope только Cases + Judges. Counterparties как Notion-база -- расширение (этап 7+); локальная глобальная память по оппонентам уже есть (`$VASSAL_GLOBAL_DIR/counterparties/`).
- **Не синкает Hearings, Deadlines, Templates** -- эти базы зарезервированы в [NOTION-INTEGRATION-PROPOSAL.md](../../NOTION-INTEGRATION-PROPOSAL.md) §2.2-2.6 для будущих этапов.
