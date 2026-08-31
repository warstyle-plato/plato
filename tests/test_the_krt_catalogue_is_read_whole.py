"""Каталог КРТ прочитан целиком — или сказано, что не целиком.

Официальный хост krt.mos.ru время от времени роняет TCP, и на этот случай у
чтения есть запасной путь через постраничный рендерер. Обрыв прямого пути
посреди обхода читался как конец каталога: запасной начинает с ПЕРВОЙ
страницы, концом считал «нет новых площадок», — а после частичного прямого
чтения первая же его страница состоит из уже прочитанных. Обход
останавливался на ней, усечённый список писался `complete=bool(rows)` («строки
есть» = «прочитали всё») и жил сутки.

Наружу это выглядит как каталог, в котором просто нет половины площадок:
двадцать две из двадцати семи известных «Планируемых» отсутствовали при
снимке, помеченном полным (сверка с ручной таблицей владельца, 31.08.2026).

Тот же класс ошибки, что «пустой результат проверки — не чисто»: неполный
ответ источника нельзя показывать как его полный ответ.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from market_search import krt_registry as kr  # noqa: E402

_CARD = ('<a href="/projects/{slug}/">{name} Подробнее</a>'
         '<div>Округ: САО</div><div>Район: Тест</div>'
         '<div>Статус: Планируемая</div><div>Площадь: 1,0</div>')

PAGES = 5
PER_PAGE = 2
TOTAL = PAGES * PER_PAGE


def _slugs(page: int) -> tuple[int, ...]:
    return tuple(range(page * PER_PAGE - PER_PAGE + 1, page * PER_PAGE + 1))


def _html(page: int) -> bytes:
    body = "".join(_CARD.format(slug=f"p{n}", name=f"Площадка {n}") for n in _slugs(page))
    more = (f'<div class="show_more" data-url="/projects/?PAGEN_1={page + 1}"></div>'
            if page < PAGES else "")
    return (body + more).encode()


def _markdown(page: int) -> bytes:
    return "".join(
        f"[Площадка {n} Подробнее](https://api.krt.mos.ru/projects/p{n})\n"
        "Округ: САО\n\nРайон: Тест\n\nСтатус: Планируемая\n\nПлощадь: 1,0\n\n"
        for n in _slugs(page)
    ).encode()


def _read(*, direct_breaks_at: int | None) -> tuple[list[str], bool | None, int]:
    """Прочитать подставной каталог. `direct_breaks_at` — страница, на которой
    официальный хост роняет соединение (None — не роняет)."""
    asked: list[str] = []

    def fetch(url: str) -> bytes:
        asked.append(url)
        if url.startswith(kr.JINA_PREFIX):
            tail = url.split("PAGEN_1=")[-1]
            page = int(tail) if tail.isdigit() else 1
            return _markdown(page) if page <= PAGES else b""
        page = int(url.split("PAGEN_1=")[-1]) if "PAGEN_1=" in url else 1
        if direct_breaks_at and page >= direct_breaks_at:
            raise kr.RemoteServiceError("хост уронил соединение")
        return _html(page)

    with tempfile.TemporaryDirectory() as tmp:
        registry = kr.KrtRegistry(Path(tmp), fetch=fetch)
        rows = registry.projects(refresh=True)
        cached = kr.load_json(registry.path) or {}
        return [row.slug for row in rows], cached.get("complete"), len(asked)


def test_a_break_in_the_middle_does_not_truncate_the_catalogue() -> None:
    """Обрыв на третьей странице — не конец каталога на второй.

    Именно этот случай и терял площадки: прямой путь приносил четыре из
    десяти, запасной спрашивал первую страницу, не находил на ней НОВЫХ и
    объявлял обход законченным.
    """
    slugs, complete, _ = _read(direct_breaks_at=3)
    assert len(slugs) == TOTAL, f"прочитано {len(slugs)} из {TOTAL}: {slugs}"
    assert complete is True


def test_the_fallback_alone_reads_every_page() -> None:
    """Хост недоступен с первой страницы — читает только запасной путь."""
    slugs, complete, _ = _read(direct_breaks_at=1)
    assert len(slugs) == TOTAL, f"прочитано {len(slugs)} из {TOTAL}: {slugs}"
    assert complete is True


def test_the_direct_path_alone_reads_every_page() -> None:
    """Хост цел — запасной путь не нужен вовсе."""
    slugs, complete, asked = _read(direct_breaks_at=None)
    assert len(slugs) == TOTAL, f"прочитано {len(slugs)} из {TOTAL}: {slugs}"
    assert complete is True
    assert asked == PAGES, "запасной путь спрашивали зря — хост ответил целиком"


def test_a_truncated_read_is_never_stamped_complete() -> None:
    """Не дочитали — так и записано, и сутки это не живёт.

    Оба пути оборваны после первой страницы: снимок обязан назваться
    неполным, иначе следующий запрос вернёт половину каталога как целое.
    """
    def fetch(url: str) -> bytes:
        if url.startswith(kr.JINA_PREFIX):
            raise kr.RemoteServiceError("рендерер недоступен")
        page = int(url.split("PAGEN_1=")[-1]) if "PAGEN_1=" in url else 1
        if page > 1:
            raise kr.RemoteServiceError("хост уронил соединение")
        return _html(1)

    with tempfile.TemporaryDirectory() as tmp:
        registry = kr.KrtRegistry(Path(tmp), fetch=fetch)
        rows = registry.projects(refresh=True)
        cached = kr.load_json(registry.path) or {}
    assert len(rows) == PER_PAGE
    assert cached.get("complete") is False, "усечённый снимок выдан за полный"
