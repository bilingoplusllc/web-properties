# -*- coding: utf-8 -*-
"""Снимок стадии сайтов, которые ещё СТРОЯТСЯ.

Почему отдельно от метрик. У этих сайтов нет ни домена, ни Search Console, ни
единого визита. Положить их в таблицу метрик значит напечатать пустоту как
показатели — ровно та ловушка, за которую ферма уже платила: доля по шести
наблюдениям дала 100 баллов и подняла индекс падающего сайта. Пока измерять
нечего, доска обязана говорить СТАДИЮ, а не показатели.

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
import sys
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
def _find_template(start: str) -> str:
    """Найти каталог `_template` ВВЕРХ по дереву, а не по фиксированному «..».

    Раньше путь был жёстким: `HERE/../_template`. Он верен ровно при одной
    раскладке — когда каталог доски лежит прямо в каталоге направления. С
    09.09.2026 доска живёт клоном репозитория (`_board/dashboard/`), и `..`
    указывает уже внутрь клона: снимок стадии молча сообщил бы «каталога
    нет» по всем трём сайтам, а это, по его же комментарию, значит «не
    смотрели», а не «ноль страниц». Поиск вверх переживает и эту раскладку,
    и следующую.
    """
    d = os.path.abspath(start)
    for _ in range(5):
        cand = os.path.join(d, "_template")
        if os.path.isdir(cand):
            return cand
        up = os.path.dirname(d)
        if up == d:
            break
        d = up
    return os.path.join(start, "..", "_template")


TPL = _find_template(HERE)
OUT = os.path.join(HERE, "data", "pipeline.json")

# Что известно НЕ из кода и потому объявлено с причиной. Даты доменов — из
# реестра ветки (куплены 01.09.2026), облик — решение владельца.
DECLARED = {
    "batterycross": {
        "name": "BatteryCross",
        "host": "batterycross.com",
        "niche": "Замены элементов питания: что физически подойдёт вместо снятого",
        "domain": "2026-09-01",
        "design": "промышленный каталог — применён",
        "design_done": True,
    },
    "keepsuntil": {
        "name": "KeepsUntil",
        "host": "keepsuntil.com",
        "niche": "Сроки хранения еды по данным USDA FoodKeeper",
        "domain": "2026-09-01",
        "design": "бирка на банке — применён",
        "design_done": True,
    },
    "districtbyzip": {
        "name": "DistrictByZip",
        "host": "districtbyzip.com",
        "niche": "Школьные округа по почтовому индексу, отдельно для K-8 и 9-12",
        "domain": "2026-09-01",
        "design": "счётное поле — ВЫБРАН, но к сайту не применён",
        "design_done": False,
    },
}

# Что мешает запуску. Общее для всех трёх — на всех трёх и печатается; своё —
# у своего. Пустой список означал бы «готов к запуску», поэтому пустоту сюда
# писать нельзя, пока это неправда.
BLOCKERS_ALL = [
    "почтового ящика на домене не существует (адрес на страницах напечатан)",
    "нет идентификатора издателя AdSense — реклама стоит заглушками",
    "нет идентификатора GA4 — трафик не будет измерен с первого дня",
]
BLOCKERS_OWN = {
    "districtbyzip": ["облик выбран, но к сайту не применён"],
}


def _count_files(root, ext=".html"):
    n = 0
    for base, _dirs, files in os.walk(root):
        n += sum(1 for f in files if f.endswith(ext))
    return n


def _const(path, name):
    """Достать константу из исходника, НЕ импортируя его.

    Импорт запустил бы генератор сайта со всеми его побочными действиями, а
    нам нужно одно число. `ast` читает то же самое и ничего не выполняет.
    """
    try:
        tree = ast.parse(io.open(path, encoding="utf-8").read())
    except (OSError, SyntaxError):
        return None
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == name:
                    try:
                        return ast.literal_eval(node.value)
                    except ValueError:
                        return None
    return None


def snapshot():
    out = {"taken": date.today().isoformat(), "sites": []}
    for key, dec in DECLARED.items():
        root = os.path.join(TPL, key)
        if not os.path.isdir(root):
            # Каталога нет — это НЕ ноль страниц, это «не смотрели». Разница
            # существенная, и она печатается.
            out["sites"].append(dict(dec, key=key, missing=True))
            continue
        rec = dict(dec, key=key, missing=False)
        rec["pages"] = _count_files(os.path.join(root, "dist"))
        rec["gates"] = _const(os.path.join(root, "gates.py"), "GATE_COUNT")
        # Числа нарочных поломок здесь НЕТ намеренно: у трёх сайтов список
        # объявлен по-разному, один разбор давал 70 там, где их 132, а
        # надёжно считает только запуск самопроверки — минуты на сайт.
        # Неверное число хуже отсутствующего: на него смотрят.
        rec["blockers"] = BLOCKERS_ALL + BLOCKERS_OWN.get(key, [])
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
            print("  %-14s страниц %4s · гейтов %3s"
                  % (s["key"], s["pages"], s["gates"]))
    print("снимок стадии записан:", OUT, "· дата", data["taken"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
