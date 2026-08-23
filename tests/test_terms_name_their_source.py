"""У показателя площади в руководстве стоит источник, а не только смысл.

Справка по площадям сначала смешивала три слоя: градостроительные понятия
Москвы, термины проектной документации и экономику девелопера (владелец,
23.08.2026). Снаружи такая справка выглядит верно, а основание у половины строк
другое — и в переписке с городом или с банком ссылаться оказывается не на что.
Та же ошибка, что ловится в модуле НСПД.

Проверяется ровно то, что нельзя проверить глазами один раз и забыть:

* три слоя разведены и названы;
* у каждого показателя стоит источник;
* городская цепочка идёт от СПП, а не от общей площади здания;
* термины DevelopAid прямо помечены как не нормативные.

Запуск: python3 -m pytest tests/test_terms_name_their_source.py -q
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main_registry  # noqa: E402


@pytest.fixture(scope="module")
def guide() -> str:
    """Собранная страница руководства, а не её исходник.

    Часть значений приезжает подстановкой плейсхолдеров, и проверять надо то,
    что человек видит, — иначе тест сойдётся на файле и разойдётся с экраном.
    """
    response = TestClient(main_registry.app).get("/guide")
    assert response.status_code == 200, response.text
    return response.text


def section(guide_html: str) -> str:
    start = guide_html.index('<section id="areas"')
    return guide_html[start:guide_html.index("</section>", start)]


def test_the_three_layers_are_told_apart(guide: str) -> None:
    body = section(guide)
    assert "Градостроительные показатели Москвы" in body
    assert "Показатели проектной документации" in body
    assert "Экономические показатели DevelopAid" in body


def test_every_area_term_names_its_source(guide: str) -> None:
    body = section(guide)
    for term, source in (
        ("СПП", "методика ГлавАПУ"),
        ("Наземная площадь", "методика ГлавАПУ"),
        ("Общая площадь здания", "проектная документация"),
        ("Подземная площадь", "проектная документация"),
        ("ГНС", "финансовая модель DevelopAid"),
        ("Продаваемая площадь", "финансовая модель DevelopAid"),
        ("Коэффициент выхода", "финансовая модель DevelopAid"),
    ):
        assert term in body, term
        assert source in body, source


def test_the_city_chain_starts_from_spp(guide: str) -> None:
    """Плотность, население и соцнагрузка идут от СПП, а не от общей площади."""
    body = section(guide)
    assert "СПП → плотность → население →" in body
    assert "неверное" in body, "ошибочное утверждение названо ошибочным"


def test_our_terms_are_marked_as_ours(guide: str) -> None:
    body = section(guide)
    assert "не термин методики" in body
    assert "нормативными" in body and "не являются" in body


def test_the_guide_does_not_claim_the_city_counts_from_the_total_area(guide: str) -> None:
    """Утверждение может стоять только как пример неверного."""
    for match in re.finditer(r"[^.<>]{0,120}соцнагрузк[^.<>]{0,120}", guide):
        text = match.group(0)
        if "общей площад" in text:
            assert "неверн" in text, text


def test_the_section_is_reachable_from_the_navigation(guide: str) -> None:
    assert 'href="#areas"' in guide
