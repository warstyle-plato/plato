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


def options(body: str) -> None:
    for m in re.finditer(r'<select[^>]*name="([^"]+)"[^>]*>(.*?)</select>', body, re.S):
        opts = re.findall(r'<option[^>]*value="([^"]*)"[^>]*>([^<]*)<', m.group(2))
        print("SELECT", m.group(1), [(v, t.strip()[:40]) for v, t in opts][:40])
    for m in re.finditer(r'<input[^>]*name="(sale|source\[\]|type\[\]|status\[\]|region\[\]|okato\[\])"[^>]*>', body):
        tag = m.group(0)
        val = re.search(r'value="([^"]*)"', tag)
        lab = body[m.end():m.end() + 300]
        lab = re.sub(r"<[^>]+>", " ", lab)
        print("INPUT", m.group(1), val.group(1) if val else "", "|", " ".join(lab.split())[:60])


def main() -> None:
    from auction_search.adapters.roseltorg import RoseltorgAdapter
    from auction_search.parsing import deadline_is_current

    pages = (
        "https://www.roseltorg.ru/search/sale",
        "https://www.roseltorg.ru/search/sale?sale=1",
        "https://www.roseltorg.ru/search/sale?sale=2",
        "https://www.roseltorg.ru/search/sale?sale=3",
        "https://www.roseltorg.ru/imuschestvo/nedvizhimost/zemelnye-uchastki",
        "https://www.roseltorg.ru/imuschestvo/nedvizhimost/kommercheskaya-nedvizhimost",
        "https://www.roseltorg.ru/search/sale?tags%5B%5D=%D0%BF%D1%80%D0%BE%D0%B4%D0%B0%D0%B6%D0%B0%20%D0%B4%D0%BE%D0%BB%D0%B8",
    )
    found: list[str] = []
    for i, url in enumerate(pages):
        try:
            got = core_page(url)
        except Exception as exc:  # noqa: BLE001
            print("СТРАНИЦА", url, "ошибка", exc)
            continue
        body = got.get("body") or ""
        ids = list(dict.fromkeys(re.findall(r"/procedure/(178fz[0-9a-z]+(?:/\d+)?)", body, re.I)))
        allp = len(set(re.findall(r"/procedure/([0-9a-z]+)", body, re.I)))
        print("СТРАНИЦА", url, "HTTP", got.get("http_status"), "байт", got.get("bytes"),
              "процедур", allp, "178fz", len(ids), ids[:6])
        if i == 0:
            options(body)
            pag = sorted(set(re.findall(r'href="([^"]*page=\d+[^"]*)"', body)))[:5]
            print("ЛИСТАНИЕ", pag)
        for x in ids:
            if x not in found:
                found.append(x)
    print("ВСЕГО 178fz", len(found))
    seen_body = {}
    for pid in found[:45]:
        url = "https://www.roseltorg.ru/procedure/" + (pid if "/" in pid else pid + "/1")
        try:
            html = core_page(url).get("body") or ""
            RoseltorgAdapter._read = classmethod(lambda cls, u, t, _h=html, **kw: _h)
            lot = RoseltorgAdapter().fetch_lot(url)
        except Exception as exc:  # noqa: BLE001
            print("КАРТОЧКА", pid, "ошибка", type(exc).__name__, exc)
            continue
        text = lot.raw.get("page_text") or ""
        tags = re.search(r"Показать полностью(.{0,200})", text)
        reg = re.search(r"\b(\d{2})\.\s*(?:г\.?\s*)?[А-ЯЁ][а-яё -]{2,40}", text[:6000])
        print("КАРТОЧКА", pid, "|", lot.lot_kind.value, "| площадь", lot.land_area_sqm,
              "| цена", lot.start_price_rub, "| до", lot.application_deadline, "|", lot.status,
              "| регион", lot.raw.get("lot_region_code"), "|", (lot.title or "")[:150],
              "| ТЕГИ", (tags.group(1) if tags else "")[:160])


if __name__ == "__main__":
    main()
