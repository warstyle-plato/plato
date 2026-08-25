"""Статья расходов приходит на экран с именем, а не сырым ключом.

Во вкладке «Расходы» среди русских названий стояли «resettlement» и
«demolition» — латиницей, строчными (экран владельца, 25.08.2026). Причина
знакомая: страница держала свой словарь имён `capNames`, а статьи «Снос и
демонтаж» и «Расселение» заведены позже и в копию не попали.

Копии больше нет: имена подставляются из движка плейсхолдером, как `VERSION`,
`FIELD_GROUPS` и доли ТЭП. Короткие подписи — не второй список статей, а
переопределения по ключам того же списка: статья без короткой подписи получает
полную, и сырой ключ на экране невозможен по построению.

Запуск: python3 -m pytest tests/test_cost_articles_are_named_once.py -q
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402


def page_names() -> dict[str, str]:
    start = core.PAGE.index("const capNames=") + len("const capNames=")
    return json.loads(core.PAGE[start:core.PAGE.index("};", start) + 1])


def test_every_article_of_the_engine_has_a_name() -> None:
    names = page_names()
    missing = [key for key, _ in core._MODEL_CAPEX_LABELS if not names.get(key)]
    assert not missing, f"статьи доедут до экрана сырым ключом: {missing}"


def test_the_two_that_slipped_through_are_named() -> None:
    names = page_names()
    assert names["demolition"] == "Снос и демонтаж"
    assert names["resettlement"] == "Расселение"


def test_no_name_is_left_in_latin() -> None:
    """Сырой ключ узнаётся по латинице: русские имена её не содержат."""
    for key, name in page_names().items():
        assert name != key, f"{key} показывается сырым ключом"
        assert any("а" <= letter.lower() <= "я" or letter.lower() == "ё" for letter in name), \
            f"имя статьи {key} без единой русской буквы: {name}"


def test_the_page_keeps_no_copy_of_the_list() -> None:
    """Копию негде обновлять, потому что копии нет."""
    source = (ROOT / "main_legacy.py").read_text()
    assert "const capNames=__DEVELOPAID_CAPEX_NAMES__" in source
    assert source.count("const capNames={") == 0, "второй словарь имён на странице"


def test_a_short_name_is_an_override_not_a_second_list() -> None:
    """Короткая подпись — переопределение по ключу того же списка."""
    keys = {key for key, _ in core._MODEL_CAPEX_LABELS}
    stray = set(core.CAPEX_SHORT_NAMES) - keys
    assert not stray, f"короткие имена для несуществующих статей: {stray}"


def test_an_article_without_a_short_name_keeps_the_full_one() -> None:
    names = page_names()
    full = dict(core._MODEL_CAPEX_LABELS)
    for key in full:
        if key not in core.CAPEX_SHORT_NAMES:
            assert names[key] == full[key]
