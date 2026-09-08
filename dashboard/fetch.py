# -*- coding: utf-8 -*-
"""Свежие данные для доски: Search Console и GA4.

До этого КАЖДЫЙ ряд снимался руками — в шапке любого CSV стоит «Снято руками
31.08.2026». Пока так, доска стареет молча: числа выглядят сегодняшними,
потому что страница собрана сегодня.

ЧЕГО ЭТОТ ЗАГРУЗЧИК НЕ ДЕЛАЕТ, и это главное.

  * Он не пишет пустоту. Пустой ответ API чаще всего значит «запрос не
    выполнился», а не «нуль»: у нас уже был случай, когда «ничего не найдено»
    оказалось незапущенным запросом. Поэтому если для сайта, у которого в
    прошлом файле были строки, приходит ноль строк — файл НЕ переписывается,
    и загрузчик падает с этим в тексте ошибки.
  * Он не подставляет вчерашние числа под сегодняшнюю дату. В шапку каждого
    файла пишется дата и окно, за которое данные взяты, и доска печатает их
    рядом с числами.
  * Он не хранит ключ. Ключа не существует — см. ниже.

ПОЧЕМУ КЛЮЧА НЕТ ВООБЩЕ.

Организация bilingoplus.com запрещает создание ключей служебных аккаунтов
(политика iam.disableServiceAccountKeyCreation, Enforced). Запрет правильный:
скачанный ключ живёт вечно, лежит файлом и утекает молча. Вместо ключа —
федерация: GitHub Actions предъявляет свой OIDC-токен, Google меняет его на
временный и выдаёт его от имени служебного аккаунта. Владельцу нечего
вставлять, нечего ротировать и нечему утекать.

  проект         bilingoplus-board (номер 344965276479)
  служебный      board-fetch@bilingoplus-board.iam.gserviceaccount.com
  пул/провайдер  github / gh-actions, issuer token.actions.githubusercontent.com
  условие входа  assertion.repository_owner == 'bilingoplusllc'
  кому доверяем  attribute.repository = bilingoplusllc/web-properties

Читательский доступ выдан отдельно, потому что Search Console и GA4 не знают
про роли Cloud: в Search Console служебный аккаунт добавлен пользователем
обоих ресурсов, в GA4 — ролью Viewer на обоих ресурсах.

GOOGLE_SA_JSON поддержан на случай запуска НЕ из CI, но в репозитории его нет
и заводить его не нужно.

Запуск:  python fetch.py            (нужны google-auth и requests)
"""
import io
import json
import os
import sys
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
DAYS = 90

SCOPES = [
    "https://www.googleapis.com/auth/webmasters.readonly",
    "https://www.googleapis.com/auth/analytics.readonly",
]

# Ресурсы Search Console. Форма адреса — та же, что в самой Search Console.
GSC = {
    "mileagecurve": "sc-domain:mileagecurve.com",
    "gspaytables": "sc-domain:gspaytables.com",
}

# ЧИСЛОВЫЕ идентификаторы ресурсов GA4 (Admin -> Property details), а НЕ
# измерительные G-XXXX. Секретом они не являются: сами по себе не открывают
# ни одного отчёта — доступ даёт роль Viewer у служебного аккаунта. Поэтому
# они лежат здесь, а не в секрете репозитория: секрет, который нельзя
# прочитать, невозможно и проверить глазами.
GA4 = {
    "mileagecurve": "550704652",
    "gspaytables": "551647466",
}


class Missing(Exception):
    """Не настроено. Это не сбой сети и не ноль — это отсутствие доступа, и
    молча превращать его в пустые данные нельзя."""


def _creds():
    raw = os.environ.get("GOOGLE_SA_JSON", "").strip()
    if raw:
        try:
            info = json.loads(raw)
        except ValueError as e:
            raise Missing("GOOGLE_SA_JSON не разбирается как JSON: %s" % e)
        from google.oauth2 import service_account      # noqa: E402
        return service_account.Credentials.from_service_account_info(
            info, scopes=SCOPES)
    # Ключа нет — и это норма. В CI личность приходит федерацией, а
    # google.auth.default() находит её по файлу, который положил шаг
    # google-github-actions/auth. Вне CI не найдёт ничего — и это «не
    # настроено», а не поломка.
    try:
        import google.auth                              # noqa: E402
        from google.auth.exceptions import DefaultCredentialsError  # noqa: E402
    except ImportError as e:
        raise Missing("библиотека google-auth не установлена (%s); она нужна "
                      "только боту" % e)
    try:
        creds, _project = google.auth.default(scopes=SCOPES)
    except DefaultCredentialsError as e:
        raise Missing(
            "личности нет: ни GOOGLE_SA_JSON, ни федерации (%s). Данные НЕ "
            "обновлены и НЕ затёрты; доска покажет прежние числа с их "
            "прежней датой." % e)
    return creds


