# -*- coding: utf-8 -*-
"""Слой данных доски: окна СЧИТАЮТСЯ из посуточного ряда, а не набираются руками.

Почему так, а не как было. Раньше в генераторе лежал словарь с двумя готовыми
срезами, набранными с экрана вручную. У этого три беды сразу:

  1. Набранное руками число проходит мимо всех гейтов — они читают собранный
     HTML, а не источник. Один и тот же класс ошибки уже стоил нам пяти макетов
     с чужими цифрами.
  2. Два готовых среза нельзя пересечь, сдвинуть или сравнить между собой.
     Вопрос «а что было на прошлой неделе» не имел ответа в принципе.
  3. Среднее за всё время у молодого сайта — это среднее по ПАДАЮЩЕМУ тренду.
     У MileageCurve позиция 25,8 лежит ровно между 20,4 первой половины жизни
     и 40,1 второй. Сайт не был на 25,8 ни одного дня.

Теперь есть посуточный ряд, а любое окно — функция от него. Числа сходятся
с итогами Search Console до второго знака, и это проверяется гейтом.

ЧТО ТАКОЕ ПРАВЫЙ КРАЙ. Search Console отдаёт данные с задержкой два-три дня.
Правый край поисковых окон — НИКОГДА не сегодня, а последний день, который в
ряду есть. Иначе последние дни всегда выглядят провалом, которого нет.
"""
import csv
import io
import os
from datetime import date, timedelta

DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

# Дата снятия. Все окна отсчитываются от края РЯДА, а не отсюда; это поле
# нужно только чтобы честно подписать возраст данных.
CAPTURED = date(2026, 8, 31)


def _rows(name):
    """CSV без строк-комментариев. Комментарии здесь несут больше, чем данные."""
    with io.open(os.path.join(DIR, name), encoding="utf-8") as f:
        return list(csv.DictReader(l for l in f if not l.startswith("#")))


def _d(s):
    return date(*map(int, s.split("-")))


# --------------------------------------------------------------- поиск

def _load_search():
    out = {}
    for r in _rows("daily_search.csv"):
        out.setdefault(r["site"], []).append(
            (_d(r["day"]), int(r["clicks"]), int(r["impressions"]),
             float(r["position"])))
    for k in out:
        out[k].sort()
    return out


DAILY = _load_search()

# Правый край ряда — последний день, за который Search Console вообще что-то
# отдал. У обоих сайтов он один и тот же, но считаем по каждому отдельно:
# сайты могут расходиться, и тогда общий край соврёт про молодой.
EDGE = {k: v[-1][0] for k, v in DAILY.items()}
FIRST = {k: v[0][0] for k, v in DAILY.items()}


def window(k, a, b, launch=None):
    """Итог за отрезок [a; b] включительно.

    Позиция взвешивается ПОКАЗАМИ, а не усредняется по дням: день с шестью
    показами не должен весить столько же, сколько день с пятьюстами. Именно так
    считает и сам Search Console — сверено, сходится.

    ЗНАМЕНАТЕЛЬ у «в день» — не длина окна, а длина ЖИЗНИ САЙТА внутри окна.
    Окно в семь дней на сайте, которому три, делённое на семь, занижает темп
    в два с лишним раза, и подписано это будет как «в день».
    """
    q = [x for x in DAILY.get(k, []) if a <= x[0] <= b]
    if not q:
        return None
    c = sum(x[1] for x in q)
    i = sum(x[2] for x in q)
    if not i:
        return None
    left = max(a, launch) if launch else a
    span = max(1, (b - left).days + 1)
    full = (b - a).days + 1
    return {
        "from": q[0][0], "to": q[-1][0],
        "days": full, "span": span, "partial": span < full,
        "days_with_data": len(q),
        "clicks": c, "impressions": i,
        "ctr": c / i * 100,
        "position": sum(x[3] * x[2] for x in q) / i,
        "clicks_day": c / span,
        "impr_day": i / span,
    }


def w7(k, launch=None):
    """Последние 7 полных дней ряда. «Что происходит сейчас»."""
    e = EDGE[k]
    return window(k, e - timedelta(6), e, launch)


def w7_prev(k, launch=None):
    """Семь дней ДО них — единственное, с чем «сейчас» имеет смысл сравнивать.

    Если сайт их не прожил, сравнивать не с чем, и это ЧЕСТНЕЕ, чем сравнить
    с пустотой и объявить рост.
    """
    e = EDGE[k]
    a, b = e - timedelta(13), e - timedelta(7)
    if launch and launch > b:
        return None
    return window(k, a, b, launch)


