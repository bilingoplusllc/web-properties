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
import time
import concurrent.futures as cf
import threading
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

# Карты сайтов — единственный список того, что мы вообще опубликовали. Он же
# знаменатель доли индексации: до сих пор знаменатель (353 и 165) был вбит
# руками в ЧЕТЫРЁХ местах сразу и ни одна пара не сверялась.
SITEMAP = {
    "mileagecurve": "https://mileagecurve.com/sitemap.xml",
    "gspaytables": "https://gspaytables.com/sitemap.xml",
}

# Сколько адресов опрашиваем за прогон НА РЕСУРС.
#
# Ограничивает нас НЕ квота. Квота Google — 2000 в сутки и 600 в минуту на
# ресурс, и в неё оба корпуса влезают целиком. Ограничивает ВРЕМЯ: метод
# отвечает примерно за шесть секунд на адрес — он делает живой просмотр
# индекса, а не читает готовую сводку. Первый полный прогон занял 57 минут на
# 518 адресов, и это слишком: получасовой шаг легче отвалится посреди работы,
# а в логе всё это время тишина.
#
# Лечится это НЕ урезанием охвата, а параллельностью: последовательный опрос
# давал 9 запросов в минуту при разрешённых 600 — полтора процента от того,
# что позволено. Восемь потоков дают около 80 в минуту, и оба корпуса (518
# адресов) снимаются целиком примерно за семь минут.
#
# Предел на прогон всё равно нужен — на вырост. Обход идёт ПО КРУГУ: первыми
# те, кого проверяли раньше всех. Сегодня оба корпуса в предел влезают, то
# есть перепись каждый день полная; когда сайт перерастёт предел, круг
# растянется на несколько суток. Перепись от этого не портится: у каждого
# адреса своя дата проверки, и доска печатает ДИАПАЗОН дат, а не выдаёт
# многодневный срез за сегодняшний.
INSPECT_PER_SITE = 400

# И предел по времени, независимо от числа адресов: шаг, который может идти
# сколько угодно, однажды пойдёт бесконечно. Что не успели — снимется
# следующим прогоном, и недобор называется вслух.
INSPECT_MINUTES = 15

# Сколько запросов держим в воздухе. Восемь — это ~80 запросов в минуту при
# разрешённых 600 на ресурс: с запасом в семь раз. Больше брать незачем, а
# соседний пул соединений у requests по умолчанию тоже равен десяти.
INSPECT_THREADS = 8


class Missing(Exception):
    """Не настроено. Это не сбой сети и не ноль — это отсутствие доступа, и
    молча превращать его в пустые данные нельзя."""


class Quota(Exception):
    """Квота источника исчерпана. Это НЕ отказ и не ноль: часть данных снята,
    остальное снимется следующим прогоном. Обрывать по этой причине весь
    прогон нельзя, а молчать о недоборе — тем более."""


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
    a, b, c = set(GSC), set(props), set(SITEMAP)
    if not (a == b == c):
        raise RuntimeError(
            "списки сайтов разошлись: Search Console %s, GA4 %s, карты сайтов "
            "%s. Пока они не совпадут, доска сравнивала бы разное."
            % (sorted(a), sorted(b), sorted(c)))


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


