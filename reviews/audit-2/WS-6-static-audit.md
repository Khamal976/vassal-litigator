# Аудит №2 — WS-6: Сплошная статика непротестированного — синтез

**Дата:** 2026-06-17
**Статус:** ✅ **WS-6 ЗАВЕРШЁН** — все 8 скиллов проаудированы (калибровка cassation+settlement + основной прогон 6 скиллов). Реестр **F6.1–F6.34**: 18 подтверждённых · 16 «можно лучше» · 2 отброшено · P0 нет. **Фиксы завершены (Волна 1 + Волна 2, 2026-06-17)** — все 18 подтверждённых + связанные P2/P3 обработаны; 5 коммитов на ветке `audit-2/structural-rework`. Дальше — WS-7 (доки).
**Метод:** вариант Б (D5) — параллельный workflow: карта контрактов → анализ по осям A–D + линза первого прогона + verify-before-assert → adversarial-проверка каждой находки → синтез
**Граница (D3):** правовой слой по существу не перепроверяем; ловим расхождения контрактов между артефактами, мёртвые поля, нарушения идемпотентности и verify-before-assert.

---

## 0. Что прогнано

| Батч | Скиллы | Прогон |
|---|---|---|
| **Калибровочный (этот)** | cassation (499 + 432 справочники), settlement (434 + 489 справочники) — два самых тяжёлых, ветвления `target` / `mode×stage` | run `wf_f494e07c-8cb`: 27 субагентов · ~2.3M токенов · 386 tool-вызовов · ~15.5 мин |
| **Основной ✅** | add-opponent · analyze-hearing · draft-judgment · update-index · catalog · notion-sync | run `wf_c7e77095-86d`: 43 субагента · ~3.4M токенов · ~29.5 мин |

Структура прогона: Фаза 1 — 3 агента (карта cassation + карта settlement + дайджест shared-контрактов и handoff-поверхности соседей, барьер). Фаза 2+3 — 4 слайса пайплайном (cassation: стандарт / ruling-appeals; settlement: мировое / отказ-признание), каждая находка сразу на adversarial-проверку (P0/P1 — 2 скептика, опровергают + сверяют якорь `файл:строка`).

---

## 1. Калибровочный вердикт

**Статистика:** 15 кандидатов → **11 подтверждённых · 4 «можно лучше» · 0 отброшено.**

**Моя ручная сверка якорей (5/5 точны):**
- F6.1 — [cassation/SKILL.md:357-366](../../skills/cassation/SKILL.md): да, под заголовком секции `ruling_settlement` (316) дублируются «стандартные» Просительная (357-360) и Приложения (362-366), а у самой стандартной секции (293) собственных просительной/приложений в листинге нет. ✅
- F6.3 — [cassation/SKILL.md:412](../../skills/cassation/SKILL.md): шаблон срока хардкодит «ст. 276 АПК — 2 месяца / ст. 376.1 ГПК — 3 месяца» без ветвления по `target`. ✅
- F6.2 — [cassation/SKILL.md:510-512](../../skills/cassation/SKILL.md): apply пишет только timeline / filed_date / status; `target`/`instance`/`deadline`/`_set_by`/`_set_date` — нет. ✅
- F6.7 — [settlement/SKILL.md:424](../../skills/settlement/SKILL.md): хардкод `in_progress=true`, ветки фазы-0-(в) с `confirmed_date` в apply нет (нюанс: `status` частично закрыт строкой 426 для agreement/withdrawal, но `confirmed_date` и `in_progress=false` не пишет ни apply, ни analyze-hearing). ✅
- F6.8 — [conventions.md:726](../../shared/conventions.md): зона verify-before-assert = legal-review/build-position/prepare-hearing/appeal/cassation/build-submission; settlement отсутствует. ✅

**Оценка метода:**
- **Формат годен** — находки конкретны, привязаны к `файл:строка`, действенны (есть эскиз фикса), граница правового слоя соблюдена во всех 15.
- **Сигнал высокий** — планка «дыра vs можно-лучше» держится; P1 — реальные риски дефектного документа / застывания состояния / потери срока.
- **Adversarial-слой работает, но мягко:** `rejected=0`, при этом 4 кандидата реклассифицированы в «можно лучше» (скептики корректируют severity, не штампуют). Для основного прогона — **усилить скептиков**: требовать активного поиска уже существующего механизма, закрывающего «дыру», и более жёсткого порога на P2/P3.
- **Перекрёстный дедуп нужен на синтезе:** F6.4 всплыл из двух слайсов (cassation/ruling-appeals + settlement/мировое) как одна проблема `court_ruling_id`. В основном прогоне поля-без-писателя всплывут из нескольких скиллов — синтез обязан склеивать.

