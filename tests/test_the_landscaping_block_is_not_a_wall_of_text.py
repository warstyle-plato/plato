"""Пояснения блока благоустройства меряются, а не оцениваются на глаз.

«Не кажется ли тебе, что текста пояснительного слишком много и возможно его
стоит или сократить, или как-то свернуть в единые пояснения для блока
благоустройство» (владелец, 16.09.2026, снимок экрана). Померено на живой
странице: две вводные благоустройства несли 1732 знака сплошной прозы, из них
928 — справка о нормах ГОРОДА, которая в расчёт не входит вовсе, и около
двухсот — повтор одного и того же в подсказке поля и в подписи под ним.

Правило отсюда общее и уже записано у списков карточки КРТ: справочное уезжает
под кат с названным заголовком, а каждое утверждение говорится один раз — база
у подсказки, состояние у подписи. Проверяется отрисовкой: в исходнике стена
текста выглядит ровно так же, как свёрнутая, и «на глаз» здесь не мера.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from browser import chromium_or_skip, serve  # noqa: E402

PORT = 18963

# Замер до правки — 1732 знака видимой прозы; после — около семисот. Потолок
# стоит с запасом, но ниже прежнего объёма: он ловит возврат стены, а не
# каждое слово. Число названо здесь один раз, чтобы отказ мог сказать, с чем
# сравнивал.
VISIBLE_LIMIT = 900
WAS_BEFORE = 1732


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
        f"(до правки было {WAS_BEFORE}) — стена текста вернулась", seen)
    # Свёрнуто — не «удалено»: справка о нормах города обязана остаться на
    # странице, иначе проверка на объём чинится вычёркиванием знания.
    assert seen["folds"] >= 1, ("справки о нормах города на странице нет вовсе", seen)
    assert seen["folded"] >= 600, (
        "под катом почти ничего — значит справку не свернули, а урезали", seen)
