# -*- coding: utf-8 -*-
"""Свежие данные для доски: Search Console и GA4 через служебный аккаунт.

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
  * Он не хранит ключ. Ключ приходит из переменной окружения, которую
    заполняет секрет репозитория, и в файлы не попадает.

Настройка со стороны владельца (разово, руками — я к ключам не прикасаюсь):
  1. В Google Cloud завести проект и СЛУЖЕБНЫЙ АККАУНТ, скачать ключ JSON.
  2. Включить два API: Search Console API и Google Analytics Data API.
  3. В Search Console добавить адрес служебного аккаунта читателем КАЖДОГО
     ресурса; в GA4 — читателем ресурса (Admin -> Property access management).
  4. В репозитории завести секрет GOOGLE_SA_JSON — содержимое файла ключа
     целиком, и секрет GA4_PROPERTIES вида
     "mileagecurve=123456789,gspaytables=987654321" (числовые id ресурсов
     GA4, они в Admin -> Property details, НЕ измерительные G-XXXX).

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


class Missing(Exception):
    """Не настроено. Это не сбой сети и не ноль — это отсутствие доступа, и
    молча превращать его в пустые данные нельзя."""


def _creds():
    raw = os.environ.get("GOOGLE_SA_JSON", "").strip()
    if not raw:
        raise Missing(
            "нет GOOGLE_SA_JSON. Данные НЕ обновлены и НЕ затёрты; доска "
            "покажет прежние числа с их прежней датой.")
    try:
        info = json.loads(raw)
    except ValueError as e:
        raise Missing("GOOGLE_SA_JSON не разбирается как JSON: %s" % e)
    from google.oauth2 import service_account          # noqa: E402
    return service_account.Credentials.from_service_account_info(
        info, scopes=SCOPES)


def _session(creds):
    import google.auth.transport.requests as gr        # noqa: E402
    s = gr.AuthorizedSession(creds)
    s.headers["User-Agent"] = "bilingoplus-board/1.0"
    return s


def _ga4_properties():
    raw = os.environ.get("GA4_PROPERTIES", "").strip()
    if not raw:
        raise Missing("нет GA4_PROPERTIES вида key=123456789,key=987654321")
    out = {}
    for part in raw.split(","):
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        out[k.strip()] = v.strip()
    if not out:
        raise Missing("GA4_PROPERTIES пуст после разбора: %r" % raw)
    return out


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


def _write(name, header, rows, note):
    """Записать файл, если в нём не пропал ни один прежний сайт."""
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
           % date.today().isoformat(),
           ",".join(header)]
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
            rows.append((key, d, int(row.get("impressions", 0)),
                         int(row.get("clicks", 0)),
                         round(float(row.get("position", 0)), 1)))
    return rows


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
    s = _session(creds)

    print("окно", window)
    _write("daily_search.csv",
           ["site", "date", "impressions", "clicks", "position"],
           search_daily(s, since, until),
           "Посуточный ряд Google Search Console, окно " + window)

    ch, pg = [], []
    for key, prop in sorted(props.items()):
        for row in ga4_report(s, prop, ["sessionDefaultChannelGroup"],
                              ["sessions", "engagedSessions",
                               "averageSessionDuration"], since, until):
            ch.append((key, row["dimensionValues"][0]["value"],
                       row["metricValues"][0]["value"],
                       row["metricValues"][1]["value"],
                       round(float(row["metricValues"][2]["value"]), 1)))
        for row in ga4_report(s, prop, ["pagePath"],
                              ["screenPageViews", "totalUsers",
                               "userEngagementDuration"], since, until, 25):
            pg.append((key, row["dimensionValues"][0]["value"],
                       row["metricValues"][0]["value"],
                       row["metricValues"][1]["value"],
                       round(float(row["metricValues"][2]["value"]), 1)))

    _write("ga4_channels.csv",
           ["site", "channel", "sessions", "engaged", "avg_seconds"],
           ch, "GA4 Traffic acquisition, окно " + window)
    _write("ga4_pages.csv",
           ["site", "path", "views", "users", "avg_engagement"],
           pg, "GA4 топ страниц по просмотрам, окно " + window)
    print("готово")
    return 0


if __name__ == "__main__":
    sys.exit(main())