**Решение:** метод валидирован, **рекомендую запускать основной прогон (6 скиллов)** с двумя твиками (злее скептики; явный дедуп-проход на синтезе). Карты cassation/settlement и дайджест shared переиспользуются.

---

## 2. Кластеры находок (это и есть план фиксов)

Фиксы делаем **после полного WS-6** (6 остальных скиллов), по кластерам — потому что C1/C3/C4 почти наверняка всплывут и в непрогнанных скиллах, и чинить системно дешевле, чем точечно по скиллу.

| Кластер | Суть | Находки | Почему системный |
|---|---|---|---|
| **C1 — Поле с владельцем/в схеме, но без писателя** | Поле объявлено в ownership-матрице / case-schema, но ни один apply-шаг его не пишет → на первом прогоне `null`, читатели деградируют | F6.2, F6.4, F6.7, F6.13 | Матрица владения и схема v6 росли быстрее, чем apply-шаги скиллов; та же дыра вероятна в notion-sync/update-index/analyze-hearing |
| **C2 — `target`/`mode`-условный текст захардкожен под дефолт** | Ветвящийся скилл выдаёт контент дефолтной ветки на не-дефолтном пути (структура, срок, норма) | F6.1, F6.3 | Любой скилл с `target`/`mode`-ветвлением (appeal? draft-judgment?) |
| **C3 — Пробел verify-before-assert** | Скилл пишет в подаваемый/значимый документ дословные суммы/реквизиты/цитаты без обязательной сверки и без блокировки `needs_manual_review` | F6.8 | Проверить draft-judgment (проект решения), analyze-hearing (замечания на протокол) — в зоне ли они |
| **C4 — Расхождение контракта между артефактами** | SKILL ↔ схема ↔ справочник ↔ OPEN-ITEMS говорят разное (норма, enum, маршрут) | F6.6, F6.9, F6.10, F6.12 | Дрейф документации; ловится в любом скилле |
| **C5 — Идемпотентность повторного прогона** | Повторный прогон в ту же дату молча перезаписывает продукт без supersedes/`-{ЧЧММ}` | F6.11 | Проверить, у всех ли document-producing скиллов есть коллизия имён |
| **C6 — Полнота предупреждений** | Асимметрия предупреждений о необратимых последствиях для клиента | F6.14 | Точечное |

---

## 3. Реестр находок WS-6 (калибровочный батч)

> ID по образцу §6 трекера. Класс — PLUGIN (все). Sev: P0 ломает первый прогон/порча состояния/потеря срока-права/дефектный документ · P1 неверный результат в типовом сценарии · P2 трение/edge · P3 косметика/доки. **«CBB»** = переведено скептиком в «можно лучше».

