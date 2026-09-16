# -*- coding: utf-8 -*-
"""Снимок СТАДИИ сайтов, у которых показателей ещё нет.

Почему отдельно от метрик. У этих сайтов нет либо домена, либо накопленных
наблюдений. Положить их в таблицу метрик значит напечатать пустоту как
показатели — ровно та ловушка, за которую ферма уже платила: доля по шести
наблюдениям дала 100 баллов и подняла индекс падающего сайта. Пока измерять
нечего, доска обязана говорить СТАДИЮ, а не показатели.

ДВА состояния, а не одно. До 15.09.2026 здесь был один смысл — «строится».
15 и 16 сентября batterycross.com и keepsuntil.com вышли в свет, и прежний
вводный абзац доски («ни домена в работе, ни Search Console, ни единого
визита») стал ложью на выложенной странице. Запуск НЕ делает сайт измеримым:
Google отдаёт первые сутки с задержкой, а до порога наблюдений (MIN_SESSIONS
на доске — 30) от них всё равно нельзя вывести ни доли, ни балла. Поэтому
состояний три: `building` — не опубликован; `launched` — опубликован, мерить
пока нечего; и третье, «измеряется», живёт НЕ здесь, а в
build_web_board.SITES. Ключ обязан быть ровно в одном из двух списков — это
стережёт гейт доски «сайт объявлен ровно один раз».

Почему снимком, а не на лету. Доска собирается в CI, где исходников сайтов
нет — у каждого сайта свой репозиторий. Значит числа снимаются здесь, на
машине, где эти каталоги есть, и кладутся в `data/pipeline.json` вместе с
ДАТОЙ съёмки. Доска печатает дату рядом с числами: снимок, выданный за
сегодняшнее состояние, — это ложь, которую никто не заметит.

Запуск:  python pipeline.py
"""
import ast
import io
import json
import os
import re
import sys
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))


def _find_root(start: str) -> str:
    """Найти корень НАПРАВЛЕНИЯ, а не каталог `_template`.

    Прежний поиск искал сам `_template` вверх по дереву. Он был верен ровно
    пока все ещё не запущенные сайты лежали ВНУТРИ него. 15–16.09.2026
    batterycross и keepsuntil уехали в собственные репозитории
    (`web-properties/<key>/`), а `_template/` остался — ради districtbyzip.
    Поэтому поиск по-прежнему УДАВАЛСЯ, и снимок объявил бы два живых сайта
    «каталога нет», то есть, по своему же комментарию, «не смотрели».
    Ищем корень направления (в нём лежат и REGISTRY.md, и `_template`), а
    каталог сайта разбираем отдельно — он бывает в двух местах.
    """
    d = os.path.abspath(start)
    for _ in range(6):
        if (os.path.isfile(os.path.join(d, "REGISTRY.md"))
                and os.path.isdir(os.path.join(d, "_template"))):
            return d
        up = os.path.dirname(d)
        if up == d:
            break
        d = up
    return os.path.abspath(os.path.join(start, "..", ".."))


ROOT = _find_root(HERE)
OUT = os.path.join(HERE, "data", "pipeline.json")

# Сколько суток Google копит, прежде чем отдать первые сутки в Search Console.
# Не догадка: бот тянет ряд до ВЧЕРА, а правый край у обоих живых сайтов
# отстаёт ещё на двое суток. Дата, посчитанная отсюда, печатается как
# ОЖИДАНИЕ и подписана словом «не раньше».
SC_LAG_DAYS = 3

# Что известно НЕ из кода и потому объявлено с причиной.
# Даты домена и запуска — из REGISTRY.md (пп. 50, 77, 79, 80), НЕ из головы.
# Прежнее «2026-09-01» у всех трёх было комментарием, пережившим факт на две
# недели: возраст домена — условие рекламной сети, и занижение на 14 суток
# сдвигает ожидание порога.
# Search Console: состояние проверено запросом к DNS 16.09.2026 (TXT
# google-site-verification), а не взято со слов.
DECLARED = {
    "batterycross": {
        "name": "BatteryCross",
        "host": "batterycross.com",
        "niche": "Замены элементов питания: что физически подойдёт вместо снятого",
        "domain": "2026-09-15",
        "launched": "2026-09-15",
        "design": "промышленный каталог — применён",
        "design_done": True,
        "sc": "владение подтверждено TXT-записью (проверено в DNS 16.09.2026)",
    },
    "keepsuntil": {
        "name": "KeepsUntil",
        "host": "keepsuntil.com",
        "niche": "Сроки хранения еды по данным USDA FoodKeeper",
        "domain": "2026-09-15",
        "launched": "2026-09-16",
        "design": "дата, а не срок — применён",
        "design_done": True,
        "sc": "владение подтверждено TXT-записью, карта принята — 326 адресов",
    },
    "districtbyzip": {
        "name": "DistrictByZip",
        "host": "districtbyzip.com",
        "niche": "Школьные округа по почтовому индексу, отдельно для K-8 и 9-12",
        "domain": None,            # домен НЕ куплен — это не дата, это пусто
        "launched": None,
        "design": "счётное поле — ВЫБРАН, но к сайту не применён",
        "design_done": False,
        "sc": None,
    },
}

