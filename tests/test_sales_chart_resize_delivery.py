"""Responsive SVG charts settle without writing from ResizeObserver delivery.

Use the native HTTP PAGE, its real calculation and the browser's own observer.
The old implementation produces trusted loop errors when the report first
becomes visible and when its width changes; no fabricated ErrorEvent is used.
"""
from __future__ import annotations

import hashlib

import pytest

import main as wrapper
from browser import chromium_or_skip, serve, wait_for_result


FRAMES = """() => new Promise(resolve => {
  let remaining=8;
  const tick=()=>--remaining?requestAnimationFrame(tick):resolve();
  requestAnimationFrame(tick);
})"""
INIT = """window.__chartProbe={deliveries:0,errors:[]};
const NativeResizeObserver=window.ResizeObserver;
window.ResizeObserver=class extends NativeResizeObserver {
 constructor(callback){super((entries,observer)=>{
   window.__chartProbe.deliveries++;callback(entries,observer);
 })}
};
window.addEventListener('error',event=>{
 window.__chartProbe.errors.push({message:event.message||'',trusted:event.isTrusted});
});"""
CHART_READY = """() => {
 const target=document.getElementById('apartmentPaceChart'),svg=target?.querySelector('svg');
 return target?.clientWidth>0&&svg
  &&Math.abs(svg.viewBox.baseVal.width-Math.max(280,target.clientWidth))<1;
}"""


@pytest.fixture
def native_page():
    from playwright.sync_api import sync_playwright

    with serve(wrapper.app, 18994) as base, sync_playwright() as pw:
        with pw.chromium.launch(executable_path=str(chromium_or_skip()), args=[
            "--disk-cache-size=1", "--media-cache-size=1", "--disable-gpu-shader-disk-cache",
        ]) as browser:
            yield browser, base


def _open(native_page, width):
    browser, base = native_page
    page = browser.new_page(viewport={"width": width, "height": 900})
    page.add_init_script(INIT)
    page.goto(base, wait_until="domcontentloaded")
    wait_for_result(page)
    return page


def _result_fingerprint(page):
    payload = page.evaluate("()=>JSON.stringify({lastResult,inputs,tep})")
    return hashlib.sha256(payload.encode()).hexdigest()


@pytest.mark.parametrize("width", [390, 1440])
def test_report_visibility_resize_and_rerender_do_not_loop_or_recalculate(native_page, width):
    page = _open(native_page, width)
    calculations = []
    page.on("request", lambda request: calculations.append(request.url)
            if "/calculate" in request.url else None)
    before = _result_fingerprint(page)
    page.evaluate("()=>openTab('report',null)")
    page.wait_for_function(CHART_READY)
    for next_width in (1440 if width == 390 else 390, width):
        page.set_viewport_size({"width": next_width, "height": 900})
        page.wait_for_function(CHART_READY)
        page.evaluate(FRAMES)
    page.evaluate("()=>{openTab('inputs',null);openTab('report',null);renderResult()}")
    page.wait_for_function(CHART_READY)
    page.evaluate(FRAMES)
    # A stable width must preserve the already drawn SVG, including when
    # only its observed container's height changes.
    page.evaluate("""()=>{
      const target=document.getElementById('apartmentPaceChart');
      window.__chartSvg=target.querySelector('svg');target.style.paddingBottom='17px';
    }""")
    page.evaluate(FRAMES)
    deliveries = page.evaluate("()=>window.__chartProbe.deliveries")
    page.evaluate(FRAMES)
    assert page.evaluate("()=>window.__chartProbe.deliveries") == deliveries
    assert page.evaluate("()=>window.__chartSvg===document.querySelector('#apartmentPaceChart svg')")
    assert page.evaluate("()=>document.querySelectorAll('#apartmentPaceChart rect').length") == page.evaluate(
        "()=>lastResult.report.apartment_sales.rows.filter(row=>Number(row.units)!==0).length")
    assert _result_fingerprint(page) == before
    assert not calculations, calculations
    assert not page.evaluate("()=>window.__chartProbe.errors")
    assert not page.locator("#pageFailure").count()


