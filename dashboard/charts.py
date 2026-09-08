# -*- coding: utf-8 -*-
"""Графика динамики. Ни одна величина здесь не считается — только рисуется.

Разделение жёсткое: wp_data отдаёт числа, charts превращает их в координаты.
Иначе одна и та же величина оказывается посчитанной дважды и однажды разойдётся
сама с собой — у нас так уже было с рангами, которые карточка и таблица
считали независимо.

ТРИ ЭЛЕМЕНТА, каждый отвечает на свой вопрос:
  1. Шапка-вердикт — HTML без единой шкалы. Соврать нечем: там нет геометрии,
     кодирующей величину.
  2. «Стало против было» по ПЕРЕХОДАМ, с нарисованной полосой случайности.
  3. Лента 28 суток: переходы, показы, место — на одной календарной оси.

ЧЕМ ЭТО ВЫЗВАНО. На прежней доске деньги не были нарисованы нигде: все графики
кодировали показы и место. У GS Pay Tables единственная количественная картинка
(показы 487 -> 1084 -> 895) РОСЛА, пока переходы падали 34 -> 8, то есть
утверждала обратное вердикту, написанному над ней. За три секунды смотрят на
картинку, а не читают абзац.

ПОЧЕМУ КАЛЕНДАРНАЯ ОСЬ С ПОСТОЯННОЙ ШИРИНОЙ СУТОК. Раньше ряд любой длины
растягивался на всю ширину: шестнадцать суток и трое суток занимали одинаковое
место, наклон трёхдневной линии был сопоставим с наклоном шестнадцатидневной, и
разный возраст сайтов оказывался не «не показан», а СТЁРТ. Теперь сутки — это
константа, одна на всю доску: пятидневный сайт занимает три клетки из
двадцати восьми, девятнадцатидневный — шестнадцать. Возраст нарисован.

ПОЧЕМУ ПОТОЛКИ ОБЩИЕ. Шкала от собственного максимума делает две картинки
несопоставимыми и вдобавок перерисовывает себя при каждом обновлении данных:
сравнить сегодняшнюю с той, что видел неделю назад, нечем.
"""
import wp_data as wp

# --------------------------------------------------------- геометрия
W = 1030
PAD_L, PAD_R, DAY = 118, 16, 32
DAYS = 28                      # окно ленты: последние 28 календарных суток
assert PAD_L + DAY * DAYS + PAD_R == W, "лента не сходится по ширине"

A_TOP, A_BASE = 30, 114        # дорожка переходов
B_TOP, B_BASE = 160, 244       # дорожка показов
PANEL = 84
C_TOP = 296                    # верх дорожки места
PAGE_H = 20                    # одна страница выдачи = 20 единиц
PAGES = 6
C_BOT = C_TOP + PAGE_H * PAGES
H = 466

# Оценка ширины текста ОДНОЙ константой: измерять текст нечем — JavaScript
# запрещён целиком, а getComputedTextLength без него не существует.
CH = 0.55


def tw(text, size):
    return CH * size * len(text)


def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def num(x, digits=1):
    return ("%.*f" % (digits, x)).replace(".", ",")


# ----------------------------------------------------------- шкалы

def x_of(j):
    return PAD_L + DAY * j


def cx_of(j):
    return PAD_L + DAY * j + DAY / 2


def y_pos(p):
    """Место на дорожке выдачи. Первое место СВЕРХУ.

    Не перевернуть ось — значит нарисовать падение с 23-го места на 40-е
    линией, идущей ВВЕРХ. Границы полос-страниц берутся ЭТОЙ ЖЕ функцией, а не
    набираются руками: набранные руками они однажды уехали в чужую панель.
    """
    v = min(max(wp.pos_disp(p), 0.0), float(PAGE_H * PAGES / 2))
    return C_TOP + 2 * v


def y_bar(v, ceil_, base):
    return base - PANEL * (v / ceil_ if ceil_ else 0)


# ------------------------------------------------------ элемент 1

WHY_NOT_IMPRESSIONS = (
    "Показы — объясняющая величина, а не цель, и в слово вердикта они не "
    "входят никогда. Сайт, которому Google стал чаще показывать бесполезную "
    "страницу, успешнее не стал: у GS Pay Tables показы выросли впятеро ровно "
    "в те дни, когда переходы упали вчетверо.")

