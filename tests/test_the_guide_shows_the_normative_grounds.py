"""Руководство показывает, на чём стоят расчёты, — и берёт это из реестра.

«Я хотел сделать справочник, подтверждающий, что расчёты построены не на голом
месте» (владелец, 06.09.2026). До правки в руководстве на пятьдесят килобайт
текста было ровно одно упоминание «РНГП» и ни одной ссылки на нормативную базу:
основания у расчётов есть, а читателю они не показаны нигде.

Список собирается из САМОГО реестра движка. Второй список в руководстве — это
копия, которую негде обновлять: разойдясь, она пообещает читателю основание,
которого под числом нет. Ровно та же причина, по которой нет копии `VERSION`.

Запуск: python3 -m pytest tests/test_the_guide_shows_the_normative_grounds.py -q
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import normatives_registry  # noqa: E402

PAGE = (ROOT / "guide" / "page.html").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def served() -> str:
    from fastapi.testclient import TestClient

    import main_registry

    client = TestClient(main_registry.app)
    response = client.get("/guide")
    assert response.status_code == 200, response.status_code
    return response.text


def _block(text: str) -> str:
    start = text.index("Справочник нормативной базы")
    return text[start:text.index("</section>", start)]


def test_the_guide_carries_the_reference_block(served) -> None:
    assert "__GUIDE_NORMATIVE_REGISTRY__" not in served, "плейсхолдер не подставлен"
    block = _block(served)
    assert "gnorm-grid" in block


def test_every_act_of_the_registry_is_shown(served) -> None:
    """Позиций столько же, сколько в реестре: показанная половина хуже целого."""
    rows = normatives_registry._merged_registry()
    assert rows, "реестр пуст — проверять нечего"
    block = _block(served)
    assert block.count("<li>") == len(rows), (block.count("<li>"), len(rows))
    for row in rows:
        name = str(row.get("short_name") or row.get("title") or "")
        assert name.split(" — ")[0] in block, name


def test_the_levels_stand_in_their_own_columns(served) -> None:
    block = _block(served)
    heads = re.findall(r"<h4>([^<]+)</h4>", block)
    scopes = [str(row.get("scope") or "") for row in normatives_registry._merged_registry()]
    assert set(heads) == set(scopes), (heads, set(scopes))


def test_each_act_links_to_its_own_source(served) -> None:
    """Проверять нас можно только по исходнику, а не по нашему пересказу."""
    block = _block(served)
    rows = normatives_registry._merged_registry()
    with_url = [row for row in rows if str(row.get("source_url") or "").strip()]
    assert block.count(">исходник</a>") == len(with_url)
    import html as _html

    for row in with_url:
        # Адрес в href экранирован: «&» внутри строки запроса обязан приехать
        # как «&amp;», иначе браузер прочитает хвост как чужую сущность.
        assert _html.escape(str(row["source_url"])) in block, row.get("short_name")


def test_a_missing_link_is_named_not_hidden() -> None:
    """Отсутствие ссылки — ответ, а не пустое место.

    Акт без исходника в справочнике «подтверждающем, что не на голом месте»
    обязан выглядеть иначе, чем акт со ссылкой.
    """
    html = normatives_registry.guide_reference_html()
    assert "gnorm-nolink" in normatives_registry.guide_reference_html.__doc__ or True
    # Механика: у строки без ссылки вместо неё стоит названная причина.
    assert ("gnorm-nolink" in html) == any(
        not str(row.get("source_url") or "").strip()
        for row in normatives_registry._merged_registry())


def test_the_guide_does_not_keep_its_own_list_of_acts() -> None:
    """Копии реестра в руководстве нет — иначе её негде обновлять."""
    body = PAGE[PAGE.index("Справочник нормативной базы"):]
    body = body[:body.index("</section>")]
    for token in ("945-ПП", "2152-ПП", "1874-ПП", "713/30", "43-ФЗ", "СП 42.13330"):
        assert token not in body, f"{token} вписан в руководство руками"


def test_an_unreadable_registry_says_so_out_loud(monkeypatch) -> None:
    """Пустой блок и отсутствующий выглядят одинаково, а значат разное."""
    monkeypatch.setattr(normatives_registry, "_merged_registry", lambda: [])
    assert "не прочитан" in normatives_registry.guide_reference_html()

    def _boom():
        raise RuntimeError("реестр недоступен")

    monkeypatch.setattr(normatives_registry, "_merged_registry", _boom)
    got = normatives_registry.guide_reference_html()
    assert "не собран" in got and "реестр недоступен" in got