def w7_prev_opens(k, launch):
    """Когда появится, с чем сравнивать «последние 7 дней»."""
    return launch + timedelta(13) + (CAPTURED - EDGE[k])


def w28(k, launch):
    """Последние 28 полных дней — но ТОЛЬКО если сайт их прожил целиком.

    Окно «28 дней» на сайте, которому три дня, — не окно, а случайный кусок,
    и подписано оно будет как месяц. Пока не набрали — возвращаем None и
    показываем дату, когда откроется.
    """
    e = EDGE[k]
    a = e - timedelta(27)
    return window(k, a, e, launch) if a >= launch else None


def w28_opens(k, launch):
    """Когда окно «28 дней» станет честным: когда его левый край дойдёт до запуска."""
    return launch + timedelta(27) + (CAPTURED - EDGE[k])


def life(k, launch):
    """С запуска по край ряда. Годится для НАКОПЛЕНИЙ, не для средних."""
    return window(k, launch, EDGE[k], launch)


def weeks(k, launch, n=8):
    """Ряд по неделям от края назад. То, чего средние не показывают.

    Крайняя корзина почти всегда НЕПОЛНАЯ: ряд начинается посреди недели.
    У MileageCurve это два дня с позицией 11,0 — если нарисовать их столбцом
    в полную ширину, они прочитаются как блестящий старт, которого не было.
    Поэтому каждая корзина несёт "partial" и сколько дней в ней на самом деле,
    а рисовать неполные надо иначе, чем полные.
    """
    e = EDGE[k]
    out = []
    for j in range(n):
        b = e - timedelta(7 * j)
        w = window(k, b - timedelta(6), b, launch)
        if w:
            out.append(w)
    return list(reversed(out))


# ----------------------------------------------------------------- GA4

_SNAP = {r["site"]: r for r in _rows("ga4_snapshot.csv")}
_CHAN = {}
for _r in _rows("ga4_channels.csv"):
    _CHAN.setdefault(_r["site"], {})[_r["channel"]] = _r


def ga(k):
    """Просмотры страниц и охват. views — числитель порога рекламной сети."""
    s = _SNAP[k]
    return {
        "views": int(s["views"]), "users": int(s["users"]),
        "views_per_user": float(s["views_per_user"]),
        "avg_engagement": s["avg_engagement"],
        "pages_with_views": int(s["pages_with_views"]),
        "pages_built": int(s["pages_built"]),
    }


def organic(k):
    """Поведение ТОЛЬКО органики.

    Direct на сайте без единого канала продвижения, без бренда и без рассылки —
    это не аудитория. Улика прямая: у GS Pay Tables Direct показывает НОЛЬ
    секунд среднего времени и одну вовлечённую сессию из 58. Это сканеры,
    аптайм-мониторы, краулеры и наши собственные заходы при проверках вёрстки.

    Смешивать их с людьми нельзя, а сравнивать так два сайта нельзя тем более:
    доля этого мусора у них 92% и 45%, то есть разбавлены они по-разному и в
    разную сторону.
    """
    c = _CHAN[k]["Organic Search"]
    tot = sum(int(v["sessions"]) for v in _CHAN[k].values())
    o = int(c["sessions"])
    return {
        "sessions": o, "engaged": int(c["engaged"]),
        "engagement": float(c["engagement_rate"].rstrip("%")),
        "avg_time": c["avg_time"],
        "noise_share": (tot - o) / tot * 100,
        "noise_sessions": tot - o,
        "total_sessions": tot,
    }


def channels(k):
    return _CHAN[k]


def age_days(k, launch):
    """Сколько дней сайта покрывает ряд. Возраст по РЯДУ, а не по календарю:
    правый край данных отстаёт от сегодня на два-три дня, и календарный
    возраст обещал бы дни, которых в данных нет."""
    return (EDGE[k] - launch).days + 1


def first_days(k, launch, n):
    """Первые n дней ЖИЗНИ сайта. Основа сравнения сайтов разного возраста:
    по календарю их сравнивать нельзя, по возрасту — можно."""
    return window(k, launch, launch + timedelta(n - 1), launch)


# ===================== величины для графиков =====================
# Ни один рисующий файл не считает величину сам и не сравнивает выборку с
# порогом своим литералом: иначе одна и та же точка окажется то измеренной, то
# нет, смотря на какой график смотришь.

import math

# Ниже этого числа наблюдений доля не считается (см. MIN_SESSIONS на доске).
MEASURE_MIN = 30