WHY_SPREAD = (
    "Переходы — редкие счётные события, и их разброс примерно равен корню из "
    "числа. Пока разница меньше разброса, отличить движение от везения нечем, "
    "и процент не считается вовсе: «4 против 1» выглядит ростом вчетверо, а "
    "при пяти событиях означает ровно ничего.")


def verdict_head(s, series, pair):
    """Слово вердикта и одна короткая строка. Всё «почему» — под наведением."""
    if pair is None:
        return ('<div class="vd"><span class="vd-word na">Пока не измерено</span>'
                '<span class="vd-sub">суток с данными меньше двух</span></div>')
    was, now = wp.agg(pair["was"]), wp.agg(pair["now"])
    verdict, pct, spread = wp.test_clicks(was["clicks"], now["clicks"])
    p_was, p_now = wp.pos_disp(was["position"]), wp.pos_disp(now["position"])
    d_pos = ("хуже" if p_now > p_was + 0.3 else
             "лучше" if p_now < p_was - 0.3 else "без движения")

    down = verdict == "падение" or (verdict == "не измерено" and d_pos == "хуже")
    up = verdict in ("рост", "рост с нуля") and d_pos in ("лучше", "без движения")
    if verdict == "не измерено" and d_pos == "без движения":
        word, cls = "Без движения", "na"
    elif up:
        word, cls = "Растём", "up"
    elif down:
        word, cls = "Падаем", "down"
    else:
        word, cls = "Разнобой", "na"

    if verdict == "не измерено":
        sub = (f'по месту в выдаче — переходов слишком мало, чтобы судить '
               f'по ним{tipmark(WHY_SPREAD)}')
    else:
        sub = f'по переходам и по месту в выдаче'
    return (f'<div class="vd"><span class="vd-word {cls}">{word}</span>'
            f'<span class="vd-sub">{sub}</span>'
            f'<span class="vd-win">{pair["label"]}</span></div>')


def tipmark(text):
    """Значок «почему» с подсказкой. Объяснение обязано быть доступно, но не
    обязано занимать строку."""
    return (f'<span class="tip qm" tabindex="0" data-tip="{esc(text)}">?</span>')


def pages_block(s, pair):
    """Место в выдаче: шесть равных клеток — шесть страниц.

    Это категорическое утверждение живёт РОВНО ЗДЕСЬ, один раз, и нигде больше
    на доске не повторяется геометрией. Клетка «было» помечена пунктиром,
    клетка «стало» — сплошной рамкой и цветом направления; между ними стрелка,
    чтобы движение читалось само, без подписи под картинкой.
    """
    if pair is None:
        return ""
    was, now = wp.agg(pair["was"]), wp.agg(pair["now"])
    p_was, p_now = wp.pos_disp(was["position"]), wp.pos_disp(now["position"])
    pg_was, pg_now = wp.page_of(was["position"]), wp.page_of(now["position"])
    d_pos = ("down" if p_now > p_was + 0.3 else
             "up" if p_now < p_was - 0.3 else "")

    cells = ""
    lo, hi = min(pg_was, pg_now), max(pg_was, pg_now)
    for kpg in range(1, PAGES + 1):
        cls, inner = [], f'<span class="pg-n">стр. {kpg}</span>'
        if lo < kpg < hi:
            cls.append("mid")
        if kpg == pg_was:
            cls.append("was")
            inner += f'<span class="pg-v">было {num(p_was)}</span>'
        if kpg == pg_now:
            cls.append("now")
            if d_pos:
                cls.append(d_pos)
            inner += (f'<span class="pg-v">{"было и стало" if kpg == pg_was else "стало " + num(p_now)}</span>')
        cells += f'<div class="{" ".join(cls)}">{inner}</div>'

    edge = (tipmark("Место " + num(p_now) + " стоит у самой границы страниц: "
                    "полбалла туда-сюда — и клетка была бы соседней. Поэтому "
                    "граница отмечена, а не проглочена.")
            if wp.at_edge(now["position"]) else "")
    return (f'<p class="ch-t">Место в выдаче{edge}'
            f'<span>десять ссылок на странице · первая страница слева</span></p>'
            f'<div class="pages">{cells}</div>')