def _merge_history(name, header, fresh, key_cols=2):
    """Дописать окно к ряду, а НЕ заменить ряд окном.

    Загрузчик тянет последние DAYS суток и раньше переписывал файл целиком.
    Пока сайты моложе окна, разницы нет — окно покрывает всю их жизнь. Дальше
    начинается тихая потеря: у mileagecurve (запуск 12.08.2026) первые сутки
    с показами выпадают из файла 12.11.2026, у gspaytables — 25.11.2026. С
    этого дня «с запуска» считается по обрезанному слева ряду и уменьшается
    само по себе, сутки за сутками. Ни один гейт этого не видит: все они
    сверяют окно с итогом за то же окно.

    Свежая строка вытесняет прежнюю за те же сутки — Search Console
    пересчитывает последние дни, и новое значение вернее. Всё, что старше
    окна, остаётся нетронутым.
    """
    path = os.path.join(DATA, name)
    prev = []
    if os.path.exists(path):
        with io.open(path, encoding="utf-8") as f:
            body = [l.rstrip("\n") for l in f if not l.startswith("#")]
        if body:
            was = [c.strip() for c in body[0].split(",")]
            if was != list(header):
                raise RuntimeError(
                    "%s: шапка прежнего файла %s не совпадает с новой %s — "
                    "сливать нечего." % (name, ",".join(was), ",".join(header)))
            prev = [tuple(l.split(",")) for l in body[1:] if l]
    by_key = {tuple(r[:key_cols]): tuple(str(v) for v in r) for r in prev}
    before = len(by_key)
    for r in fresh:
        by_key[tuple(str(v) for v in r[:key_cols])] = tuple(
            "" if v is None else str(v) for v in r)
    if len(by_key) < before:
        raise RuntimeError(
            "%s: после слияния строк стало МЕНЬШЕ (%d против %d). История не "
            "должна укорачиваться никогда." % (name, len(by_key), before))
    print("  %-22s было %d, стало %d (+%d)"
          % (name, before, len(by_key), len(by_key) - before))
    return [by_key[k] for k in sorted(by_key)]


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


def _csv_safe(v):
    """Запятая в значении разорвала бы строку: файл пишется склейкой через ",".

    Это не теоретическая опасность. coverageState приходит человекочитаемой
    строкой, и среди настоящих её значений есть «Duplicate, Google chose
    different canonical than user» — запятая внутри поля.
    """
    return str(v or "").replace(",", " ·").replace("\n", " ").strip()


def _sitemap_urls(url, depth=0):
    """Адреса из карты сайта. Индекс карт разворачивается рекурсивно."""
    import xml.etree.ElementTree as ET                 # noqa: E402
    import requests                                    # noqa: E402
    if depth > 3:
        raise RuntimeError("карты сайтов вложены глубже трёх уровней: %s" % url)
    r = requests.get(url, timeout=60,
                     headers={"User-Agent": "bilingoplus-board/1.0"})
    r.raise_for_status()
    root = ET.fromstring(r.content)
    ns = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
    if root.tag == ns + "sitemapindex":
        out = []
        for loc in root.findall(ns + "sitemap/" + ns + "loc"):
            out += _sitemap_urls((loc.text or "").strip(), depth + 1)
        return out
    locs = [(e.text or "").strip()
            for e in root.findall(ns + "url/" + ns + "loc") if (e.text or "").strip()]
    if not locs:
        # Пустая карта — это отказ сервера или сломанная сборка, а не сайт из
        # нуля страниц. Принять её за ноль значит объявить сайт исчезнувшим.
        raise RuntimeError("карта %s не дала ни одного адреса" % url)
    return locs


_LOCAL = threading.local()


def _thread_session(sessions):
    """Своя сессия на КАЖДЫЙ поток.

    requests.Session потокобезопасной не объявлена, и делить одну на восемь
    потоков — приглашение к редкой ошибке, которая проявится однажды и не
    воспроизведётся. Учётные данные при этом общие: их обновление google-auth
    сам берёт под замок.
    """
    s = getattr(_LOCAL, "s", None)
    if s is None:
        s = _LOCAL.s = _session(sessions)
    return s


def inspect_url(sessions, prop, url):
    """Состояние ОДНОГО адреса в индексе Google.

    Сводки «сколько страниц в индексе» Search Console не отдаёт ни одним
    методом — только поадресно, этим. Считаем по полю `verdict`: оно ЕДИНСТВЕННОЕ
    здесь настоящий enum (PASS / FAIL / NEUTRAL / PARTIAL / UNSPECIFIED).
    Соседнее `coverageState` — человекочитаемая строка без объявленного набора
    значений, вдобавок переводимая параметром languageCode; строить на ней
    арифметику значит считать по тексту, который Google вправе переписать.
    Мы её сохраняем, но только чтобы человек мог прочитать причину.
    """
    r = _thread_session(sessions).post(
        "https://searchconsole.googleapis.com/v1/urlInspection/index:inspect",
               json={"inspectionUrl": url, "siteUrl": prop,
                     "languageCode": "en-US"},
               timeout=90)
    if r.status_code == 403:
        raise Missing(
            "URL Inspection отказала по %s (403). Служебному аккаунту нужен "
            "уровень доступа Full — Restricted для этого метода не годится."
            % prop)
    if r.status_code == 429:
        raise Quota("квота URL Inspection исчерпана на %s" % prop)
    r.raise_for_status()
    return (r.json().get("inspectionResult") or {}).get("indexStatusResult") or {}


