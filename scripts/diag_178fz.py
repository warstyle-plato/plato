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
    for pid in ("178fz30102600019/1", "178fz22102600001/1", "21000030950000001703/1"):
        body = core_page("https://www.roseltorg.ru/procedure/" + pid).get("body") or ""
        print("=== КАРТОЧКА", pid)
        for m in re.finditer(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', body, re.S):
            print("LD", " ".join(m.group(1).split())[:3000])
        text = " ".join(re.sub(r"<script.*?</script>|<style.*?</style>|<[^>]+>", " ", body, flags=re.S).split())
        for word in ("Регион", "Местонахождение", "Место нахождения", "Адрес", "Способ проведения",
                     "Организатор торгов", "Площадь", "Категори", "77.", "50."):
            for m in list(re.finditer(re.escape(word), text))[:3]:
                print("ОКОЛО", word, "|", text[max(0, m.start() - 80):m.start() + 220])
    url = ("https://www.roseltorg.ru/imuschestvo/nedvizhimost/zemelnye-uchastki"
           "?okato%5B%5D=46000000000&status%5B%5D=5&status%5B%5D=0")
    body = core_page(url).get("body") or ""
    i = body.find("/procedure/21000030950000001703")
    print("=== РАЗМЕТКА СТРОКИ СПИСКА")
    print(" ".join(body[max(0, i - 2500):i + 2500].split())[:5000])


if __name__ == "__main__":
    main()