def _session(creds):
    import google.auth.transport.requests as gr        # noqa: E402
    s = gr.AuthorizedSession(creds)
    s.headers["User-Agent"] = "bilingoplus-board/1.0"
    return s


def _ga4_properties():
    """Ресурсы GA4. Переменная окружения перекрывает список в коде — это для
    разового прогона по другому ресурсу, а не для постоянной настройки."""
    raw = os.environ.get("GA4_PROPERTIES", "").strip()
    if not raw:
        return dict(GA4)
    out = {}
    for part in raw.split(","):
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        out[k.strip()] = v.strip()
    if not out:
        raise Missing("GA4_PROPERTIES пуст после разбора: %r" % raw)
    return out


def _same_sites(props):
    """Два источника обязаны говорить об одних и тех же сайтах.

    Если сайт есть в Search Console и нет в GA4 (или наоборот), доска
    напечатает две таблицы про РАЗНЫЕ множества, и никто этого не заметит:
    отсутствующая строка не выглядит ошибкой. Пусть лучше упадёт здесь.
    """
    a, b = set(GSC), set(props)
    if a != b:
        raise RuntimeError(
            "списки сайтов разошлись: только в Search Console %s, только в "
            "GA4 %s. Пока они не совпадут, доска сравнивала бы разное."
            % (sorted(a - b) or "-", sorted(b - a) or "-"))


