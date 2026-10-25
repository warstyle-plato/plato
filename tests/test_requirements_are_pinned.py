"""Прод и тесты ставят точные версии, а не «последние на сегодня».

requirements.in — что нужно приложению (нижние границы и причины);
requirements.txt — точные версии всех пакетов с контрольными суммами, его
ставят образ и CI. Без него прод при каждой сборке молча брал свежие версии,
а PR Dependabot ничего не меняли в том, что реально стоит на проде.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# pycel (только тесты) требует networkx<2.7, pymupdf на проде получает 3.x.
# Других расхождений быть не должно: тесты проверяют версии прода.
ALLOWED_DIVERGENCE = {"networkx"}

_PIN = re.compile(r"^([A-Za-z0-9_.\-]+)==([^\s\\]+)", re.M)


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def pins(text: str) -> dict[str, str]:
    return {_norm(n): v for n, v in _PIN.findall(text)}


def unpinned_lines(text: str) -> list[str]:
    """Строки-требования без `==` или без контрольной суммы."""
    bad = []
    for block in re.split(r"\n(?=\S)", text):
        head = block.split("\n", 1)[0].strip()
        if not head or head.startswith("#") or head.startswith("-"):
            continue
        if "==" not in head or "--hash=sha256:" not in block:
            bad.append(head)
    return bad


def declared(in_text: str) -> set[str]:
    names = set()
    for line in in_text.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        names.add(_norm(re.split(r"[\[<>=!~;\s]", line, 1)[0]))
    return names


def _read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def test_every_installed_package_is_exact_and_hashed():
    for name in ("requirements.txt", "requirements-dev.txt"):
        text = _read(name)
        assert "pip-compile" in text, f"{name} собран не pip-compile"
        assert unpinned_lines(text) == [], name


def test_the_lock_is_not_behind_its_input():
    assert declared(_read("requirements.in")) <= set(pins(_read("requirements.txt")))
    assert declared(_read("requirements-dev.in")) <= set(pins(_read("requirements-dev.txt")))


def test_tests_run_on_the_versions_of_prod():
    prod, dev = pins(_read("requirements.txt")), pins(_read("requirements-dev.txt"))
    assert set(prod) <= set(dev), "тестам не хватает пакетов прода"
    differ = {k for k in prod if prod[k] != dev[k]}
    assert differ <= ALLOWED_DIVERGENCE, {k: (prod[k], dev[k]) for k in differ}


def test_the_image_installs_the_lock():
    assert re.search(r"pip install[^\n]*(\\\n[^\n]*)*-r requirements\.txt", _read("Dockerfile"))


def test_the_checks_catch_a_loose_or_stale_lock():
    # Сторож обязан падать на подделке, иначе он ничего не доказывает.
    assert unpinned_lines("fastapi>=0.110\n") == ["fastapi>=0.110"]
    assert unpinned_lines("fastapi==1.0\n    # via -r x\n") == ["fastapi==1.0"]
    assert unpinned_lines("fastapi==1.0 \\\n    --hash=sha256:ab\n") == []
    assert declared("newpkg>=1  # причина\n") - set(pins("fastapi==1.0\n")) == {"newpkg"}
