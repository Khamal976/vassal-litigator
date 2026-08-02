# -*- coding: utf-8 -*-
"""Машинная проверка ссылочной целостности markdown внутри плагина.

Берёт каждую ссылку вида [текст](путь) во всех .md плагина, разрешает путь
относительно файла-источника и сообщает о несуществующих целях.

Зачем отдельная проверка. Пути до одного и того же файла из разных мест
пишутся по-разному: из `shared/` это `../skills/build-position/references/X.md`,
а из `skills/prepare-hearing/` — `../build-position/references/X.md`. Перепутать
их легко, а поймать нечем: битая относительная ссылка не ломает ни сборку
(`build-plugin.ps1` копирует папки целиком), ни рендеринг — она просто молча
ведёт в никуда, и скилл в бою не доходит до справочника.

Запуск:   python scripts/verify_links.py [корень]
Выход:    0 — битых нет; 1 — есть находки (или не найден корень).
"""
import os
import re
import sys

# Не наши файлы либо не входят в дистрибутив.
SKIP_DIRS = {'.git', 'dist', 'node_modules', '__pycache__', '.vassal'}
# Рабочие папки Сюзерена в корне репозитория — не часть плагина.
SKIP_PREFIXES = ('Результаты тестирования', 'Анти ИИ')
# Схемы, которые проверять нечем: цель вне файловой системы.
EXTERNAL = ('http://', 'https://', 'mailto:', 'ftp://', 'file:', 'tel:')

# [текст](путь) либо [текст](путь "title"). Вложенных скобок в тексте не ждём.
LINK_RE = re.compile(r'\[(?P<text>[^\]\n]*)\]\((?P<href>[^)\s]+)(?:\s+"[^"]*")?\)')

# Конвенция проекта: `файл.md:120` и `файл.md:1000-1006` — указатель на строку,
# а не часть пути. Хвост отбрасываем, проверяем сам файл.
LINE_ANCHOR_RE = re.compile(r':(\d+)(?:-\d+)?$')

# Что уезжает в дистрибутив (whitelist из scripts/build-plugin.ps1).
# Битая ссылка здесь — боевой дефект; вне этого списка — рабочие материалы.
SHIPPED = ('skills', 'shared', 'commands', 'scripts', '.claude-plugin',
           'README.md', 'CHANGELOG.md', 'LICENSE')


def is_shipped(relpath):
    head = relpath.replace('\\', '/').split('/', 1)[0]
    return head in SHIPPED


def unquote(path):
    """%20 и подобное в относительных путях — та же цель, что и с пробелом."""
    out, i = [], 0
    while i < len(path):
        if path[i] == '%' and i + 2 < len(path):
            try:
                out.append(chr(int(path[i + 1:i + 3], 16)))
                i += 3
                continue
            except ValueError:
                pass
        out.append(path[i])
        i += 1
    return ''.join(out)


CODE_SPAN_RE = re.compile(r'`[^`\n]*`')


def strip_code_spans(line):
    """Разметка ссылки внутри `обратных апострофов` — иллюстрация, а не ссылка.

    Заменяем содержимое пробелами, чтобы номера позиций не поехали.
    """
    return CODE_SPAN_RE.sub(lambda m: ' ' * len(m.group(0)), line)


def walk(root):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames
                       if d not in SKIP_DIRS and not d.startswith(SKIP_PREFIXES)]
        for name in sorted(filenames):
            if name.endswith('.md'):
                yield os.path.join(dirpath, name)


def check(root):
    bad, total, files = [], 0, 0
    for path in walk(root):
        files += 1
        with open(path, encoding='utf-8') as fh:
            fenced = False
            for num, raw in enumerate(fh, 1):
                if raw.lstrip().startswith('```'):
                    fenced = not fenced
                    continue
                if fenced:          # содержимое ``` — пример, а не ссылки
                    continue
                line = strip_code_spans(raw)
                for m in LINK_RE.finditer(line):
                    href = m.group('href')
                    if href.startswith(EXTERNAL) or href.startswith('#'):
                        continue
                    target = unquote(href.split('#', 1)[0])
                    if not target:          # ссылка только на якорь
                        continue
                    total += 1
                    base = os.path.dirname(path)
                    resolved = os.path.normpath(os.path.join(base, target))
                    if os.path.exists(resolved):
                        continue
                    # Путь, уходящий выше корня репозитория, файлом быть не может:
                    # это GitHub-относительная ссылка вида `../../releases`,
                    # которую разрешает хостинг, а не файловая система.
                    if os.path.relpath(resolved, root).startswith('..'):
                        continue
                    # Возможно, это `файл.md:120` — проверим файл без хвоста.
                    stripped = LINE_ANCHOR_RE.sub('', target)
                    if stripped != target and os.path.exists(
                            os.path.normpath(os.path.join(base, stripped))):
                        continue
                    bad.append((os.path.relpath(path, root), num,
                                m.group('text'), href))
    return files, total, bad


def main():
    root = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.abspath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
    if not os.path.isdir(root):
        print('Не найден корень: %s' % root)
        return 1

    files, total, bad = check(root)
    shipped = [b for b in bad if is_shipped(b[0])]
    other = [b for b in bad if not is_shipped(b[0])]

    print('=' * 70)
    print('Корень: %s' % root)
    print('Файлов .md: %d   внутренних ссылок: %d' % (files, total))
    print('Битых: %d — в дистрибутиве %d, в рабочих материалах %d'
          % (len(bad), len(shipped), len(other)))
    print('=' * 70)

    for title, items in (('В ДИСТРИБУТИВЕ (боевые)', shipped),
                         ('Вне дистрибутива (рабочие материалы)', other)):
        if not items:
            continue
        print('\n--- %s ---' % title)
        for src, num, text, href in items:
            print('\n%s:%d' % (src, num))
            print('  [%s](%s)' % (text[:60], href))

    if shipped:
        print('\nБИТЫХ ССЫЛОК В ДИСТРИБУТИВЕ: %d' % len(shipped))
    else:
        print('\nВ дистрибутиве битых ссылок нет.')
    # Проваливаемся только на дистрибутиве: рабочие материалы не блокируют.
    return 1 if shipped else 0


if __name__ == '__main__':
    sys.exit(main())