| ID | Sev | Ось | Скилл | Находка | Якорь |
|---|---|---|---|---|---|
| **F6.1** | P1 | A | cassation | Дублированные/осиротевшие «стандартные» Просительная+Приложения внутри секции `ruling_settlement` → риск дефектной просительной (отмена несуществующих решения/постановления) | [SKILL.md:344-366](../../skills/cassation/SKILL.md) |
| **F6.2** | P1 | B | cassation | apply не пишет `case.cassation.{target, instance, deadline, _set_by, _set_date}` → срок-предупреждение читает `null`; провенанс v6 не штампуется | [SKILL.md:510-512](../../skills/cassation/SKILL.md) |
| **F6.3** | P1 | первый прогон | cassation | Fallback-предупреждение о сроке хардкодит ст.276/2 мес — неверно для `ruling_settlement` (ст.141 ч.11, 1 мес); самый опасный по сроку путь | [SKILL.md:412](../../skills/cassation/SKILL.md) |
| **F6.4** | P2 | B | settlement→cassation | `case.settlement.court_ruling_id` в ownership settlement, читается cassation для `ruling_settlement`, но не пишется ни одним apply → оба указателя (`court_ruling_id`, `appealed_ruling_doc_id`) = null **(дедуп: всплыл из 2 слайсов)** | [settlement/SKILL.md:471](../../skills/settlement/SKILL.md) · [cassation/SKILL.md:92](../../skills/cassation/SKILL.md) |
| **F6.5** | P2 | B | cassation→build-submission | В корне нет рабочей `.md` с тегами `[doc-NNN]` (жалоба tag-free, единственный корневой `.md`) → резолв приложений в build-submission деградирует на fuzzy-добор | [build-submission/SKILL.md:43-45](../../skills/build-submission/SKILL.md) · [cassation/SKILL.md:390-393,500](../../skills/cassation/SKILL.md) |
| **F6.6** | P3 | C | cassation | `case.cassation.instance` enum закрыт на 2 арбитражных значения, а SKILL документирует ГПК-ветки (КСОЮ/СКГД) первоклассно; prep-фронтматтер использует 4 значения | [case-schema.yaml:352](../../shared/case-schema.yaml) · [cassation/SKILL.md:430](../../skills/cassation/SKILL.md) |
| **F6.7** | P1 | A | settlement | apply хардкодит `in_progress=true`, нет ветки фазы-0-(в): `confirmed_date`/`in_progress=false` не пишет ни settlement, ни заявленный сосед analyze-hearing → трек примирения не достигает терминала | [SKILL.md:423-428](../../skills/settlement/SKILL.md) |
| **F6.8** | P1 | verify-before-assert | settlement | settlement вне зоны verify-before-assert и без внутренней замены → подаваемый `.docx` (мировое, ходатайство) с дословными суммами/реквизитами/цитатами без сверки | [conventions.md:726](../../shared/conventions.md) |
| **F6.9** | P3 | A | settlement | Внутреннее расхождение нормы прекращения ИП: SKILL «ст. 43 ч. 1 п. 3 ФЗ-229», справочники+схема — «ч. 2 п. 3» (в тело документа не попадает → P3) | [SKILL.md:278](../../skills/settlement/SKILL.md) |
| **F6.10** | P2 | B | settlement | Анти-триггер маршрутизирует прочие основания ст.150 АПК в prepare-hearing, где такого режима нет (противоречит OPEN-ITEMS B.5 / ARCHITECTURE / собств. справочнику) | [SKILL.md:10-11](../../skills/settlement/SKILL.md) |
| **F6.11** | P2·CBB | A | cassation | Корневая `.md` жалобы без supersedes/коллизии даты → повторный прогон в ту же дату молча перезаписывает (для prep-артефакта `-{ЧЧММ}` есть, для `.md` — нет) | [SKILL.md:390-393](../../skills/cassation/SKILL.md) |
| **F6.12** | P3·CBB | B | cassation | Схема приписывает маршрут `ruling_settlement` ст.141 **ч.9**, SKILL/справочник — ст.141 **ч.11** (ч.9 = немедленное исполнение) | [case-schema.yaml:333](../../shared/case-schema.yaml) |
| **F6.13** | P3·CBB | D | settlement | `case.settlement.filed_date` в ownership, но не пишется ни одним документированным путём (кластер C1) | [SKILL.md:565](../../skills/settlement/SKILL.md) |
| **F6.14** | P3·CBB | A | settlement | Асимметрия предупреждений: для `admission` нет user-facing предупреждения о необратимости решения против клиента (для `withdrawal` — есть в теле документа) | [SKILL.md:350-362](../../skills/settlement/SKILL.md) |

**Severity-итог калибровочного батча:** P1 ×5 · P2 ×4 · P3 ×5. P0 — нет.

### Развёрнуто — P1 (действенные, в фиксы первой волны)

**F6.1 (P1, ось A, cassation).** Под `#### Структура для target='ruling_settlement' -- особая` ([SKILL.md:316](../../skills/cassation/SKILL.md)) идут ДВА конфликтующих блока «Просительная часть» и ДВА «Приложения»: верные для этого target (344-355: отменить определение об утверждении мирового; приложения = копия определения + копия мирового) и сразу за ними — СТАНДАРТНЫЕ (357-366: «Решение и/или постановление отменить», «Копии обжалуемых судебных актов»), физически оторванные от своей секции (293, у которой их в листинге нет). SKILL на [строке 92](../../skills/cassation/SKILL.md) прямо говорит, что для `ruling_settlement` решение/постановление **не существуют**. → генератор по особому пути может выдать просительную с отменой несуществующего акта. **Фикс:** перенести 357-366 в стандартную секцию (после 314), в `ruling_settlement` оставить только её 344-355; разделитель между структурами.