def index_census(creds, today):
    """Перепись индексации: по строке на КАЖДЫЙ опубликованный адрес.

    Три величины, ради которых она существует, выводятся из ДОКУМЕНТИРОВАННЫХ
    полей, а не из перевода строки причины:

      в индексе          verdict == PASS
      обошёл и не взял   verdict != PASS, при этом lastCrawlTime ЕСТЬ
      нашёл и не обошёл  verdict != PASS, lastCrawlTime отсутствует

    Присутствие lastCrawlTime документировано: «Absent if the URL was never
    crawled successfully». Разница между этими двумя — разница между приговором
    содержанию и очередью обхода, и чинятся они противоположным.

    Адрес, которого в карте больше нет, из переписи ВЫПАДАЕТ: иначе удалённые
    страницы вечно раздували бы знаменатель.
    """
    prev = _prev_index_rows()
    sessions = creds
    rows, notes = [], []
    for key, prop in sorted(GSC.items()):
        urls = _sitemap_urls(SITEMAP[key])
        # По кругу: первыми те, кого проверяли раньше всех. Пустая дата
        # сортируется первой — это «ни разу не смотрели». Адрес добавлен
        # вторым ключом не для красоты: без него порядок при РАВНЫХ датах
        # держится порядком карты, и первый же прогон после полной переписи
        # брал бы одну и ту же голову списка, а хвост не обновлялся бы никогда.
        order = sorted(urls, key=lambda u: (prev.get((key, u), ("",) * 8)[7], u))
        take = order[:INSPECT_PER_SITE]
        if len(take) < len(order):
            notes.append("%s: адресов %d, за прогон берём %d — остальные "
                         "в следующие прогоны" % (key, len(order), len(take)))
        fresh, stopped = {}, None
        started = time.monotonic()
        done = 0
        with cf.ThreadPoolExecutor(max_workers=INSPECT_THREADS) as pool:
            futures = {pool.submit(inspect_url, sessions, prop, u): u
                       for u in take}
            for fut in cf.as_completed(futures):
                u = futures[fut]
                done += 1
                try:
                    st = fut.result()
                except Quota as e:
                    stopped = stopped or str(e)
                    continue
                fresh[u] = (
                    key, u,
                    _csv_safe(st.get("verdict") or "VERDICT_UNSPECIFIED"),
                    _csv_safe(st.get("coverageState")),
                    _csv_safe(st.get("pageFetchState")),
                    _csv_safe(st.get("robotsTxtState")),
                    _csv_safe((st.get("lastCrawlTime") or "")[:10]),
                    today.isoformat(),
                )
                if done % 50 == 0 or done == len(take):
                    # Полчаса тишины в логе — это то, из-за чего начинают
                    # гадать, завис прогон или нет.
                    print("  перепись %s: %d из %d, %.0f c"
                          % (key, done, len(take),
                             time.monotonic() - started), flush=True)
                if time.monotonic() - started > INSPECT_MINUTES * 60:
                    stopped = stopped or ("предел времени %d мин"
                                          % INSPECT_MINUTES)
                    for f2 in futures:
                        f2.cancel()
        if stopped:
            notes.append("%s: %s; опрошено %d из %d"
                         % (key, stopped, len(fresh), len(take)))
        gone = sum(1 for (k, u) in prev if k == key and u not in set(urls))
        if gone:
            notes.append("%s: %d адресов ушли из карты и выпали из переписи"
                         % (key, gone))
        for u in urls:
            if u in fresh:
                rows.append(fresh[u])
            elif (key, u) in prev:
                rows.append(prev[(key, u)])
            else:
                # НИ РАЗУ не опрошен. Это не «нет в индексе» — это «не смотрели»,
                # и пустая дата проверки отличает одно от другого.
                rows.append((key, u, "", "", "", "", "", ""))
    for n in notes:
        print("  перепись:", n)
    return rows


