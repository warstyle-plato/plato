"""ВРЕМЕННАЯ диагностика лота 178-ФЗ Росэлторга (удаляется до PR).

Карточку читает ядро (`/auctions/source-page`, ключ команды), разбор — наш
`RoseltorgAdapter` здесь же, на раннере. Печатаются только поля лота и шаг
отсева; страница в репозиторий не кладётся.
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BASE = os.environ.get("BASE", "https://developaid.ru")
KEY = os.environ.get("KEY", "")
LOT = os.environ.get("LOT_URL", "https://www.roseltorg.ru/procedure/178fz30102600019/1")


def core_page(url: str) -> dict:
    q = urllib.parse.urlencode({"url": url, "key": KEY})
    with urllib.request.urlopen(f"{BASE}/auctions/source-page?{q}", timeout=120) as r:
        return json.loads(r.read().decode("utf-8"))


def main() -> None:
    from auction_search.adapters.roseltorg import RoseltorgAdapter, _RoseltorgHTML
    from auction_search.parsing import deadline_is_current

    page = core_page(LOT)
    print("HTTP", page.get("http_status"), page.get("bytes"), page.get("reason", ""))
    html = page.get("body") or ""
    RoseltorgAdapter._read = classmethod(lambda cls, url, timeout, **kw: html)
    lot = RoseltorgAdapter().fetch_lot(LOT)
    for name in ("title", "lot_kind", "address", "cadastral_numbers", "land_area_sqm",
                 "building_area_sqm", "start_price_rub", "deposit_rub", "procedure_type",
                 "status", "application_start", "application_deadline", "auction_date",
                 "seller", "organizer", "origin"):
        print(f"{name}: {getattr(lot, name, None)}")
    print("trading_section:", lot.raw.get("trading_section"))
    print("lot_region_code:", lot.raw.get("lot_region_code"))
    ad = RoseltorgAdapter
    steps = [
        ("вид лота девелоперский", lot.lot_kind in ad.RELEVANT_KINDS),
        ("распоряжение имуществом", ad._is_asset_disposal(lot)),
        ("Москва подтверждена", ad._confirmed_moscow(lot)),
        ("статус рабочий", ad._is_actionable_status(lot.status)),
        ("срок подачи идёт", deadline_is_current(lot.application_deadline)),
    ]
    for label, ok in steps:
        print(f"шаг «{label}»: {'да' if ok else 'НЕТ'}")
    text = lot.raw.get("page_text") or ""
    print("--- текст карточки (первые 3500) ---")
    print(text[:3500])
    parser = _RoseltorgHTML()
    parser.feed(html)
    print("--- ссылки не на процедуры (разделы) ---")
    seen = set()
    for href, title in parser.links:
        if "/procedure/" in href or href in seen or not href.startswith(("/", "https://www.roseltorg")):
            continue
        seen.add(href)
        if re.search(r"search|imuschestvo|privat|178|torgi", href, re.I):
            print(href, "|", title[:80])
    # Кандидаты страницы поиска: сколько ссылок 178fz на каждой.
    for url in (
        "https://www.roseltorg.ru/procedures/search?tags%5B%5D=%D0%BF%D1%80%D0%B8%D0%B2%D0%B0%D1%82%D0%B8%D0%B7%D0%B0%D1%86%D0%B8%D1%8F",
        "https://www.roseltorg.ru/procedures/search?query_field=178fz",
        "https://www.roseltorg.ru/procedures/search?sale=1&source%5B%5D=178fz",
        "https://www.roseltorg.ru/procedures/search?source%5B%5D=27",
        "https://www.roseltorg.ru/imuschestvo/privatizaciya",
        "https://www.roseltorg.ru/imuschestvo",
    ):
        try:
            got = core_page(url)
        except Exception as exc:  # noqa: BLE001
            print("ПОИСК", url, "ошибка", exc)
            continue
        body = got.get("body") or ""
        links = sorted(set(re.findall(r"/procedure/(178fz[0-9a-z]+)", body, re.I)))
        allp = len(set(re.findall(r"/procedure/([0-9a-z]+)", body, re.I)))
        print("ПОИСК", url, "HTTP", got.get("http_status"), "процедур", allp,
              "из них 178fz", len(links), links[:5], got.get("reason", ""))
    print("--- формы фильтров первой страницы поиска (name=) ---")
    try:
        got = core_page("https://www.roseltorg.ru/procedures/search")
        names = sorted(set(re.findall(r'name="([^"]{2,40})"', got.get("body") or "")))
        print(names[:120])
        for m in re.finditer(r'name="(source\[\]|sale|law\[\]|type\[\]|section\[\])"[^>]*value="([^"]*)"[^<]{0,200}', got.get("body") or ""):
            print(m.group(0)[:200])
    except Exception as exc:  # noqa: BLE001
        print("форма", exc)
    for host in ("https://www.roseltorg.ru/", "https://torgi.gov.ru/new/api/public/lotcards/search?size=1"):
        try:
            with urllib.request.urlopen(host, timeout=20) as r:
                print("С РАННЕРА", host, r.status)
        except Exception as exc:  # noqa: BLE001
            print("С РАННЕРА", host, type(exc).__name__, exc)


if __name__ == "__main__":
    main()