**F6.2 (P1, ось B, cassation).** Шаг 25 ([SKILL.md:510-512](../../skills/cassation/SKILL.md)) — единственный apply в `case.yaml` — пишет только `timeline`, `filed_date` (условно), `status: pending_cassation`. НЕ пишет `target`/`instance`/`deadline`/`origin`/`_set_by`/`_set_date`, хотя схема ([case-schema.yaml:327-352](../../shared/case-schema.yaml)) и матрица владения ([conventions.md:569](../../shared/conventions.md)) объявляют cassation писателем, а скилл их вычисляет. `deadline` по всему SKILL только читается (201, 414, 431) → самое громкое срок-предупреждение (408-414) читает `null`. **Фикс:** в шаг 25 добавить запись target/instance/deadline/origin=computed/_set_by/_set_date (+ appealed_ruling_doc_id для target≠judgment_with_appeal).

**F6.3 (P1, первый прогон, cassation).** Шаблон graceful degradation ([SKILL.md:412](../../skills/cassation/SKILL.md)) безусловно цитирует «ст. 276 АПК — 2 мес / ст. 376.1 ГПК — 3 мес». Для `ruling_settlement` срок — 1 месяц по ст.141 ч.11 (сам SKILL: 35, 76, 88, 328). Самый короткий срок + самое критичное сообщение («пропуск — утрата права»). **Фикс:** ветвить «Срок (КРИТИЧНО)» по `target` (или вычислять подпись из target, не хардкодить).

**F6.7 (P1, ось A, settlement).** Фаза 6 apply ([SKILL.md:423-428](../../skills/settlement/SKILL.md)) хардкодит `in_progress=true` + `{mode, initiator, stage, draft_date}`; `confirmed_date` не упомянут, ветки фазы-0-(в) ([SKILL.md:76](../../skills/settlement/SKILL.md): «ставим confirmed_date и финальный статус») в apply нет. SKILL многократно (451, 472, 514, 565-569) делегирует простановку `confirmed_date`/финального статуса в analyze-hearing — но [analyze-hearing/SKILL.md](../../skills/analyze-hearing/SKILL.md) про settlement/confirmed_date не знает (grep=0). → типовой «суд утвердил мировое» оставляет дело навсегда `in_progress=true`, `confirmed_date=null`. **Фикс:** ввести в шаг 36 явную ветку завершения (`confirmed_date`, `in_progress=false`, финальный статус); либо реально реализовать запись в analyze-hearing, либо снять обещание делегирования.

**F6.8 (P1, verify-before-assert, settlement).** [conventions.md:726](../../shared/conventions.md) не включает settlement в зону; grep по `skills/settlement/` на verify-before-assert/needs_manual_review = 0. Между тем settlement пишет в подаваемый документ суммы цифрами+прописью и банковские реквизиты (terms-checklist.md:71-73, §8.2), дословные цитаты определений ВС (SKILL.md:313-314; case-law.md). → риск переноса непроверенной суммы/реквизита/цитаты из зеркала низкого качества в текст мирового/ходатайства. **Фикс:** включить settlement в зону (conventions.md:726) + блок сверки в фазы 1/4 по образцу cassation (110, 179); зеркало `needs_manual_review:true` нельзя как источник дословных реквизитов.

### Кратко — P2/P3

- **F6.4 (P2):** см. кластер C1. Фикс — один из: settlement пишет `court_ruling_id` при confirmed_date; ИЛИ cassation резолвит определение по индексу и пишет `appealed_ruling_doc_id`; ИЛИ явный fallback в cassation:92.
- **F6.5 (P2):** cassation производит один корневой tag-free `.md`; рабочая версия с `[doc-NNN]` живёт только в prep §7, который build-submission не автодетектит. Фикс — cassation сохраняет рабочую копию с тегами, ИЛИ build-submission указывает prep §7 источником.
- **F6.6 (P3):** расширить enum `instance` до 4 (окружной/СИП | КСОЮ | СКЭС | СКГД) или зафиксировать в схеме ГПК-поведение; синхронизировать с prep:430.
- **F6.9 (P3):** SKILL.md:278 → «ч. 2 п. 3» (как terms-checklist:216, legal-basis:77/265, схема:283).
- **F6.10 (P2):** привести скобку SKILL.md:11 «(это prepare-hearing)» к реальности (нет такого режима; OPEN-ITEMS B.5) — формулировка без обещания готового режима; выровнять с legal-basis.md:125.
- **F6.11 (P2·CBB):** шаг 21 — суффикс `-{ЧЧММ}`/`(2)` при коллизии даты + supersedes (как prep, 422); `.docx` защищён `_v2`, а `.md` нет.
- **F6.12 (P3·CBB):** комментарий case-schema.yaml:333 → ст.141 ч.11 (маршрут), ч.9 — немедленное исполнение.
- **F6.13 (P3·CBB):** см. C1; `filed_date` без писателя — добавить писателя или снять из активного ownership.
- **F6.14 (P3·CBB):** симметрично withdrawal — предупреждение для `admission` (необратимость решения против клиента) в секцию документа после 357 и/или Preview п.27.