def _prev_index_rows():
    path = os.path.join(DATA, "index_state.csv")
    if not os.path.exists(path):
        return {}
    out = {}
    with io.open(path, encoding="utf-8") as f:
        body = [l.rstrip("\n") for l in f if not l.startswith("#")]
    for line in body[1:]:
        if not line:
            continue
        p = line.split(",")
        if len(p) == 8:
            out[(p[0], p[1])] = tuple(p)
    return out


def search_by(s, dim, since, until, limit=250):
    """Разрез поискового ряда по ЗАПРОСАМ или по СТРАНИЦАМ.

    Посуточный ряд отвечает «сколько», но не отвечает «за что». Пока его не
    было, любой разговор про то, почему сайт стоит на 26-м месте, был
    гаданием: мы видели итог и не видели ни одного запроса, по которому он
    сложился.

    Google подрезает выдачу сам: часть запросов он не отдаёт вовсе (редкие,
    способные выдать человека). Поэтому сумма по этому разрезу МЕНЬШЕ итога
    из посуточного ряда, и это не ошибка — это анонимизация. Доля, которую
    удалось увидеть, печатается рядом.
    """
    rows = []
    for key, prop in sorted(GSC.items()):
        url = ("https://searchconsole.googleapis.com/webmasters/v3/sites/"
               "%s/searchAnalytics/query" % prop.replace(":", "%3A"))
        body = {"startDate": since.isoformat(), "endDate": until.isoformat(),
                "dimensions": [dim], "rowLimit": limit}
        r = s.post(url, json=body, timeout=90)
        if r.status_code == 403:
            raise Missing("Search Console отказала по %s (403)." % prop)
        r.raise_for_status()
        for row in r.json().get("rows", []):
            rows.append((key, _csv_safe(row["keys"][0]),
                         int(row.get("impressions", 0)),
                         int(row.get("clicks", 0)),
                         round(float(row.get("ctr", 0)) * 100, 2),
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
    SEARCH_HEAD = ["site", "day", "clicks", "impressions", "position"]
    _write("daily_search.csv", SEARCH_HEAD,
           _merge_history("daily_search.csv", SEARCH_HEAD,
                          search_daily(s, since, until)),
           "Посуточный ряд Google Search Console. Ряд НАКАПЛИВАЕТСЯ; каждый "
           "прогон дописывает окно " + window,
           extra=[check])

    prev_snap = _prev_rows("ga4_snapshot.csv")
    # Разрезы «за что» — по запросам и по страницам. Без них разговор о том,
    # почему сайт стоит на 26-м месте, остаётся гаданием.
    for _name, _dim, _col in (("search_queries.csv", "query", "query"),
                              ("search_pages.csv", "page", "page")):
        _rows = search_by(s, _dim, since, until)
        _shown = sum(r[2] for r in _rows)
        _all = sum(v[1] for v in totals.values())
        _write(_name, ["site", _col, "impressions", "clicks", "ctr", "position"],
               _rows,
               "Разрез Search Console по %s, окно %s. Показов в разрезе %d из "
               "%d в итоге (%.0f%%): остальное Google не отдаёт по "
               "анонимизации, и это не потеря данных, а её предел"
               % (_col, window, _shown, _all,
                  (_shown / _all * 100) if _all else 0))

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
    # Перепись индексации идёт ПОСЛЕДНЕЙ и своим отказом не роняет уже снятое:
    # поисковый ряд и GA4 к этому месту записаны. Отказ печатается словами, а
    # доска покажет прежнюю перепись с её прежней датой — как и всё остальное.
    try:
        _write("index_state.csv",
               ["site", "url", "verdict", "coverage", "fetch_state", "robots",
                "last_crawl", "checked"],
               index_census(creds, until + timedelta(days=1)),
               "Перепись индексации по адресам карты сайта; обновляется ПО "
               "КРУГУ, у каждого адреса своя дата проверки. Считать по verdict "
               "(enum), НЕ по coverage: coverage — человекочитаемая строка без "
               "объявленного набора значений")
    except (Missing, RuntimeError) as e:
        print("ПЕРЕПИСЬ ИНДЕКСАЦИИ НЕ СНЯТА:", e)

    print("готово")
    return 0


if __name__ == "__main__":
    sys.exit(main())
