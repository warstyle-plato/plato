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
    from urllib.parse import urlencode
    for tag in ("продажа доли", "доля в уставном капитале", "уставный капитал"):
        base = "https://www.roseltorg.ru/search/sale?" + urlencode([("tags[]", tag)])
        for suffix in ("", "&page=0", "&page=1", "&page=2", "&page=3"):
            body = core_page(base + suffix).get("body") or ""
            ids = list(dict.fromkeys(re.findall(r"/procedure/([0-9A-Za-z]+)/\d", body)))
            total = re.findall(r"(?:Найдено|найдено|Всего)[^0-9]{0,40}(\d[\d\s]*)", body)
            print("ТЕГ", tag, "|", suffix or "без page", "|", len(ids), ids, "| итог", total[:2])
    for url in ("https://www.roseltorg.ru/search/sale?query_field=%D0%A4%D0%BE%D0%BD%D0%B2%D0%B8%D0%B7%D0%B8%D0%BD%D0%B0",
                "https://www.roseltorg.ru/search/sale?" + urlencode([("tags[]", "продажа доли"), ("sort", "date_published"), ("order", "desc")])):
        body = core_page(url).get("body") or ""
        ids = list(dict.fromkeys(re.findall(r"/procedure/([0-9A-Za-z]+)/\d", body)))
        print("ЗАПРОС", url, "|", ids)


if __name__ == "__main__":
    main()