---

## 4. Основной прогон — реестр (6 скиллов)

> run `wf_c7e77095-86d`. Злее скептики (обязаны найти уже существующий механизм + строже порог P2/P3) → **22 кандидата: 8 подтверждено · 12 «можно лучше» · 2 отброшено** (в калибровке 0 отброшено — фильтр заработал). Осечка: карта контрактов `update-index` не вернулась (parallel[3]) — на анализ не повлияло (агент читал файлы сам, дал находки).

| ID | Sev | Ось | Скилл | Находка | Якорь |
|---|---|---|---|---|---|
| **F6.15** | P1 | B | add-opponent | `duplicate_copies` объявлен за скиллом (схема+conventions), но apply не пишет и нет dedup-гейта по content_hash → дубль-запись или потеря файла, когда оппонент прикладывает уже имеющийся документ **[C1/C4]** | [SKILL.md:83-86,230](../../skills/add-opponent/SKILL.md) |
| **F6.16** | P2 | A | add-opponent | `next_bundle_id` не инкрементируется в apply (только `next_id`) → коллизия id бандлов; то же в add-evidence **[C5]** | [SKILL.md:86](../../skills/add-opponent/SKILL.md) |
| **F6.17** | P1 | B | analyze-hearing | НЕ пишет `settlement.confirmed_date` / `status=settled\|withdrawn` / `court_ruling_id` при утверждении судом в заседании — хотя схема+матрица+решение Сюзерена назначают его писателем **[C1; чинит F6.7]** | [SKILL.md:136-164](../../skills/analyze-hearing/SKILL.md) |
| **F6.18** | P1 | B | catalog | Колоночная спека таблицы без колонки **ID (doc-id)** — нарушает постусловие conventions.md:493 и контракт двойных ссылок conventions.md:511 | [SKILL.md:43-54](../../skills/catalog/SKILL.md) |
| **F6.19** | P1 | первый прогон | catalog | Нет feature-detection и fallback на `.md` при недоступности xlsx/openpyxl → **ломает первый прогон** в Cowork (sudo/apt нет); conventions.md:606 предписывает fallback | [SKILL.md:39](../../skills/catalog/SKILL.md) |
| **F6.20** | P1 | verify-before-assert | draft-judgment | Пишет дословные суммы/ИНН/ОГРН/формулы процентов в резолютивную без сверки по зеркалу и без блока `needs_manual_review`; вне зоны conventions.md:726 **[C3]** | [SKILL.md:245-250,304-306](../../skills/draft-judgment/SKILL.md) |
| **F6.21** | P1 | C | notion-sync | Маппинг `status`→Notion «Стадия» не покрывает `settled/withdrawn/pending_settlement` → после самого частого терминала дела (мировое/прекращение) стадия не определена / импровизируется | [SKILL.md:90-96](../../skills/notion-sync/SKILL.md) |
| **F6.22** | P1 | B | update-index | Детект устаревших зеркал по дате/mtime, а контракт (conventions.md:537-540, index-schema.yaml:62, ocr.md:97) — по `content_hash`; на OneDrive mtime недостоверен → правка файла не детектится, скиллы читают замороженный OCR-текст **[verify-by-fact]** | [SKILL.md:37,42,63](../../skills/update-index/SKILL.md) |
| **F6.23** | P2·CBB | B | add-opponent | Нет обязательной секции «Постусловия» (conventions.md:448) **[C4]** | [SKILL.md:226-231](../../skills/add-opponent/SKILL.md) |
| **F6.24** | P2·CBB | B | analyze-hearing | Не пишет `appeal/cassation.hearing_date` и `ruling_date` после заседания проверочной инстанции **[C1]** | [SKILL.md:123-127](../../skills/analyze-hearing/SKILL.md) |
| **F6.25** | P2·CBB | verify-before-assert | analyze-hearing | Замечания на протокол из цитат транскрипции без обязательной сверки **[C3]** | [SKILL.md:111-114](../../skills/analyze-hearing/SKILL.md) |
| **F6.26** | P2·CBB | B | analyze-hearing | Не проставляет `next_hearing_source` при записи даты следующего заседания **[C4]** | [SKILL.md:125-126](../../skills/analyze-hearing/SKILL.md) |
| **F6.27** | P2·CBB | A | analyze-hearing | Нет секции «Постусловия» (Категория 2) **[C4]** | [SKILL.md:136-164](../../skills/analyze-hearing/SKILL.md) |
| **F6.28** | P2·CBB | A | catalog | Нет секции «Постусловия» (conventions.md:448) **[C4]** | [SKILL.md:62-80](../../skills/catalog/SKILL.md) |
| **F6.29** | P2·CBB | первый прогон | catalog | Перезапись `.xlsx` не обрабатывает Excel-lock / OneDrive (в отличие от закалённого `.docx`→`_v2`) **[C5/env]** | [SKILL.md:80](../../skills/catalog/SKILL.md) |
| **F6.30** | P2·CBB | A | draft-judgment | Проект решения мандатно несёт теги `[doc-NNN]` в мотивировочной — человеко-обращённый продукт, теги недопустимы (conventions.md:516), шага очистки нет **[родственник F4.12]** | [SKILL.md:122](../../skills/draft-judgment/SKILL.md) |
| **F6.31** | P1·CBB | C | notion-sync | Колонки `Cases.Истец/Ответчик` захардкожены под исковое → для банкротных дел пусты **[C2]** | [SKILL.md:80-81](../../skills/notion-sync/SKILL.md) |
| **F6.32** | P2·CBB | B | notion-sync | `add-opponent` заявлен авто-триггером синка, но хука в нём нет и в conventions не значится **[C4]** | [SKILL.md:323](../../skills/notion-sync/SKILL.md) |
| **F6.33** | P3·CBB | A | notion-sync | Дублирование номера шага «4» (Фаза 0 и Фаза 1) | [SKILL.md:53](../../skills/notion-sync/SKILL.md) |
| **F6.34** | P3·CBB | D | update-index | `mirror_stale` не сбрасывается в `false` при пересоздании зеркала (Шаг 15) — расхождение с conventions.md:540; поле без писателя `true` **[C1]** | [SKILL.md:103](../../skills/update-index/SKILL.md) |

