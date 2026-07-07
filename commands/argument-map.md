---
description: Карта доводов сторон — таблица по узлам спора (две версии + DOCX)
---

# argument-map — Карта доводов сторон

Когда пользователь запускает эту команду с "$ARGUMENTS":

1. Прочитай скилл `skills/argument-map/SKILL.md` и следуй его инструкциям.
2. Если `$ARGUMENTS` содержит указания (к какому заседанию, на какие узлы делать упор, за кого работаем) — используй как вводную Сюзерена.
3. Убедись, что `.vassal/case.yaml` и `.vassal/index.yaml` существуют; индекс не пуст (иначе предложи `intake`).
4. Проверь наличие источников доводов: `.vassal/hearings/*-prep.md` (§3/§4), `.vassal/analysis/opponent-filing-*.md`, `.vassal/analysis/position-*`. Нет ни одного — предупреди, что столбец оппонента будет прогнозом (предложи `add-opponent` / `build-position`).
5. Выполни pipeline из SKILL.md: загрузка контекста (хуки revise-position / study-evidence) → сборка узлов + практика CasusLegal (Opus) → approve состава узлов → заполнение → apply (рабочая в `.vassal/` + чистая для суда в корне + `.docx`).