@pytest.mark.parametrize("width", [390, 1440])
def test_new_model_at_same_width_and_release_before_pending_frame(native_page, width):
    page = _open(native_page, width)
    before = _result_fingerprint(page)
    page.evaluate("""()=>{
      const host=document.createElement('div'),target=document.createElement('div');
      target.setAttribute('data-report-chart','');target.style.width='300px';
      host.append(target);document.body.append(host);
      window.__chartHost=host;window.__chartTarget=target;
      window.__chartModel={rows:[{month:'2030-01',units:1}],fields:[['units','Объём']],unit:'шт.',multiplier:1};
      renderSalesPeriodChart(target,window.__chartModel);
    }""")
    page.evaluate(FRAMES)
    got = page.evaluate("""()=>{
      const target=window.__chartTarget,first=target.querySelector('svg');
      drawSalesPeriodChart(target);const same=first===target.querySelector('svg');
      window.__chartModel.rows[0].units=7;
      renderSalesPeriodChart(target,window.__chartModel);
      return {same,updated:first!==target.querySelector('svg'),title:target.querySelector('title').textContent};
    }""")
    assert got["same"] and got["updated"] and "7" in got["title"], got
    page.evaluate(FRAMES)
    # Hold the real observer's requested animation frame, then release the
    # chart before that frame runs. Its queued target must be forgotten.
    page.evaluate("""()=>{
      window.__heldChartFrames=[];window.__nativeRAF=window.requestAnimationFrame;
      window.requestAnimationFrame=callback=>{window.__heldChartFrames.push(callback);return 123456;};
      window.__releasedSvg=window.__chartTarget.querySelector('svg');
      window.__chartTarget.style.width='360px';
    }""")
    page.wait_for_function("()=>window.__heldChartFrames.length>0", polling=10)
    released = page.evaluate("""()=>{
      const host=window.__chartHost,target=window.__chartTarget;
      releaseSalesPeriodCharts(host);host.remove();
      window.requestAnimationFrame=window.__nativeRAF;
      window.__heldChartFrames.splice(0).forEach(callback=>callback(performance.now()));
      drawSalesPeriodChart(target);
      return {same:window.__releasedSvg===target.querySelector('svg'),connected:target.isConnected,
              retained:salesChartModels.has(target),pending:salesChartPending.has(target)};
    }""")
    assert released == {"same": True, "connected": False, "retained": False, "pending": False}
    page.evaluate(FRAMES)
    assert _result_fingerprint(page) == before
    assert not page.evaluate("()=>window.__chartProbe.errors")
    assert not page.locator("#pageFailure").count()