**Отброшено скептиками (для протокола):** (1) add-opponent — экспресс-анализ оппонента без verify-before-assert: закрыто тремя слоями (глоб. профиль пишет паттерны, не суммы — conventions.md:359-360; OCR-гейт на приёме; downstream-гейт подаваемого документа). (2) catalog — отчёт по `structural` читает несуществующее поле: закрыто жёсткой связкой `structural ⇒ needs_manual_review:true` (ocr.md:112,164), а поле есть в индексе и грузится.

---

## 5. Консолидированные кластеры (оба прогона) — это и есть план фиксов

| Кластер | Суть | Находки (оба прогона) |
|---|---|---|
| **C1 — поле с владельцем/в схеме, но без писателя** ⭐ самый системный | Поле объявлено в case-schema v6 / матрице владения, но ни один apply не пишет → на 1-м прогоне `null` | F6.2, F6.4, **F6.7↔F6.17** (связка: пишет analyze-hearing), F6.13, F6.15, F6.24, F6.34 |
| **C3 — пробел verify-before-assert** | Скилл пишет в значимый документ дословные суммы/реквизиты/цитаты без сверки и без блокировки `needs_manual_review` | F6.8 (settlement), F6.20 (draft-judgment), F6.25 (analyze-hearing замечания) |
| **C2 — условный текст/колонки захардкожены под исковое** | Не-дефолтная ветка (банкротство, ruling_settlement) получает дефолтный контент | F6.1, F6.3, F6.31 |
| **C4 — расхождение контракта / недостающие секции** | SKILL ↔ схема ↔ справочник ↔ conventions расходятся; «Постусловия» отсутствуют в 3 скиллах | F6.6, F6.9, F6.10, F6.12, F6.18, F6.21, F6.23, F6.26, F6.27, F6.28, F6.32, F6.33 |
| **C5 — идемпотентность повторного прогона** | Повтор в ту же дату перезаписывает продукт; счётчики не инкрементируются | F6.11, F6.16, F6.29 |
| **C6 — первый прогон / env-закалка** | Ломается на первом прогоне в Cowork (нет fallback, mtime-шум OneDrive) | F6.19 ⚠ (ломает прогон), F6.22, F6.29 |
| **C7 — утечка тегов в подаваемый/человеческий документ** | `[doc-NNN]` попадает туда, где их быть не должно | F6.30 (родственник F4.12) |