def impr_line(pair):
    """Показы — ОДНОЙ строкой. Своя картинка у них уже есть в ленте ниже, а в
    вердикт они не входят: это объяснение, а не цель."""
    if pair is None:
        return ""
    was, now = wp.agg(pair["was"]), wp.agg(pair["now"])
    a, b = round(was["impr_day"]), round(now["impr_day"])
    d = round((b - a) / a * 100) if a else None
    tone = "down" if d is not None and d < 0 else ("up" if d else "")
    chg = (f'<span class="dl-c {tone}">{"+" if d and d > 0 else ""}{d}%</span>'
           if d is not None else "")
    return (f'<p class="dl"><span class="dl-n">Показов в сутки</span>'
            f'<span class="dl-a">{a}</span><span class="dl-ar">→</span>'
            f'<span class="dl-b">{b}</span>{chg}{tipmark(WHY_NOT_IMPRESSIONS)}</p>')


# ------------------------------------------------------ элемент 2

CMP_W, CMP_H = 1030, 156
CMP_X0, CMP_X1 = 230, 870


def cmp_clicks(s, pair):
    """«Стало против было» по переходам, с НАРИСОВАННОЙ полосой случайности.

    Полоса — главный элемент, а не украшение. Она отвечает на вопрос, который
    иначе не задают вовсе: можно ли по этим числам вообще что-то утверждать.
    Столбик, кончающийся внутри полосы, виден как «мерить нечем» без единого
    слова.

    К ПОКАЗАМ эта полоса не применяется никогда: их разброс не пуассоновский,
    и «±91» было бы ложной уверенностью.
    """
    if pair is None:
        return ""
    was, now = wp.agg(pair["was"]), wp.agg(pair["now"])
    v_was, v_now = was["clicks"], now["clicks"]
    verdict, pct, spread = wp.test_clicks(v_was, v_now)

    lo = max(0.0, v_was - spread)
    hi = v_was + spread
    ceil_ = wp.ceil_of(max(v_was, v_now, hi))
    span = CMP_X1 - CMP_X0

    def x(v):
        return CMP_X0 + span * (v / ceil_ if ceil_ else 0)

    fill = {"падение": "var(--coral-soft)", "рост": "var(--ok-bg)",
            "рост с нуля": "var(--ok-bg)"}.get(verdict, "var(--wait-bg)")
    badge_fill = fill
    badge_ink = {"падение": "var(--coral)", "рост": "var(--ok)",
                 "рост с нуля": "var(--ok)"}.get(verdict, "var(--wait)")
    # «с нуля» и «не измерено» — разные вещи, и обе без процента. Пока они
    # печатались одним словом, на плашке стояло «не измерено» рядом со словом
    # «Растём».
    badge_text = ("с нуля" if verdict == "рост с нуля" else
                  "не измерено" if pct is None else
                  ("+" if pct > 0 else "") + str(pct) + "%")

    band_lab = "полоса случайности — внутри неё разницу считать нельзя"
    band_w = x(hi) - x(lo)
    if tw(band_lab, 11) > band_w:
        band_lab = "полоса случайности"
    band = (f'<rect class="band-rnd" x="{x(lo):.1f}" y="36" '
            f'width="{band_w:.1f}" height="72"><title>разброс ±{num(spread)} '
            f'перехода</title></rect>'
            f'<text class="c-band" x="{(x(lo) + x(hi)) / 2:.1f}" y="30" '
            f'text-anchor="middle">{esc(band_lab)}</text>')

    rows = ""
    for i, (lab, v, y0, is_now) in enumerate((
            (f'Было · {pair["was"][0][0].strftime("%d.%m")}'
             + (f'–{pair["was"][-1][0].strftime("%d.%m")}'
                if len(pair["was"]) > 1 else ""), v_was, 40, False),
            (f'Стало · {pair["now"][0][0].strftime("%d.%m")}'
             + (f'–{pair["now"][-1][0].strftime("%d.%m")}'
                if len(pair["now"]) > 1 else ""), v_now, 78, True))):
        bw = max(3.0, x(v) - CMP_X0)
        style = (f'fill:{fill};stroke:var(--ink2)' if is_now
                 else 'fill:var(--brand-soft);stroke:var(--brand)')
        # Измеренный ноль — чёрточка, а не пустота: пустота читается как
        # «здесь ничего не мерили».
        if v == 0:
            bar = (f'<rect x="{CMP_X0}" y="{y0}" width="3" height="26" '
                   f'fill="var(--ink2)"/>')
        else:
            bar = (f'<rect x="{CMP_X0}" y="{y0}" width="{bw:.1f}" height="26" '
                   f'style="{style}" stroke-width="1"/>')
        word = f'{v} ' + plural(v, "переход", "перехода", "переходов")
        tx = CMP_X0 + bw + 8
        anchor, ink = "start", "var(--ink)"
        if tx + tw(word, 12) > CMP_X1:
            tx, anchor = CMP_X0 + bw - 8, "end"
        rows += (bar
                 + f'<text class="c-lab" x="222" y="{y0 + 17}" '
                   f'text-anchor="end">{esc(lab)}</text>'
                 + f'<text class="c-val" x="{tx:.1f}" y="{y0 + 17}" '
                   f'text-anchor="{anchor}" fill="{ink}">{esc(word)}</text>')

    head = "Переходы: стало против было"
    if not pair["full"]:
        head += f' · {pair["label"]} — это ещё не тренд'

    return f"""
    <svg class="chart cmp" viewBox="0 0 {CMP_W} {CMP_H}" role="img"
      aria-label="{esc(head)}: {v_was} против {v_now}, {esc(verdict)}">
      <text class="c-head" x="8" y="18">{esc(head)}</text>
      {band}
      <line x1="{CMP_X0}" x2="{CMP_X0}" y1="34" y2="112"
        stroke="var(--ink2)" stroke-width="1.5"/>
      {rows}
      <text class="ax lo" x="{CMP_X0}" y="128" text-anchor="middle">0</text>
      <text class="ax lo" x="{CMP_X1}" y="128" text-anchor="middle">{ceil_}</text>
      <rect x="878" y="58" width="136" height="28" rx="6" fill="{badge_fill}"
        stroke="{badge_ink}" stroke-width="1"/>
      <text class="c-badge" x="946" y="77" text-anchor="middle"
        fill="{badge_ink}">{esc(badge_text)}</text>
    </svg>"""


