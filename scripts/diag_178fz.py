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
    from auction_search.adapters.roseltorg import RoseltorgAdapter, _RoseltorgHTML

    tag_share = "tags%5B%5D=%D0%BF%D1%80%D0%BE%D0%B4%D0%B0%D0%B6%D0%B0%20%D0%B4%D0%BE%D0%BB%D0%B8"
    bases = []
    for okato, region in (("45000000000", "Москва"), ("46000000000", "МО")):
        for path in ("imuschestvo/nedvizhimost/zemelnye-uchastki",
                     "imuschestvo/nedvizhimost/kommercheskaya-nedvizhimost",
                     "imuschestvo/nedvizhimost/garazhi"):
            bases.append((region + " " + path.rsplit("/", 1)[-1],
                          f"https://www.roseltorg.ru/{path}?okato%5B%5D={okato}&status%5B%5D=5&status%5B%5D=0"))
        bases.append((region + " доли", f"https://www.roseltorg.ru/search/sale?{tag_share}&okato%5B%5D={okato}"))
    bases.append(("все доли", f"https://www.roseltorg.ru/search/sale?{tag_share}"))
    for label, base in bases:
        for page in (1, 2, 3):
            url = base + (f"&page={page}" if page > 1 else "")
            try:
                got = core_page(url)
            except Exception as exc:  # noqa: BLE001
                print("СПИСОК", label, page, "ошибка", exc)
                break
            body = got.get("body") or ""
            parser = _RoseltorgHTML()
            parser.feed(body)
            titles = {}
            RoseltorgAdapter._remember_titles(url, parser.links, titles)
            print("СПИСОК", label, "стр", page, "HTTP", got.get("http_status"), "процедур", len(titles))
            for proc, title in titles.items():
                print("   ", proc.rsplit("/procedure/", 1)[-1], "|", title[:170])
            if len(titles) < 10:
                break
            # Контекст карточки списка: цена/площадь/регион рядом со ссылкой.
        snippet = re.sub(r"<[^>]+>", " ", body)
        snippet = " ".join(snippet.split())
        i = snippet.find("Лот 1")
        print("   ТЕКСТ СПИСКА:", snippet[i:i + 900] if i >= 0 else snippet[:300])


if __name__ == "__main__":
    main()