**Severity-итог WS-6 (18 подтверждённых):** P1 ×12 · P2 ×4 · P3 ×2 · P0 нет.

---

## 6. Дорожная карта фиксов (chunks, approve-гейт по каждому — паттерн WS-1..5)

**Волна 1 (Chunk A–F) ✅ ЗАВЕРШЕНА 2026-06-17 — P1 + связанные P2/P3:**
- **Chunk A — C1 «поля без писателя» ✅ ЗАКРЫТ 2026-06-17** (центральный; схему НЕ меняли — приведение скиллов к уже зафиксированному контракту v6): `analyze-hearing` записывает итоги заседания (`settlement.confirmed_date`/`status`/`court_ruling_id`; `appeal/cassation.hearing_date`/`ruling_date`/`result`; `next_hearing_source` — F6.17, F6.4, F6.24, F6.26, чинит F6.7) + `cassation` дописывает расчётные `target/instance/deadline/origin/_set_by/_set_date/appealed_ruling_doc_id` (F6.2, F6.4) + `settlement` apply путь-зависим, реально пишет `confirmed_date/in_progress=false/status` + `filed_date` (F6.7, F6.13) + `add-opponent` дедуп по `content_hash`→`duplicate_copies` + `next_bundle_id` (F6.15, F6.16) + `update-index` сброс `mirror_stale=false` (F6.34).
- **Chunk B — C3 verify-before-assert ✅ ЗАКРЫТ 2026-06-17:** `settlement` + `draft-judgment` + `analyze-hearing` (замечания) добавлены в зону conventions.md:726; блоки сверки сумм/реквизитов/цитат в их SKILL зеркалят эталон prepare-hearing:335 (F6.8, F6.20, F6.25).
- **Chunk C — catalog ✅ ЗАКРЫТ 2026-06-17:** fallback `.xlsx`→`.md` (F6.19) + колонка ID (F6.18) + Excel-lock→`_v2` (F6.29) + секция «Постусловия» (F6.28).
- **Chunk D — update-index ✅ ЗАКРЫТ 2026-06-17:** детект устаревших зеркал по `content_hash`, не mtime (F6.22).
- **Chunk E — notion-sync ✅ ЗАКРЫТ 2026-06-17:** маппинг `status` +settled/withdrawn/pending_settlement (F6.21) + банкротные колонки → прочерк (F6.31) + реализован Notion-хук в add-opponent (F6.32) + renumber дубля шага (F6.33).
- **Chunk F — cassation документ ✅ ЗАКРЫТ 2026-06-17:** перенос осиротевших просительной/приложений в стандартную секцию (F6.1) + срок-предупреждение по `target` (F6.3) + рабочий `[doc-NNN]`-источник = prep §7 + ссылка в build-submission (F6.5) + коллизия `.md` той же даты → `-{ЧЧММ}`/supersedes (F6.11) + комментарий схемы ст.141 ч.11 (F6.12).

**Волна 2 — P2/P3 косметика и доки ✅ ЗАВЕРШЕНА 2026-06-17:** F6.6 (enum instance +КСОЮ/СКГД), F6.9 (ст.43 ч.2 ФЗ-229), F6.10 (анти-триггер ст.150 → честная формулировка), F6.14 (предупреждение о последствиях admission), F6.23 + F6.27 (секции «Постусловия»), F6.30 (теги [doc-NNN] только в рабочей версии проекта решения). F6.26 закрыт в Chunk A.

**Граница:** правовой слой не переписываем; нормы — процесс B.3 (2026-11-30). После фиксов — WS-7 (доки, F7.1 счётчик скиллов→17) → WS-8 (Notion).