def _secs(total):
    """Секунды в том виде, в каком их печатает доска: «13s», «1m 05s».

    Формат не украшение: слой данных отдаёт эту величину В ДОСКУ СТРОКОЙ, как
    её сняли руками из GA4. Отдать сюда число значит напечатать «13.0» там,
    где рядом стоит «1m 05s».
    """
    total = int(round(float(total)))
    if total < 60:
        return "%ds" % total
    return "%dm %02ds" % (total // 60, total % 60)


def _pct(x):
    """Доля в том же виде, что снятая руками: «50%», «4.41%»."""
    v = round(float(x) * 100, 2)
    s = ("%.2f" % v).rstrip("0").rstrip(".")
    return s + "%"


def _prev_header(name):
    """Шапка ПРЕЖНЕГО файла — эталон, взятый не у проверяемого.

    Загрузчик писал «site,date,impressions,clicks,position», а доска читала
    «site,day,clicks,impressions,position»: имена и порядок разошлись, и
    узналось это только когда бот впервые действительно сходил за данными.
    Эталон нельзя брать из этого файла — он и есть проверяемое. Берём его у
    того, кто уже работает: у файла, который доска читает сегодня.
    """
    path = os.path.join(DATA, name)
    if not os.path.exists(path):
        return None
    with io.open(path, encoding="utf-8") as f:
        for line in f:
            if not line.startswith("#"):
                return [c.strip() for c in line.strip().split(",")]
    return None


def _prev_rows(name):
    """Прежние строки файла словарями — для колонок, которых в API нет."""
    path = os.path.join(DATA, name)
    if not os.path.exists(path):
        return {}
    import csv
    with io.open(path, encoding="utf-8") as f:
        rows = list(csv.DictReader(l for l in f if not l.startswith("#")))
    return {r["site"]: r for r in rows if r.get("site")}


def _prev_keys(name, col):
    """Какие сайты БЫЛИ в прежнем файле. Нужно, чтобы отличить «нуль» от
    «запрос не выполнился»: сайт, у которого строки были, а теперь их нет, —
    это отказ, а не отсутствие трафика."""
    path = os.path.join(DATA, name)
    if not os.path.exists(path):
        return set()
    import csv
    with io.open(path, encoding="utf-8") as f:
        rows = list(csv.DictReader(l for l in f if not l.startswith("#")))
    return {r[col] for r in rows if r.get(col)}


def _write(name, header, rows, note, extra=()):
    """Записать файл, если шапка совпала и не пропал ни один прежний сайт."""
    was = _prev_header(name)
    if was is None:
        raise RuntimeError(
            "%s: прежнего файла нет, а значит не с чем сверить шапку. "
            "Загрузчик не заводит новые таблицы: их формат знает тот, кто их "
            "читает." % name)
    if was != list(header):
        raise RuntimeError(
            "%s: шапка разошлась с той, которую читает доска.\n"
            "  доска ждёт:  %s\n  загрузчик даёт: %s\nФайл не переписан."
            % (name, ",".join(was), ",".join(header)))
    had = _prev_keys(name, header[0])
    now = {r[0] for r in rows}
    lost = sorted(had - now)
    if lost:
        raise RuntimeError(
            "%s: у %s строки БЫЛИ, а сейчас их ноль. Это похоже на "
            "невыполненный запрос, а не на отсутствие данных. Файл не "
            "переписан." % (name, ", ".join(lost)))
    if not rows:
        raise RuntimeError("%s: ноль строк на все сайты, файл не переписан"
                           % name)
    out = ["# %s" % note,
           "# Снято ботом %s. Правки руками будут стёрты следующим прогоном."
           % date.today().isoformat()]
    out += ["# %s" % e for e in extra]
    out.append(",".join(header))
    for r in rows:
        out.append(",".join("" if v is None else str(v) for v in r))
    path = os.path.join(DATA, name)
    tmp = path + ".tmp"
    io.open(tmp, "w", encoding="utf-8", newline="\n").write(
        "\n".join(out) + "\n")
    os.replace(tmp, path)          # упавшая запись не должна стирать данные
    print("  %-22s строк %4d" % (name, len(rows)))


def search_daily(s, since, until):
    rows = []
    for key, prop in sorted(GSC.items()):
        url = ("https://searchconsole.googleapis.com/webmasters/v3/sites/"
               "%s/searchAnalytics/query" % prop.replace(":", "%3A"))
        body = {"startDate": since.isoformat(), "endDate": until.isoformat(),
                "dimensions": ["date"], "rowLimit": 25000}
        r = s.post(url, json=body, timeout=90)
        if r.status_code == 403:
            raise Missing(
                "Search Console отказала по %s (403). Служебный аккаунт не "
                "добавлен читателем этого ресурса." % prop)
        r.raise_for_status()
        for row in r.json().get("rows", []):
            d = row["keys"][0]
            # Порядок колонок — не вкус: доска читает их по именам, но файл
            # читают и глазами, а рядом лежит снятый руками ряд.
            rows.append((key, d,
                         int(row.get("clicks", 0)),
                         int(row.get("impressions", 0)),
                         round(float(row.get("position", 0)), 1)))
    return rows


def search_total(s, since, until):
    """Итог окна ОДНИМ запросом, без разбивки по дням.

    Это эталон со стороны для гейта доски: сумму посуточного ряда считает наш
    код, а этот итог считает сам Search Console. Гейт, сверяющий сумму ряда с
    самой собой, не может покраснеть, и такой у нас уже был.
    """
    out = {}
    for key, prop in sorted(GSC.items()):
        url = ("https://searchconsole.googleapis.com/webmasters/v3/sites/"
               "%s/searchAnalytics/query" % prop.replace(":", "%3A"))
        body = {"startDate": since.isoformat(), "endDate": until.isoformat()}
        r = s.post(url, json=body, timeout=90)
        if r.status_code == 403:
            raise Missing("Search Console отказала по %s (403)." % prop)
        r.raise_for_status()
        rows = r.json().get("rows", [])
        if not rows:
            # Ноль здесь возможен честно: сайт мог не получить ни одного
            # показа за окно. Но тогда и ряд обязан быть пуст, и гейт доски
            # это увидит.
            out[key] = (0, 0, 0.0)
            continue
        row = rows[0]
        out[key] = (int(row.get("clicks", 0)), int(row.get("impressions", 0)),
                    round(float(row.get("position", 0)), 1))
    return out


def ga4_report(s, prop, dims, mets, since, until, limit=100):
    url = ("https://analyticsdata.googleapis.com/v1beta/properties/%s"
           ":runReport" % prop)
    body = {
        "dateRanges": [{"startDate": since.isoformat(),
                        "endDate": until.isoformat()}],
        "dimensions": [{"name": d} for d in dims],
        "metrics": [{"name": m} for m in mets],
        "limit": limit,
    }
    r = s.post(url, json=body, timeout=90)
    if r.status_code == 403:
        raise Missing("GA4 отказала по ресурсу %s (403). Служебный аккаунт "
                      "не добавлен читателем." % prop)
    r.raise_for_status()
    return r.json().get("rows", [])


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    until = date.today() - timedelta(days=1)   # вчера: сегодняшний день неполон
    since = until - timedelta(days=DAYS - 1)
    window = "%s..%s" % (since.isoformat(), until.isoformat())
    try:
        creds = _creds()
        props = _ga4_properties()
    except Missing as e:
        print("НЕ НАСТРОЕНО:", e)
        return 2                                # отличается от сбоя (1)
    _same_sites(props)
    s = _session(creds)

    # Снимок берётся за 28 суток, а не за 90. Это не мелочь: `views` из него —
    # ЧИСЛИТЕЛЬ порога рекламной сети, а порог у сети МЕСЯЧНЫЙ. Снять то же
    # число за квартал и положить в ту же клетку значит утроить его молча.
    s28 = until - timedelta(27)
    win28 = "%s..%s" % (s28.isoformat(), until.isoformat())

    print("окно", window, "· снимок", win28)
    totals = search_total(s, since, until)
    check = "СВЕРКА: окно %s · итог отдельным запросом, без разбивки по дням: %s" % (
        window, " ".join("%s=%d/%d/%.1f" % ((k,) + v)
                         for k, v in sorted(totals.items())))
    _write("daily_search.csv",
           ["site", "day", "clicks", "impressions", "position"],
           search_daily(s, since, until),
           "Посуточный ряд Google Search Console, окно " + window,
           extra=[check])

    prev_snap = _prev_rows("ga4_snapshot.csv")
    ch, snap = [], []
    for key, prop in sorted(props.items()):
        for row in ga4_report(s, prop, ["sessionDefaultChannelGroup"],
                              ["sessions", "engagedSessions",
                               "engagementRate", "averageSessionDuration"],
                              since, until):
            m = row["metricValues"]
            ch.append((key, row["dimensionValues"][0]["value"],
                       int(float(m[0]["value"])), int(float(m[1]["value"])),
                       _pct(m[2]["value"]), _secs(m[3]["value"])))

        tot = ga4_report(s, prop, [], ["screenPageViews", "totalUsers",
                                       "userEngagementDuration", "eventCount"],
                         s28, until)
        if not tot:
            raise RuntimeError(
                "%s: итоговый отчёт GA4 вернул ноль строк. У сайта с трафиком "
                "это невыполненный запрос, а не отсутствие данных." % key)
        m = tot[0]["metricValues"]
        views, users = int(float(m[0]["value"])), int(float(m[1]["value"]))
        if not users:
            raise RuntimeError("%s: ноль пользователей за %s — делить не на "
                               "что, файл не переписан" % (key, win28))
        # Страницы, у которых был хоть один просмотр. Предел в 1000 строк
        # осознан: у обоих сайтов страниц втрое меньше, но если корпус
        # вырастет, счёт замолчит — поэтому упираемся в предел ЯВНО.
        pages = ga4_report(s, prop, ["pagePath"], ["screenPageViews"],
                           s28, until, 1000)
        if len(pages) >= 1000:
            raise RuntimeError("%s: страниц ровно предел выборки (1000) — "
                               "счёт «страниц с просмотрами» занижен" % key)
        seen = sum(1 for r in pages
                   if int(float(r["metricValues"][0]["value"])) > 0)
        # pages_built приходит НЕ из GA4: это число собранных страниц сайта,
        # и знает его только сборка сайта. Переносим прежнее значение и
        # говорим об этом в шапке файла — иначе знаменатель охвата будет
        # стареть незаметно, а доля расти сама собой.
        built = (prev_snap.get(key) or {}).get("pages_built", "")
        if not built:
            raise RuntimeError(
                "%s: в прежнем снимке нет pages_built, а из GA4 его не "
                "узнать. Файл не переписан." % key)
        snap.append((key, views, users, round(views / users, 2),
                     _secs(float(m[2]["value"]) / users),
                     int(float(m[3]["value"])), seen, built))

    _write("ga4_channels.csv",
           ["site", "channel", "sessions", "engaged", "engagement_rate",
            "avg_time"],
           ch, "GA4 Traffic acquisition, окно " + window)
    _write("ga4_snapshot.csv",
           ["site", "views", "users", "views_per_user", "avg_engagement",
            "events", "pages_with_views", "pages_built"],
           snap,
           "GA4 итог за 28 суток (порог рекламной сети месячный), окно "
           + win28 + ". Колонка pages_built НЕ из GA4: перенесена из "
           "прежнего снимка, её обновляет сборка сайта")
    print("готово")
    return 0


if __name__ == "__main__":
    sys.exit(main())