# Что мешает ЗАПУСКУ — только у тех, кто ещё не запущен.
BLOCKERS_LAUNCH = [
    "домен не куплен",
    "нет идентификатора издателя AdSense — реклама стоит заглушками",
    "облик выбран, но к сайту не применён",
]
# Что мешает ИЗМЕРЕНИЮ — у тех, кто уже запущен. Это ДРУГОЙ список: печатать
# запущенному сайту «что мешает запуску» значит врать о нём в прошедшем
# времени. Перечислено пообъектно и с проверяемой причиной.
BLOCKERS_MEASURE = {
    "batterycross": [
        "GA4 не подключён: счётчика на страницах нет, и гейт сайта "
        "(gates.py:598) краснеет на любом счётчике, пока /privacy/ говорит "
        "«runs no analytics». Порядок обязателен и необратим по смыслу: "
        "сначала политика, потом счётчик, потом ресурс GA4",
        "служебному аккаунту board-fetch@bilingoplus-board.iam.gserviceaccount.com "
        "доступ к ресурсу Search Console не выдан (нужен Full: на Restricted "
        "отказывает URL Inspection)",
        "www.batterycross.com не отвечает (проверено 16.09.2026); на сбор "
        "чисел не влияет — ресурс доменный, — но половина ссылок извне "
        "придёт именно туда",
    ],
    "keepsuntil": [
        "GA4 не подключён: счётчика на страницах нет, и гейт сайта "
        "(gates.py:2540) краснеет на любом счётчике, пока /privacy/ отрицает "
        "аналитику. Порядок обязателен: сначала политика, потом счётчик, "
        "потом ресурс GA4",
        "служебному аккаунту board-fetch@bilingoplus-board.iam.gserviceaccount.com "
        "доступ к ресурсу Search Console не выдан (нужен Full)",
    ],
}


def _count_files(root, ext=".html"):
    n = 0
    for _base, _dirs, files in os.walk(root):
        n += sum(1 for f in files if f.endswith(ext))
    return n


def _count_sitemap(root):
    """Сколько адресов сайт ОТДАЁТ Google. Это не число файлов.

    Считали `.html` в `dist` и печатали как «страниц». У batterycross файлов
    321, а в карте сайта 153: 145 из них — виджеты `/embed/`, намеренно
    закрытые от выдачи. Разница вдвое, и печаталось большее число рядом со
    словом «страниц» — то есть будущий знаменатель доли индексации.
    """
    p = os.path.join(root, "dist", "sitemap.xml")
    if not os.path.isfile(p):
        return None
    return len(re.findall(r"<loc>", io.open(p, encoding="utf-8").read()))


def _site_root(key):
    """Каталог сайта: своя папка направления ИЛИ `_template/<key>`."""
    for cand in (os.path.join(ROOT, key), os.path.join(ROOT, "_template", key)):
        if os.path.isdir(cand):
            return cand
    return None


def _const(path, name):
    """Достать константу из исходника, НЕ импортируя его.

    Импорт запустил бы генератор сайта со всеми его побочными действиями, а
    нам нужно одно число. `ast` читает то же самое и ничего не выполняет.
    Берётся ПОСЛЕДНЕЕ присваивание: в gates.py есть более ранние упоминания
    имени, и первое совпадение вернуло бы не ту величину.
    """
    try:
        tree = ast.parse(io.open(path, encoding="utf-8").read())
    except (OSError, SyntaxError):
        return None
    found = None
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == name:
                    try:
                        found = ast.literal_eval(node.value)
                    except ValueError:
                        return None
    return found


def snapshot():
    today = date.today()
    out = {"taken": today.isoformat(), "sites": []}
    for key, dec in DECLARED.items():
        launched = dec.get("launched")
        rec = dict(dec, key=key,
                   status="launched" if launched else "building")
        if launched:
            # Дата, с которой у сайта вообще МОГУТ быть сутки в ряду. Это
            # ожидание, а не измерение, и подписано оно словом «не раньше».
            ld = date(*(int(x) for x in launched.split("-")))
            rec["measurable_from"] = date.fromordinal(
                ld.toordinal() + SC_LAG_DAYS).isoformat()
            rec["days_live"] = (today - ld).days
            rec["blockers"] = BLOCKERS_MEASURE.get(key, [])
        else:
            rec["blockers"] = BLOCKERS_LAUNCH
        root = _site_root(key)
        if root is None:
            # Каталога нет — это НЕ ноль страниц, это «не смотрели». Разница
            # существенная, и она печатается.
            rec["missing"] = True
            out["sites"].append(rec)
            continue
        rec["missing"] = False
        rec["pages"] = _count_sitemap(root)      # что отдано Google
        rec["files"] = _count_files(os.path.join(root, "dist"))
        rec["gates"] = _const(os.path.join(root, "gates.py"), "GATE_COUNT")
        # Числа нарочных поломок здесь НЕТ намеренно: у трёх сайтов список
        # объявлен по-разному, один разбор давал 70 там, где их 132, а
        # надёжно считает только запуск самопроверки — минуты на сайт.
        # Неверное число хуже отсутствующего: на него смотрят.
        out["sites"].append(rec)
    return out


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    data = snapshot()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    tmp = OUT + ".tmp"
    io.open(tmp, "w", encoding="utf-8", newline="\n").write(
        json.dumps(data, ensure_ascii=False, indent=1) + "\n")
    os.replace(tmp, OUT)          # упавшая запись не должна стирать снимок
    for s in data["sites"]:
        if s.get("missing"):
            print("  %-14s КАТАЛОГА НЕТ" % s["key"])
        else:
            print("  %-14s %-9s карта %4s · файлов %4s · гейтов %3s"
                  % (s["key"], s["status"], s["pages"], s["files"], s["gates"]))
    print("корень направления:", ROOT)
    print("снимок стадии записан:", OUT, "· дата", data["taken"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