def pos_disp(p):
    """Место, ОКРУГЛЁННОЕ до того, как из него что-то выведут.

    Ловушка, найденная при проверке: сырое средневзвешенное за 22–28.08 равно
    40,0231. Округлённое печатается как «40,0», но ceil(40,0231/10) даёт пятую
    страницу вместо четвёртой — доска напечатала бы одно, а подсветила другое,
    и ровно на самом дорогом факте. Поэтому и номер страницы, и координата, и
    цвет, и слово вердикта считаются ИЗ округлённого значения.
    """
    return round(float(p), 1)


def page_of(p):
    """Номер страницы выдачи. Google показывает по десять ссылок на странице."""
    return min(6, math.ceil(pos_disp(p) / 10) or 1)


def at_edge(p):
    """Место у самой границы страницы. Без этой пометки половина позиции
    перекрашивала бы целую клетку и ВЫДУМЫВАЛА переход между страницами."""
    return min(abs(pos_disp(p) - 10 * k) for k in range(1, 7)) <= 1.5


def window_pair(k, launch):
    """Два РАВНЫХ окна: «было» и «стало». Одна функция на всю доску.

    Длина зависит от возраста, поэтому её название печатается в кадре, а
    генератор сообщает дату смены базы: иначе смена прочитается как скачок
    данных.
    """
    ser = DAILY.get(k, [])
    n = len(ser)
    if n <= 1:
        return None
    if n >= 8:
        b = min(7, n // 2)
        label = f"равные {b} суток"
    elif n >= 4:
        b = n // 2
        label = f"равные {b} суток"
    else:
        b = 1
        label = "первые и последние сутки из %d" % n
    now = ser[-b:]
    was = ser[-2 * b:-b] if n >= 4 else ser[:1]
    return {"b": b, "label": label, "was": was, "now": now,
            "full": b == 7}


def when_base_changes(k, launch):
    """Когда сравнение перейдёт на равные семь суток."""
    n = len(DAILY.get(k, []))
    if n >= 14:
        return None
    return CAPTURED + timedelta(14 - n)


def agg(days):
    """Итог по набору суток. Место взвешено ПОКАЗАМИ, как и в Search Console."""
    if not days:
        return None
    c = sum(x[1] for x in days)
    i = sum(x[2] for x in days)
    return {
        "clicks": c, "impressions": i, "days": len(days),
        "clicks_day": c / len(days), "impr_day": i / len(days),
        "position": (sum(x[3] * x[2] for x in days) / i) if i else None,
        "from": days[0][0], "to": days[-1][0],
    }


def test_clicks(was, now):
    """Можно ли вообще утверждать, что переходов стало меньше.

    Переходы — счётные редкие события, их разброс примерно корень из числа.
    «4 против 1» выглядит ростом вчетверо, а при пяти событиях это шум, и
    именно эта строка стояла на доске рядом со словом «Падение», указывая в
    противоположную сторону.

    Возвращает (вердикт, процент или None, разброс).
    """
    tot = was + now
    spread = 2 * math.sqrt(tot) if tot else 0.0
    if tot < 20 or abs(now - was) < spread:
        return "не измерено", None, spread
    pct = round((now - was) / was * 100) if was else None
    return ("падение" if now < was else "рост"), pct, spread


def median(vals):
    v = sorted(vals)
    if not v:
        return 0
    m = len(v) // 2
    return v[m] if len(v) % 2 else (v[m - 1] + v[m]) / 2


def spikes(k):
    """Сутки со всплеском показов: не меньше двух с половиной медиан.

    Правило вычисляется, а не назначается на глаз: визуальное утверждение не
    имеет права быть шире правила, по которому оно построено.
    """
    ser = DAILY.get(k, [])
    if len(ser) < 5:
        return set()
    thr = 2.5 * median([x[2] for x in ser])
    return {x[0] for x in ser if x[2] >= thr}


# Лестница потолков. Потолок берётся ПО ВСЕЙ ДОСКЕ, а не по максимуму сайта:
# иначе картинки двух сайтов нельзя сопоставить глазом, а при новых данных
# график с другим максимумом выглядит точно так же, как старый.
LADDER = [1, 2, 3, 4, 5, 6, 8, 10, 12, 15, 20, 25, 30, 40, 50, 60, 80, 100,
          120, 150, 200, 250, 300, 400, 500, 600, 800, 1000, 1200, 1500,
          2000, 2500, 3000, 4000, 5000]


def ceil_of(v):
    for s in LADDER:
        if s >= v:
            return s
    return LADDER[-1]


def board_ceilings():
    """Потолки обеих дорожек — общие для всей доски."""
    c = max((x[1] for d in DAILY.values() for x in d), default=1)
    i = max((x[2] for d in DAILY.values() for x in d), default=1)
    return ceil_of(c), ceil_of(i)