def plural(n, one, few, many):
    n = abs(int(n))
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


# ------------------------------------------------------ элемент 3

def ribbon(s, series, today, ceil_c, ceil_i, suffix=""):
    """Лента 28 суток: переходы, показы, место на одной календарной оси.

    Три дорожки — три единицы. Общая у них только ось времени; ни одна шкала
    не делится между величинами. Деньги стоят ПЕРВЫМИ и сверху.
    """
    k = s["key"]
    start = today - __import__("datetime").timedelta(DAYS - 1)
    launch = s["live"]
    # Сутки до запуска сюда не доходят: ряд обрезан по LAUNCH при загрузке
    # (wp_data._load_search). Здесь этого фильтра БЫТЬ НЕ ДОЛЖНО — он стоял
    # тут одну итерацию и чинил только ленту, пока то же самое враньё лезло в
    # сравнение окон: «показов в сутки 517 → 1035, +100%», где двое из суток
    # «было» сайта ещё не существовало. Одна величина — одна функция.
    by_day = {x[0]: x for x in series}
    last_data = series[-1][0] if series else None
    spike_days = wp.spikes(k)
    med = wp.median([x[2] for x in series]) if series else 0

    def j_of(day):
        return (day - start).days

    # id узора уникален на КАЖДУЮ отрисовку: лента рисуется трижды, по разу
    # на окно, и одинаковые id — невалидная разметка, в которой ссылка
    # url(#…) однажды укажет не туда.
    uid = k + ("-" + suffix if suffix else "")

    # ---- зоны: до запуска и после края данных
    zones = ""
    jl = j_of(launch)
    if jl > 0:
        wz = x_of(min(jl, DAYS)) - x_of(0)
        lab = "сайта ещё не было"
        if tw(lab, 12) + 8 > wz:
            lab = "до запуска"
        zones += (f'<rect x="{x_of(0)}" y="{A_TOP}" width="{wz:.1f}" '
                  f'height="{C_BOT - A_TOP}" fill="url(#h-{uid})"/>')
        if tw(lab, 12) + 8 <= wz:
            zones += (f'<text class="z" x="{(x_of(0) + x_of(min(jl, DAYS))) / 2:.1f}" '
                      f'y="{A_TOP + 34}" text-anchor="middle">{lab}</text>')
    if last_data is not None and j_of(last_data) < DAYS - 1:
        jd = j_of(last_data) + 1
        wz = x_of(DAYS) - x_of(jd)
        zones += (f'<rect x="{x_of(jd)}" y="{A_TOP}" width="{wz:.1f}" '
                  f'height="{C_BOT - A_TOP}" fill="url(#h-{uid})"/>')
        if tw("нет данных", 12) + 8 <= wz:
            zones += (f'<text class="z" x="{(x_of(jd) + x_of(DAYS)) / 2:.1f}" '
                      f'y="{A_TOP + 34}" text-anchor="middle">нет данных</text>')
    if 0 <= jl < DAYS:
        zones += (f'<line x1="{x_of(jl):.1f}" x2="{x_of(jl):.1f}" y1="{A_TOP}" '
                  f'y2="{C_BOT}" stroke="var(--ink2)" stroke-width="1.25"/>')
        # Подпись запуска ставится ВЛЕВО от линии, в штриховку: справа она
        # налезала на число над первым же столбиком («34» и «запуск 26.08»
        # печатались друг на друге). Слева всегда пусто по построению — там
        # зона «сайта ещё не было».
        lab = f'запуск {launch.strftime("%d.%m")}'
        anchor, lx = "end", x_of(jl) - 6
        if tw(lab, 11) + 10 > x_of(jl) - x_of(0):
            anchor, lx = "start", x_of(jl) + 6
        zones += (f'<text class="z" x="{lx:.1f}" y="{A_TOP + 14}" '
                  f'text-anchor="{anchor}">{lab}</text>')

    # ---- дорожка переходов
    a = _track(series, by_day, j_of, ceil_c, A_TOP, A_BASE, 1,
               "переход", "перехода", "переходов", spike_days=set())
    a_head = ('<text class="t-h" x="8" y="18">Переходы из поиска — сколько '
              'человек пришло, в сутки</text>'
              f'<text class="ax lo" x="{W - PAD_R}" y="18" text-anchor="end">'
              f'шкала до {ceil_c} в сутки — общая для всей доски</text>')
    total_clicks = sum(x[1] for x in series)
    if total_clicks < wp.MEASURE_MIN:
        # Плашка ставится СПРАВА, у края поля: слева она налезала на подпись
        # запуска и на надпись «сайта ещё не было». Место детерминировано —
        # столбики этой дорожки при таком условии заведомо низкие.
        _pw = 264
        _px = W - PAD_R - _pw - 4
        a_head += (f'<rect x="{_px}" y="{A_TOP + 4}" width="{_pw}" '
                   f'height="22" rx="4" fill="var(--wait-bg)" '
                   f'stroke="var(--wait)" stroke-width="1"/>'
                   f'<text class="warn-s" x="{_px + 12}" y="{A_TOP + 19}">'
                   f'{total_clicks} '
                   f'{plural(total_clicks, "переход", "перехода", "переходов")}'
                   f' за жизнь — не измерено</text>')

    # ---- дорожка показов
    b = _track(series, by_day, j_of, ceil_i, B_TOP, B_BASE, 2,
               "показ", "показа", "показов", spike_days=spike_days)
    b_head = ('<text class="t-h" x="8" y="148">Показов в сутки — сколько раз '
              'ссылку показали в Google</text>'
              f'<text class="ax lo" x="{W - PAD_R}" y="148" text-anchor="end">'
              f'шкала до {ceil_i} · всплеск = от {num(2.5 * med, 0)}</text>')

    # ---- дорожка места
    c = _postrack(series, j_of)

    ticks = ""
    for j in range(DAYS):
        day = start + __import__("datetime").timedelta(j)
        if j % 3 == 0 or j == DAYS - 1:
            ticks += (f'<text class="ax" x="{cx_of(j):.1f}" y="{C_BOT + 18}" '
                      f'text-anchor="middle">{day.strftime("%d.%m")}</text>')

    return f"""
    <svg class="chart lenta" viewBox="0 0 {W} {H}" role="img"
      aria-label="Лента за 28 суток: переходы, показы и место в выдаче">
      <defs><pattern id="h-{uid}" width="6" height="6"
        patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
        <line x1="0" y1="0" x2="0" y2="6" stroke="var(--line)"
          stroke-width="1.2"/></pattern></defs>
      {zones}
      {a_head}{a}
      {b_head}{b}
      {c}
      {ticks}
    </svg>"""


