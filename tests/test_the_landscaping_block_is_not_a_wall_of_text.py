"""Пояснения блока благоустройства меряются, а не оцениваются на глаз.

«Не кажется ли тебе, что текста пояснительного слишком много и возможно его
стоит или сократить, или как-то свернуть в единые пояснения для блока
благоустройство» (владелец, 16.09.2026, снимок экрана). Померено на живой
странице: две вводные благоустройства несли 1732 знака сплошной прозы, из них
928 — справка о нормах ГОРОДА, которая в расчёт не входит вовсе, и около
двухсот — повтор одного и того же в подсказке поля и в подписи под ним.

Свернуть оказалось половиной ответа: «мне кажется тут слишком много текста всё
равно» (16.09.2026). Справка о нормах ГОРОДА уехала в «Настройки класса» — туда,
где правят норматив, который она объясняет, — а из «Вводных» ушла целиком.
Осталось по одному утверждению на место: база у подсказки, состояние у подписи,
двор числом у своего поля. Второй показатель «на метр дома» снят вместе с его
базой: она сведена с ГНС проекта, и два почти равных числа под одним словом
«ГНС» больше не стоят рядом.

Проверяется отрисовкой: в исходнике стена текста выглядит ровно так же, как
короткая подпись, и «на глаз» здесь не мера.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from browser import chromium_or_skip, serve  # noqa: E402

PORT = 18963

# Замеры на живой странице: 1732 знака видимой прозы в начале, 672 после
# сворачивания справки, 245 после её переезда в «Настройки класса». Потолок
# стоит с запасом, но ниже прежних объёмов: он ловит возврат стены, а не каждое
# слово. Числа названы здесь один раз, чтобы отказ мог сказать, с чем сравнивал.
VISIBLE_LIMIT = 400
WAS_BEFORE = 1732
WAS_WITH_FOLD = 672


def _seen(page) -> dict:
    return page.evaluate("""() => {
      document.querySelectorAll('#inputs details').forEach(d=>{ if(!d.querySelector('summary').textContent.includes('Нормы озеленения')) d.open=true; });
      const ids=['landscaping_area_sqm','landscaping_gns_th_per_sqm'];
      let visible=0, folded=0, folds=0;
      ids.forEach(id=>{
        const field=document.getElementById('f_'+id);
        if(!field) return;
        const box=field.closest('.field');
        let hidden=0;
        box.querySelectorAll('details').forEach(d=>{
          folds+=1;
          if(!d.open) hidden += (d.textContent||'').length - (d.querySelector('summary').textContent||'').length;
        });
        visible += (box.textContent||'').length - hidden;
        folded += hidden;
      });
      return {visible, folded, folds};
    }""")


def test_the_block_says_its_piece_without_a_wall_of_text() -> None:
    chrome = chromium_or_skip()
    from playwright.sync_api import sync_playwright

    import main as wrapper

    with serve(wrapper.app, PORT) as base:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=str(chrome))
            page = browser.new_page()
            errors: list[str] = []
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            page.goto(base + "/", wait_until="networkidle")
            page.evaluate("() => calculate()")
            page.wait_for_function(
                "() => {const box=document.getElementById('landscapingHouseRateNote');"
                "return box && box.textContent.length > 0}", timeout=120_000)
            seen = _seen(page)
            browser.close()

    assert not errors, errors
    assert seen["visible"] <= VISIBLE_LIMIT, (
        f"видимой прозы {seen['visible']} знаков при потолке {VISIBLE_LIMIT} "
        f"(было {WAS_BEFORE}, потом {WAS_WITH_FOLD}) — стена текста вернулась", seen)
    # Складок в блоке больше нет и быть не должно: справка уехала целиком.
    # Что она не удалена, а переехала, держит соседняя проверка — та, что
    # ищет её в окне «Настройки класса»; иначе объём чинился бы вычёркиванием
    # знания.
    assert seen["folds"] == 0, ("во «Вводных» снова кат — справка вернулась", seen)
