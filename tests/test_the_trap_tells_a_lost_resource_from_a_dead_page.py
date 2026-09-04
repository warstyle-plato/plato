"""Ловушка ошибок отличает не загрузившийся ресурс от сломанной страницы.

Владелец, 04.09.2026 (снимок экрана): «Страница не доработала до конца. ошибка
без описания. страница:0:0». Страница при этом работала — шёл разбор участка.
У события отказа РЕСУРСА нет ни сообщения, ни строки: ловушка слушает фазу
перехвата и видела провал картинки кадастровой подложки (НСПД в ту минуту не
отвечал) ровно так же, как падение скрипта. Ложная тревога такого рода хуже
молчания: человек ищет поломку там, где всё цело.

Запуск: python3 -m pytest tests/test_the_trap_tells_a_lost_resource_from_a_dead_page.py -q
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402

PAGE = core.PAGE


def _trap_script() -> str:
    """Ловушка — отдельный скрипт: берём его целиком, от помощника до конца."""
    start = PAGE.index("function pageFailureBox(){")
    end = PAGE.index("</script>", start)
    return PAGE[start:end]


def test_the_trap_is_its_own_script_before_the_main_one() -> None:
    """Ловушка объявлена раньше основного блока — иначе она молчит там, где нужна."""
    trap = PAGE.index("function pageFailureBox(){")
    assert trap < PAGE.index("const SCENARIOS="), "ловушка уехала за основной скрипт"
    assert "'unhandledrejection'" in PAGE, "оборванная асинхронная работа не ловится"


def _run(cases: str) -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node недоступен")
    program = (
        "const handlers={};\n"
        "const box={id:'pageFailure',style:{},textContent:''};\n"
        "const document={getElementById:id=>id==='pageFailure'?(box.attached?box:null):null,"
        "createElement:()=>{box.attached=true;return box},"
        "body:{insertBefore:()=>{},firstChild:null}};\n"
        "const window={addEventListener:(name,fn)=>{handlers[name]=fn}};\n"
        + _trap_script() + "\n"
        "const said=()=>{const t=box.textContent;box.textContent='';return t};\n"
        + cases +
        "\nprocess.stdout.write(JSON.stringify(out));"
    )
    done = subprocess.run([shutil.which("node"), "-e", program],
                          capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr[:900]
    return json.loads(done.stdout)


def test_a_lost_picture_is_not_a_dead_page() -> None:
    """Картинка без своего обработчика названа ресурсом, а не смертью страницы."""
    got = _run(
        "const out={};\n"
        "handlers.error({target:{tagName:'IMG',src:'/land/map-image?bbox=1,2,3,4'},"
        "message:'',filename:'',lineno:0,colno:0});\n"
        "out.picture=said();\n"
    )
    assert "Не загрузился ресурс страницы: img" in got["picture"], got
    assert "/land/map-image" in got["picture"]
    assert "Страница не доработала" not in got["picture"]
    assert "ошибка без описания" not in got["picture"]


def test_a_resource_the_page_handles_itself_stays_quiet() -> None:
    """У тайлов и карты свой onerror: страница о них позаботилась и говорит сама."""
    got = _run(
        "const out={};\n"
        "handlers.error({target:{tagName:'IMG',src:'/land/tiles/14/1/1.png',onerror:function(){}},"
        "message:'',filename:'',lineno:0,colno:0});\n"
        "out.quiet=said();\n"
    )
    assert got["quiet"] == "", got


def test_a_real_script_error_still_says_the_page_died() -> None:
    """Настоящая поломка скрипта остаётся поломкой, с местом и сообщением."""
    got = _run(
        "const out={};\n"
        "handlers.error({message:'x is not defined',filename:'https://developaid.ru/',"
        "lineno:1200,colno:7});\n"
        "out.script=said();\n"
        "handlers.error({message:'',error:{message:'Cannot read properties of null'},"
        "filename:'',lineno:0,colno:0});\n"
        "out.fallback=said();\n"
    )
    assert "Страница не доработала до конца." in got["script"]
    assert "x is not defined" in got["script"] and "1200:7" in got["script"]
    # Пустое сообщение при настоящей ошибке добирается из самого исключения.
    assert "Cannot read properties of null" in got["fallback"], got


def test_an_unhandled_rejection_speaks_up() -> None:
    """Оборванная асинхронная работа называет себя, а не оставляет тишину."""
    got = _run(
        "const out={};\n"
        "handlers.unhandledrejection({reason:{message:'Failed to fetch'}});\n"
        "out.rejected=said();\n"
    )
    assert "Незавершённая работа страницы." in got["rejected"]
    assert "Failed to fetch" in got["rejected"]