def _track(series, by_day, j_of, ceil_, top, base, kind, one, few, many,
           spike_days):
    """Одна столбчатая дорожка.

    ИЗМЕРЕННЫЙ НОЛЬ рисуется чёрточкой НА нулевой линии, а не отсутствием
    столбика: пустая клетка обязана означать «данных нет», и ничего больше.
    """
    grid = ""
    for frac, lab in ((1.0, ceil_), (0.5, ceil_ // 2), (0.0, 0)):
        gy = base - PANEL * frac
        grid += (f'<line class="g" x1="{PAD_L}" x2="{W - PAD_R}" '
                 f'y1="{gy:.1f}" y2="{gy:.1f}"/>'
                 f'<text class="ax lo" x="{PAD_L - 6}" y="{gy + 4:.1f}" '
                 f'text-anchor="end">{lab}</text>')
    body = ""
    for day, clicks, impr, pos in series:
        j = j_of(day)
        if not 0 <= j < DAYS:
            continue
        v = clicks if kind == 1 else impr
        cx = cx_of(j)
        if v == 0:
            body += (f'<rect class="zero" x="{cx - 10:.1f}" y="{base - 1}" '
                     f'width="20" height="2"><title>{day.strftime("%d.%m")}: '
                     f'0 {many}</title></rect>'
                     f'<text class="ax lo" x="{cx:.1f}" y="{base - 6:.1f}" '
                     f'text-anchor="middle">0</text>')
            continue
        h = max(2.0, PANEL * v / ceil_)
        y = base - h
        body += (f'<rect class="b" x="{cx - 10:.1f}" y="{y:.1f}" width="20" '
                 f'height="{h:.1f}"><title>{day.strftime("%d.%m")}: {v} '
                 f'{plural(v, one, few, many)}</title></rect>')
        inside = h > 0.9 * PANEL
        body += (f'<text class="val{" inb" if inside else ""}" x="{cx:.1f}" '
                 f'y="{(y + 13) if inside else (y - 4):.1f}" '
                 f'text-anchor="middle">{v}</text>')
        if day in spike_days:
            body += (f'<text class="spk" x="{cx:.1f}" y="{y - 16:.1f}" '
                     f'text-anchor="middle">↑</text>')
    return grid + body


def _postrack(series, j_of):
    """Дорожка места. Шесть равных полос — шесть страниц выдачи.

    Полосы РАВНЫЕ по построению: страница = десять мест, полоса = двадцать
    единиц. Границы берутся из y_pos, а не набираются руками.
    """
    head = ('<text class="t-h" x="8" y="278">Место в выдаче — на какой '
            'странице Google нас показывает</text>'
            f'<text class="ax lo" x="{W - PAD_R}" y="278" text-anchor="end">'
            f'выше — лучше</text>')
    bands = ""
    for kpg in range(1, 7):
        y0 = y_pos(10 * (kpg - 1)) if kpg > 1 else C_TOP
        y1 = y_pos(10 * kpg)
        cls = "pg1" if kpg == 1 else ("bandz" if kpg % 2 == 0 else "")
        if cls:
            bands += (f'<rect class="{cls}" x="{PAD_L}" y="{y0:.1f}" '
                      f'width="{W - PAD_L - PAD_R}" height="{y1 - y0:.1f}"/>')
        bands += (f'<text class="ax lo{" pg" if kpg == 1 else ""}" '
                  f'x="{PAD_L - 6}" y="{(y0 + y1) / 2 + 4:.1f}" '
                  f'text-anchor="end">стр. {kpg}</text>')
    pts, dots = [], ""
    for day, clicks, impr, pos in series:
        j = j_of(day)
        if not 0 <= j < DAYS:
            continue
        px, py = cx_of(j), y_pos(pos)
        pts.append((px, py))
        # Радиус ПОСТОЯНЕН: кодировать им объём значило бы положить две
        # величины в геометрию одной картинки.
        weak = impr < wp.MEASURE_MIN
        dots += (f'<circle class="d{" weak" if weak else ""}" cx="{px:.1f}" '
                 f'cy="{py:.1f}" r="3.2"><title>{day.strftime("%d.%m")}: место '
                 f'{num(wp.pos_disp(pos))}, {wp.page_of(pos)}-я страница'
                 f'{", показов всего " + str(impr) + " — не измерено" if weak else ""}'
                 f'</title></circle>')
    line = ""
    if len(pts) > 1:
        line = ('<path class="pl" d="M'
                + " L".join(f"{x:.1f},{y:.1f}" for x, y in pts) + '"/>')
    return head + bands + line + dots