@pytest.mark.parametrize('width', [390, 1440])
@pytest.mark.parametrize('reset', ['resetAll', 'resetProject'])
def test_reset_cancels_pending_native_frame_and_late_callback_cannot_take_new_model_frame(native_page, width, reset):
    page = _open(native_page, width)
    page.evaluate("()=>openTab('report',null)")
    page.wait_for_function(CHART_READY)
    page.evaluate("""()=>{
      const extra=document.createElement('div');extra.style.width='310px';document.body.append(extra);
      extra.setAttribute('data-report-chart','old-project-model');window.__resetExtra=extra;
      renderSalesPeriodChart(extra,{rows:[{month:'2030-01',units:987654321}],
        fields:[['units','Старый проект']],unit:'шт.',multiplier:1});
    }""")
    page.evaluate(FRAMES)
    page.evaluate("""()=>{
      window.__nativeChartRAF=window.requestAnimationFrame.bind(window);
      window.__nativeChartCancel=window.cancelAnimationFrame.bind(window);
      window.__resetFrames=[];window.__resetCancelled=[];
      // Native RAF delivery is real; hold its application callback to interleave
      // reset before SVG drawing. ResizeObserver and ErrorEvent stay native.
      window.requestAnimationFrame=callback=>{
        const entry={callback,delivered:false,id:0};
        entry.id=window.__nativeChartRAF(time=>{entry.delivered=true;entry.time=time});
        window.__resetFrames.push(entry);return entry.id;
      };
      window.cancelAnimationFrame=id=>{window.__resetCancelled.push(id);window.__nativeChartCancel(id)};
      const target=document.getElementById('apartmentPaceChart');window.__resetTarget=target;
      target.style.width=(target.clientWidth+31)+'px';window.__resetExtra.style.width='350px';
    }""")
    page.wait_for_function("""()=>{
      const id=typeof salesChartFrame==='object'?salesChartFrame.id:salesChartFrame;
      return window.__resetFrames.some(e=>e.id===id&&e.delivered);
    }""", polling=10)
    after = page.evaluate("""reset=>{
      const id=typeof salesChartFrame==='object'?salesChartFrame.id:salesChartFrame;
      window.__oldResetFrame=window.__resetFrames.find(e=>e.id===id);
      const original=isTelegramWebApp,refresh=refreshCurrentKeyRate;let left;
      // Observe the real reset's rate refresh without changing its response or
      // calculation. It launches calculate() asynchronously after reset returns.
      window.__resetRateDone=null;
      refreshCurrentKeyRate=(...args)=>{const done=refresh(...args);window.__resetRateDone=done;return done};
      try{if(reset==='resetProject')isTelegramWebApp=()=>true;left=window[reset]();}
      finally{isTelegramWebApp=original;refreshCurrentKeyRate=refresh;}
      const target=window.__resetTarget,extra=window.__resetExtra;
      return {left,frame:salesChartFrame,pending:salesChartPending.size,
        retained:salesChartModels.has(target)||salesChartModels.has(extra),
        measured:salesChartWidths.has(target)||salesChartWidths.has(extra),
        tracked:typeof salesChartTargets!=='undefined'?salesChartTargets.size:null,
        empty:!target.querySelector('svg')&&!extra.querySelector('svg'),
        oldModelAttribute:extra.hasAttribute('data-report-chart'),
        cancelled:window.__resetCancelled.includes(id),gns:tep.apartments.gns,units:tep.apartments.units};
    }""", reset)
    assert after == {'left': [], 'frame': 0, 'pending': 0, 'retained': False,
                     'measured': False, 'tracked': 0, 'empty': True, 'oldModelAttribute': False,
                     'cancelled': True, 'gns': 0, 'units': 0}, after
    # A new project starts after the reset's own real async work settles. A
    # chart injected before this point can correctly be cleared by that work.
    page.evaluate('()=>window.__resetRateDone')
    page.wait_for_function('()=>calcIdle()', polling=10)
    page.evaluate('()=>new Promise(resolve=>setTimeout(resolve,0))')
    page.evaluate("""()=>{
      const target=window.__resetTarget;
      renderApartmentPaceChart({rows:[{month:'2031-02',units:7}]});
      target.style.width=(target.clientWidth+19)+'px';
    }""")
    page.wait_for_function("""()=>{
      const id=typeof salesChartFrame==='object'?salesChartFrame.id:salesChartFrame;
      return id!==window.__oldResetFrame.id&&window.__resetFrames.some(e=>e.id===id&&e.delivered);
    }""", polling=10)
    before = _result_fingerprint(page)
    late = page.evaluate("""()=>{
      const frame=salesChartFrame,target=window.__resetTarget,svg=target.querySelector('svg');
      window.__oldResetFrame.callback(window.__oldResetFrame.time);
      const result={sameFrame:salesChartFrame===frame,pending:salesChartPending.has(target),
        sameSvg:svg===target.querySelector('svg'),title:target.querySelector('title').textContent,
        oldExtraEmpty:!window.__resetExtra.querySelector('svg')};
      window.requestAnimationFrame=window.__nativeChartRAF;
      window.cancelAnimationFrame=window.__nativeChartCancel;
      const id=typeof frame==='object'?frame.id:frame;
      window.__resetFrames.find(e=>e.id===id).callback(performance.now());
      return result;
    }""")
    assert late['sameFrame'] and late['pending'] and late['sameSvg'] and late['oldExtraEmpty'], late
    assert '7' in late['title'] and '987654321' not in late['title']
    page.wait_for_function(CHART_READY)
    page.evaluate(FRAMES)
    assert _result_fingerprint(page) == before
    assert not page.evaluate("()=>window.__chartProbe.errors")
    assert not page.locator('#pageFailure').count()


def test_genuine_script_rejection_and_resource_failures_remain_visible(native_page):
    page = _open(native_page, 1440)
    page.evaluate("()=>setTimeout(()=>{__missingChartProbeFunction__()},0)")
    page.wait_for_function("()=>document.getElementById('pageFailure')?.textContent.includes('__missingChartProbeFunction__')")
    assert "Страница не доработала до конца" in page.locator("#pageFailure").inner_text()
    page.evaluate("()=>{document.getElementById('pageFailure').remove();setTimeout(()=>{null.syntheticChartMethod()},0)}")
    page.wait_for_function("()=>document.getElementById('pageFailure')?.textContent.includes('null')")
    assert "Страница не доработала до конца" in page.locator("#pageFailure").inner_text()
    page.route("**/__chart_probe_fetch__", lambda route: route.abort())
    page.evaluate("()=>{document.getElementById('pageFailure').remove();fetch('/__chart_probe_fetch__')}")
    page.wait_for_function("()=>document.getElementById('pageFailure')?.textContent.includes('Failed to fetch')")
    assert "Незавершённая работа страницы" in page.locator("#pageFailure").inner_text()
    page.evaluate("""()=>{
      document.getElementById('pageFailure').remove();
      const image=document.createElement('img');image.src='/__chart_probe_missing_image__.png';document.body.append(image);
    }""")
    page.wait_for_function("()=>document.getElementById('pageFailure')?.textContent.includes('Не загрузился ресурс страницы: img')")
    assert "__chart_probe_missing_image__.png" in page.locator("#pageFailure").inner_text()
