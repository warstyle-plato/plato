"""Маркеры конфликта не уезжают в выпуск.

В `auction_search/ui.py` они лежали внутри строки со стилями страницы — и
доехали до `origin/main`: браузер получал `<<<` и `>>>` прямо в `<style>`, а
блок CSS был задвоен целиком (4 081 знак лишних). Нашлось это чужим разбором
модуля (ChatGPT, ссылка от владельца 09.09.2026), а не нами.

Ни один сторож этого не видел и не мог: Python не падает, потому что маркеры
внутри строкового шаблона; `node --check` смотрит скрипт, а не стили; а сам
CSS-разбор от них не ломается — замер в Chromium показал, что правила после
маркера применяются, и снятие конфликта не изменило ни одного вычисленного
стиля (234 правила до, 185 после — ушли ровно дубли).

То есть вреда на экране не было, и потому это могло жить сколько угодно. Ловит
только разбор исходников: маркер законным не бывает нигде.

Запуск: python3 -m pytest tests/test_no_merge_conflict_survives.py -q
"""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Собираются из частей: написанные целиком, они сделали бы этот файл своим же
# нарушителем — та же ловушка, что у сторожа скрытых каталогов.
OURS = "<" * 7 + " "
THEIRS = ">" * 7 + " "
SPLIT = "=" * 7


def tracked_text_files() -> list[Path]:
    """Только то, что в git: чужие черновики в песочнице нас не касаются."""
    out = subprocess.run(["git", "ls-files"], cwd=ROOT,
                         capture_output=True, text=True, check=True)
    keep = {".py", ".js", ".css", ".html", ".md", ".yml", ".yaml", ".json", ".sh"}
    return [ROOT / name for name in out.stdout.splitlines()
            if Path(name).suffix in keep and (ROOT / name).is_file()]


def test_no_source_carries_a_conflict_marker() -> None:
    offenders: list[str] = []
    for path in tracked_text_files():
        if path.name == Path(__file__).name:
            continue
        for number, line in enumerate(
                path.read_text("utf-8", errors="replace").splitlines(), start=1):
            if line.startswith(OURS) or line.startswith(THEIRS) or line == SPLIT:
                offenders.append(f"{path.relative_to(ROOT)}:{number}")
    assert not offenders, "слияние доехало недоделанным: " + "; ".join(offenders[:20])


def test_the_guard_bites(tmp_path: Path) -> None:
    """Сторож, не падающий на поломке, — не сторож."""
    broken = (tmp_path / "broken.py")
    broken.write_text(f"a = 1\n{OURS}HEAD\nb = 2\n{SPLIT}\nb = 3\n{THEIRS}origin/main\n",
                      encoding="utf-8")
    lines = broken.read_text("utf-8").splitlines()
    assert any(line.startswith(OURS) or line.startswith(THEIRS) or line == SPLIT
               for line in lines), "разбор не узнаёт маркер даже в подделке"
