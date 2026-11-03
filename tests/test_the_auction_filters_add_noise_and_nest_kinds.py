"""Фильтры торгов: «с шумом» добавляет лоты к интересным, типы — дерево.

Владелец, 27.09.2026: при «с шумом» интересные лоты «пропадают» — сервер их
отдаёт, но в общем списке по баллу они тонули среди ста шумных без черты. И
список типов шёл «Земля», «Объекты», а затем снова «Продажа земли» на том же
уровне. Стенд гоняет настоящие функции страницы (`page_blocks.run`).
"""

from __future__ import annotations

import json

from auction_search import ui
from auction_search.service import AuctionSearchService
from tests import page_blocks


def _lot(url, *, main, score_hint=0, kind="land_sale"):
    return {"title": f"Лот {url}", "source": {"lot_url": url}, "lot_kind": kind,
            "main_selection": main, "land_area_sqm": 1000 + score_hint,
            "screening": {"development_relevant": True}, "quality": {"accepted": main}}


def _run(prelude: str, tail: str):
    out, _ = page_blocks.run(prelude, tail, page=ui.auctions_page())
    return json.loads(out.strip().splitlines()[-1])


def test_noise_is_added_under_the_interesting_lots_not_mixed_in():
    lots = [_lot(f"n{i}", main=False, score_hint=900) for i in range(5)]
    lots += [_lot("a", main=True), _lot("b", main=True), {**_lot("old", main=True), "main_selection": None}]
    lots[-1].pop("main_selection")
    got = _run("const LOTS=%s;" % json.dumps(lots, ensure_ascii=False),
               "console.log(JSON.stringify(lotFamilies(LOTS).map(f=>[f.lead.source.lot_url,f.main])))")
    order = [url for url, _main in got]
    assert set(order[:3]) == {"a", "b", "old"}, "интересные — первыми, даже с баллом ниже"
    assert all(not main for _url, main in got[3:])
    assert dict(got)["old"] is True, "нет поля — не «шум», а «не сказано»"


def test_the_kind_menu_is_a_tree_without_repeats_on_one_level():
    got = _run("", "console.log(JSON.stringify({tree:AUCTION_KIND_TREE,flat:AUCTION_KIND_OPTIONS}))")
    top = [value for value, _name, _kids in got["tree"]]
    assert top[:2] == ["land", "building"]
    land = dict((value, kids) for value, _name, kids in got["tree"])["land"]
    assert [value for value, _ in land] == ["land_sale", "land_lease", "krt"]
    flat = [value for value, _ in got["flat"]]
    assert len(flat) == len(set(flat)), "один вид — один пункт"
    assert "land" not in flat and "building" not in flat, "группа — не вид лота"


def test_the_page_groups_match_the_server_subjects():
    from auction_search.models import BUILDING_KINDS, LAND_KINDS

    got = _run("", "console.log(JSON.stringify(AUCTION_KIND_TREE))")
    groups = {value: {kid for kid, _ in kids} for value, _name, kids in got}
    assert groups["land"] == {kind.value for kind in LAND_KINDS}
    assert groups["building"] == {kind.value for kind in BUILDING_KINDS}


def test_main_selection_is_the_servers_own_rule():
    rule = AuctionSearchService.in_main_selection
    assert rule({"development_relevant": True}, {"accepted": True}) is True
    assert rule({"development_relevant": True}, {"accepted": False}) is False
    assert rule({"development_relevant": False}, {"accepted": True}) is False
