(() => {
  'use strict';

  function moveFirst(container, selector) {
    if (!container) return;
    const item = container.querySelector(selector);
    if (item && container.firstElementChild !== item) container.insertBefore(item, container.firstElementChild);
  }

  function orderNavigation() {
    // Search is the entry point for a new project, so it must also be the first
    // visible item rather than merely the screen selected behind an "Overview"
    // tab. Keep desktop and mobile navigation in the same order.
    moveFirst(document.querySelector('.main-nav'), '[data-view="tepsearch"]');
    moveFirst(document.querySelector('.mobile-tabs'), '[data-view="tepsearch"]');
  }

  function ensureTepStep() {
    // The photo OCR review still writes through the stock v2 form controls.
    // Keep the TEP form block rendered in the hidden Inputs view while the user
    // stays on Search; this lets the existing change handlers update form.draft
    // without creating a second mapping of TEP fields.
    try {
      if (typeof form === 'undefined' || !form || !Array.isArray(form.blocks)) return;
      const index = form.blocks.findIndex((block) => block && (
        block.kind === 'tep' || /ТЭП/i.test(String(block.title || ''))
      ));
      if (index < 0 || form.step === index) return;
      form.step = index;
      if (typeof renderStep === 'function') renderStep();
    } catch (error) {
      // app.js can still be initializing during the first paint; the next user
      // action calls this again after the form exists.
    }
  }

  function movePhotoToSearch() {
    const searchPanel = document.querySelector('#view-tepsearch .tep-search-panel');
    const photoPanel = document.getElementById('v2PhotoPanel');
    if (!searchPanel || !photoPanel) return;

    if (photoPanel.previousElementSibling !== searchPanel) {
      searchPanel.insertAdjacentElement('afterend', photoPanel);
    }
    // The old hook hid the panel whenever the Inputs wizard was not on its TEP
    // block. The panel now belongs to Search, so visibility is controlled by the
    // Search view itself and must not depend on that hidden wizard step.
    photoPanel.hidden = false;

    if (photoPanel.dataset.searchVisibilityGuard === '1') return;
    photoPanel.dataset.searchVisibilityGuard = '1';
    const guard = new MutationObserver(() => {
      if (photoPanel.hidden) photoPanel.hidden = false;
      if (photoPanel.previousElementSibling !== searchPanel) {
        searchPanel.insertAdjacentElement('afterend', photoPanel);
      }
    });
    guard.observe(photoPanel, { attributes: true, attributeFilter: ['hidden'] });
  }

  // Switch the hidden form to the TEP block before the old photo handler reads
  // or applies values. Capture phase runs before the button's original handler.
  document.addEventListener('click', (event) => {
    if (event.target.closest('#v2CameraButton, #v2GalleryButton, #v2PhotoApply')) {
      ensureTepStep();
      movePhotoToSearch();
    }
  }, true);

  orderNavigation();
  movePhotoToSearch();

  // upgrade.js creates the photo panel and app.js builds form blocks
  // asynchronously. Watch only DOM structure; the panel gets its own tiny
  // attribute guard once it appears.
  const observer = new MutationObserver(() => {
    orderNavigation();
    movePhotoToSearch();
  });
  observer.observe(document.body, { childList: true, subtree: true });
})();

(() => {
  'use strict';

  const scenarioState = {
    formDescription: null,
    classPresets: null,
    compareBusy: false,
    landSignature: '',
    landBusy: false,
  };

  function esc(value) {
    return String(value == null ? '' : value).replace(/[&<>"']/g, (char) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[char]));
  }

  function injectScenarioLandStyles() {
    if (document.getElementById('v2ScenarioLandStyles')) return;
    const style = document.createElement('style');
    style.id = 'v2ScenarioLandStyles';
    style.textContent = `
      .scenario-class-grid,.scenario-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin:12px 0 20px}
      .scenario-choice{display:block;width:100%;text-align:left;border:1px solid rgba(255,255,255,.1);border-radius:14px;background:rgba(255,255,255,.035);padding:14px;color:inherit;cursor:pointer}
      .scenario-choice:hover,.scenario-choice.is-active{border-color:rgba(56,215,255,.45);background:rgba(56,215,255,.08)}
      .scenario-choice strong{display:block;font-size:15px;margin-bottom:5px}.scenario-choice small{display:block;color:#91a4ba;line-height:1.45}
      .scenario-choice .scenario-metric{display:block;margin-top:8px;color:#dbe9f7;font-size:12px}.scenario-actions{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin:8px 0 16px}
      .scenario-table{width:100%;border-collapse:collapse;font-size:12px}.scenario-table th,.scenario-table td{padding:10px 8px;border-bottom:1px solid rgba(255,255,255,.08);text-align:right}.scenario-table th:first-child,.scenario-table td:first-child{text-align:left}
      .scenario-status{color:#91a4ba;font-size:12px;line-height:1.45}.scenario-status.is-error{color:#ff9aaa}
      .land-v2-wrap{margin-top:18px}.land-v2-grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}.land-v2-card{overflow:hidden}.land-v2-card .panel-heading{margin-bottom:10px}
      .land-live-map{position:relative;aspect-ratio:16/9;border:1px solid rgba(255,255,255,.09);border-radius:13px;overflow:hidden;background:#0b1725;touch-action:none;user-select:none}
      .land-live-map img,.land-live-map svg{position:absolute;inset:0;width:100%;height:100%;display:block}.land-live-map img{object-fit:fill}.land-live-map svg{pointer-events:none}
      .land-map-controls{position:absolute;z-index:4;top:10px;right:10px;display:flex;flex-direction:column;gap:6px}.land-map-controls button{width:34px;height:34px;border:1px solid rgba(255,255,255,.18);border-radius:9px;background:rgba(7,17,31,.9);color:#fff;font-size:19px;cursor:pointer}
      .land-map-caption{position:absolute;z-index:4;left:9px;bottom:8px;padding:4px 7px;border-radius:7px;background:rgba(7,17,31,.82);color:#dbe9f7;font-size:10px}.land-map-status{padding:28px 16px;text-align:center;color:#91a4ba}
      .land-restrictions{margin-top:12px;display:grid;gap:8px}.land-restriction{padding:10px 11px;border:1px solid rgba(255,255,255,.08);border-radius:11px;background:rgba(255,255,255,.025)}
      .land-restriction-head{display:flex;gap:7px;align-items:center;flex-wrap:wrap}.land-restriction-head strong{font-size:12px}.land-flag{font-size:9px;font-weight:800;letter-spacing:.04em;padding:2px 6px;border-radius:999px;text-transform:uppercase}.land-flag.killer{background:rgba(255,102,122,.14);color:#ff8fa0}.land-flag.economic{background:rgba(255,185,87,.14);color:#ffc979}.land-flag.info{background:rgba(56,215,255,.12);color:#8ddfff}
      .land-restriction p{margin:5px 0 0;color:#91a4ba;font-size:11px;line-height:1.45}.land-verdict{margin:0 0 10px;color:#c9d8e8;font-size:12px;line-height:1.45}
      @media(max-width:900px){.scenario-class-grid,.scenario-grid,.land-v2-grid{grid-template-columns:1fr}.scenario-table{font-size:11px}.land-live-map{aspect-ratio:4/3}}
    `;
    document.head.appendChild(style);
  }

  function ensureScenarioNavigation() {
    const desktopNav = document.querySelector('.main-nav');
    const mobileNav = document.querySelector('.mobile-tabs');
    const sensitivityDesktop = desktopNav && desktopNav.querySelector('[data-view="sensitivity"]');
    const sensitivityMobile = mobileNav && mobileNav.querySelector('[data-view="sensitivity"]');

    if (desktopNav && sensitivityDesktop && !desktopNav.querySelector('[data-view="scenarios"]')) {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'nav-item';
      button.dataset.view = 'scenarios';
      button.innerHTML = '<span>◇</span>Сценарии';
      sensitivityDesktop.before(button);
    }
    if (mobileNav && sensitivityMobile && !mobileNav.querySelector('[data-view="scenarios"]')) {
      const button = document.createElement('button');
      button.type = 'button';
      button.dataset.view = 'scenarios';
      button.textContent = 'Сценарии';
      sensitivityMobile.before(button);
    }

    const sensitivityView = document.getElementById('view-sensitivity');
    if (sensitivityView && !document.getElementById('view-scenarios')) {
      const section = document.createElement('section');
      section.id = 'view-scenarios';
      section.className = 'view';
      section.innerHTML = `
        <div class="section-heading"><div><span class="eyebrow">Предпосылки и стресс</span><h2>Класс проекта и сценарии</h2></div><span class="source-label">один движок · три сценария</span></div>
        <article class="panel">
          <div class="panel-heading"><div><span class="eyebrow">База проекта</span><h2>Класс</h2></div></div>
          <p class="input-hint">Класс задаёт базовые цены реализации и полный профиль строительной себестоимости. После выбора можно править отдельные ставки во «Вводных».</p>
          <div id="v2ClassGrid" class="scenario-class-grid"><div class="scenario-status">Загружаю классы…</div></div>
        </article>
        <article class="panel" style="margin-top:14px">
          <div class="panel-heading"><div><span class="eyebrow">Поверх выбранного класса</span><h2>Сценарий</h2></div></div>
          <p class="input-hint">Базовый — цены и затраты 100%; консервативный — цены −10%, затраты +10%; оптимистичный — цены +10%, затраты −10%.</p>
          <div id="v2ScenarioGrid" class="scenario-grid"></div>
          <div class="scenario-actions"><button id="v2CompareScenarios" class="search-button" type="button">Сравнить три сценария</button><span id="v2ScenarioStatus" class="scenario-status"></span></div>
          <div id="v2ScenarioComparison"></div>
        </article>`;
      sensitivityView.before(section);
    }
  }

  function ensureLandPanels() {
    const view = document.getElementById('view-tep');
    if (!view || document.getElementById('v2LandMaps')) return;
    const wrap = document.createElement('div');
    wrap.id = 'v2LandMaps';
    wrap.className = 'land-v2-wrap';
    wrap.innerHTML = `
      <div class="land-v2-grid">
        <article class="panel land-v2-card">
          <div class="panel-heading"><div><span class="eyebrow">НСПД · ЕГРН</span><h2>Участок и ограничения</h2></div></div>
          <div id="v2RestrictionVerdict" class="land-verdict">Откройте проект с кадастровым номером — проверю ЗОУИТ, ООПТ, красные линии и другие ограничения.</div>
          <div id="v2RestrictionMap" class="land-map-status">Карта появится по кадастровому номеру.</div>
          <div id="v2RestrictionList" class="land-restrictions"></div>
        </article>
        <article class="panel land-v2-card">
          <div class="panel-heading"><div><span class="eyebrow">OpenStreetMap</span><h2>Живое окружение</h2></div><span class="source-label">двигайте · масштабируйте</span></div>
          <div id="v2EnvironmentMap" class="land-map-status">Карта появится по границам участка.</div>
          <p class="input-hint" style="margin-top:9px">Улицы, здания, вода и подписи приходят из актуальной OSM-подложки DevelopAid. Контур — фактический ЕГРН.</p>
        </article>
      </div>`;
    view.appendChild(wrap);
  }

  function money(value) {
    const n = Number(value || 0);
    if (!Number.isFinite(n)) return '—';
    if (Math.abs(n) >= 1e9) return `${(n / 1e9).toLocaleString('ru-RU', { maximumFractionDigits: 2 })} млрд ₽`;
    return `${(n / 1e6).toLocaleString('ru-RU', { maximumFractionDigits: 1 })} млн ₽`;
  }

  function currentResult() {
    return window.DevelopAidV2 && window.DevelopAidV2.state && window.DevelopAidV2.state.result;
  }

  function currentDraft() {
    const result = currentResult() || {};
    const request = result.request || {};
    try {
      if (typeof form !== 'undefined' && form && form.draft) return form.draft;
    } catch (error) { /* stock form can still be starting */ }
    return { inputs: request.inputs || {}, tep: request.tep || {}, phasing: request.phasing || {} };
  }

  function currentScenario() {
    const result = currentResult() || {};
    return String((result.project || {}).scenario || (result.request || {}).scenario || 'base');
  }

  function payloadFor(scenario, sensitivity = false) {
    const result = currentResult() || {};
    const project = result.project || {};
    const draft = currentDraft();
    return {
      inputs: draft.inputs || {}, tep: draft.tep || {}, rates: [], phasing: draft.phasing || {},
      project_name: project.name || '', region: project.region || '',
      cadastral_numbers: project.cadastral_numbers || [],
      source_label: project.source_label || 'DevelopAid 2.0',
      scenario: scenario || currentScenario(), sensitivity,
    };
  }

  async function loadFormDescription() {
    if (scenarioState.formDescription) return scenarioState.formDescription;
    const response = await fetch('/api/v2/form', { cache: 'no-store' });
    if (!response.ok) throw new Error('Не удалось получить сценарии движка');
    scenarioState.formDescription = await response.json();
    return scenarioState.formDescription;
  }

  async function loadClassPresets() {
    if (scenarioState.classPresets) return scenarioState.classPresets;
    // Основная страница получает этот JSON непосредственно из PROJECT_CLASS_PRESETS
    // движка. Читаем именно её сериализованный объект, чтобы не заводить вторую
    // копию цен/себестоимости в v2.
    const response = await fetch('/', { cache: 'no-store' });
    if (!response.ok) throw new Error('Не удалось получить классы проекта');
    const html = await response.text();
    const match = html.match(/const PROJECT_CLASS_PRESETS=(\{[^\n]+\});/);
    if (!match) throw new Error('Движок не отдал профили классов');
    scenarioState.classPresets = JSON.parse(match[1]);
    return scenarioState.classPresets;
  }

  function scenarioLabel(key) {
    return ({ conservative: 'Консервативный', base: 'Базовый', optimistic: 'Оптимистичный' })[key] || key;
  }

  function renderScenarioControls() {
    const result = currentResult();
    if (!result) return;
    const request = result.request || {};
    const inputs = request.inputs || currentDraft().inputs || {};
    const activeClass = String(inputs.project_class || 'custom');
    const activeScenario = currentScenario();
    const classHost = document.getElementById('v2ClassGrid');
    const scenarioHost = document.getElementById('v2ScenarioGrid');
    if (!classHost || !scenarioHost) return;

    Promise.all([loadFormDescription(), loadClassPresets()]).then(([description, presets]) => {
      const classes = description.project_classes || [];
      classHost.innerHTML = classes.map((item) => {
        const preset = presets[item.value] || {};
        const price = Number(preset.apartment_price_th || 0);
        const smr = Number(preset.main_above_th_per_sqm || 0);
        return `<button type="button" class="scenario-choice ${activeClass === item.value ? 'is-active' : ''}" data-project-class="${esc(item.value)}"><strong>${esc(item.label)}</strong><small>Жильё ${price.toLocaleString('ru-RU')} тыс. ₽/м² · СМР ${smr.toLocaleString('ru-RU')} тыс. ₽/м²</small></button>`;
      }).join('') + `<button type="button" class="scenario-choice ${activeClass === 'custom' ? 'is-active' : ''}" data-project-class="custom"><strong>Пользовательский</strong><small>Оставить текущие ставки и править их во «Вводных».</small></button>`;

      const scenarios = description.scenarios || {};
      scenarioHost.innerHTML = Object.keys(scenarios).map((key) => {
        const row = scenarios[key] || {};
        const revenue = Math.round(Number(row.scenario_revenue_multiplier || 1) * 100);
        const cost = Math.round(Number(row.scenario_cost_multiplier || 1) * 100);
        return `<button type="button" class="scenario-choice ${activeScenario === key ? 'is-active' : ''}" data-project-scenario="${esc(key)}"><strong>${esc(scenarioLabel(key))}</strong><small>Цены ${revenue}% · затраты ${cost}%</small></button>`;
      }).join('');
    }).catch((error) => {
      classHost.innerHTML = `<div class="scenario-status is-error">${esc(error.message || error)}</div>`;
    });
  }

  async function applyClass(key) {
    const status = document.getElementById('v2ScenarioStatus');
    try {
      const draft = currentDraft();
      if (!draft.inputs) throw new Error('Форма проекта ещё не загрузилась');
      if (key === 'custom') {
        draft.inputs.project_class = 'custom';
      } else {
        const presets = await loadClassPresets();
        const preset = presets[key];
        if (!preset) throw new Error('Профиль класса не найден');
        draft.inputs.project_class = key;
        Object.keys(preset).filter((field) => field !== 'label').forEach((field) => {
          draft.inputs[field] = preset[field];
        });
      }
      try { if (typeof renderStep === 'function') renderStep(); } catch (error) { /* optional */ }
      status.textContent = 'Пересчитываю проект с базой выбранного класса…';
      await window.DevelopAidV2.calculateProject(payloadFor(currentScenario(), true));
      status.textContent = 'Класс применён. Все показатели пересчитаны движком.';
      renderScenarioControls();
    } catch (error) {
      status.textContent = String(error.message || error);
      status.classList.add('is-error');
    }
  }

  async function applyScenario(key) {
    const status = document.getElementById('v2ScenarioStatus');
    try {
      status.classList.remove('is-error');
      status.textContent = `Считаю сценарий «${scenarioLabel(key)}»…`;
      await window.DevelopAidV2.calculateProject(payloadFor(key, true));
      status.textContent = `Активен сценарий «${scenarioLabel(key)}».`;
      renderScenarioControls();
    } catch (error) {
      status.textContent = String(error.message || error);
      status.classList.add('is-error');
    }
  }

  async function compareScenarios() {
    if (scenarioState.compareBusy) return;
    const status = document.getElementById('v2ScenarioStatus');
    const host = document.getElementById('v2ScenarioComparison');
    if (!host) return;
    scenarioState.compareBusy = true;
    if (status) status.textContent = 'Считаю три сценария одним и тем же движком…';
    try {
      const description = await loadFormDescription();
      const keys = Object.keys(description.scenarios || {});
      const rows = await Promise.all(keys.map(async (key) => {
        const response = await fetch('/api/v2/calculate', {
          method: 'POST', headers: { 'Content-Type': 'application/json' }, cache: 'no-store',
          body: JSON.stringify(payloadFor(key, false)),
        });
        const result = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(result.detail || `Не посчитался сценарий ${key}`);
        return [key, result];
      }));
      host.innerHTML = `<div style="overflow:auto"><table class="scenario-table"><thead><tr><th>Сценарий</th><th>Выручка</th><th>Расходы</th><th>Чистая прибыль</th><th>LLCR</th></tr></thead><tbody>${rows.map(([key, result]) => {
        const kpi = result.kpi || {};
        const llcr = Number(kpi.llcr);
        return `<tr><td><strong>${esc(scenarioLabel(key))}</strong></td><td>${esc(money(kpi.revenue))}</td><td>${esc(money(kpi.total_expenses))}</td><td>${esc(money(kpi.net_profit))}</td><td>${Number.isFinite(llcr) ? llcr.toFixed(2).replace('.', ',') + 'x' : '—'}</td></tr>`;
      }).join('')}</tbody></table></div>`;
      if (status) status.textContent = 'Сравнение готово. Выбор сценария выше делает его активным расчётом проекта.';
    } catch (error) {
      if (status) { status.textContent = String(error.message || error); status.classList.add('is-error'); }
    } finally {
      scenarioState.compareBusy = false;
    }
  }

  function allPoints(rings) {
    return (rings || []).flatMap((ring) => (ring || []).filter((point) => Array.isArray(point) && point.length >= 2));
  }

  function bboxFromRings(rings, context = 0.12, minimumPad = 120) {
    const points = allPoints(rings);
    if (!points.length) return null;
    const xs = points.map((p) => Number(p[0]));
    const ys = points.map((p) => Number(p[1]));
    let minX = Math.min(...xs), maxX = Math.max(...xs), minY = Math.min(...ys), maxY = Math.max(...ys);
    let spanX = Math.max(maxX - minX, 1), spanY = Math.max(maxY - minY, 1);
    const pad = Math.max(Math.max(spanX, spanY) * context, minimumPad);
    minX -= pad; maxX += pad; minY -= pad; maxY += pad;
    spanX = maxX - minX; spanY = maxY - minY;
    const target = 16 / 9;
    if (spanX / spanY < target) {
      const extra = (spanY * target - spanX) / 2; minX -= extra; maxX += extra;
    } else {
      const extra = (spanX / target - spanY) / 2; minY -= extra; maxY += extra;
    }
    return [minX, minY, maxX, maxY];
  }

  function mapPath(rings, bbox, width = 1000, height = 562.5) {
    const [x0, y0, x1, y1] = bbox;
    return (rings || []).map((ring) => {
      const points = (ring || []).filter((point) => Array.isArray(point) && point.length >= 2).map((point) => {
        const x = (Number(point[0]) - x0) / (x1 - x0) * width;
        const y = (y1 - Number(point[1])) / (y1 - y0) * height;
        return `${x.toFixed(1)} ${y.toFixed(1)}`;
      });
      return points.length >= 3 ? `M${points.join(' L')} Z` : '';
    }).join(' ');
  }

  function mountLiveMap(host, options) {
    if (!host || !options.rings || !options.rings.length) return;
    let bbox = options.bbox.slice();
    const parcelRings = options.rings;
    const zones = options.zones || [];
    host.className = 'land-live-map';
    host.innerHTML = '<img alt=""><svg viewBox="0 0 1000 562.5" preserveAspectRatio="none" aria-hidden="true"></svg><div class="land-map-controls"><button type="button" data-map-zoom="in" aria-label="Приблизить">+</button><button type="button" data-map-zoom="out" aria-label="Отдалить">−</button><button type="button" data-map-zoom="reset" aria-label="Вернуть участок">⌂</button></div><div class="land-map-caption"></div>';
    const image = host.querySelector('img');
    const svg = host.querySelector('svg');
    const caption = host.querySelector('.land-map-caption');
    const initial = bbox.slice();

    function source() {
      const q = bbox.map((value) => value.toFixed(1)).join(',');
      return options.kind === 'osm'
        ? `/land/basemap?bbox=${encodeURIComponent(q)}&width=1000`
        : `/land/map-image?bbox=${encodeURIComponent(q)}`;
    }

    function paint() {
      image.src = source();
      const parcel = mapPath(parcelRings, bbox);
      const zonePaths = zones.map((zone) => {
        const d = mapPath(zone.outline_merc || [], bbox);
        if (!d) return '';
        const cls = zone.flag_class === 'killer' ? 'killer' : (zone.flag_class === 'economic' ? 'economic' : 'info');
        const fill = cls === 'killer' ? 'rgba(255,102,122,.22)' : (cls === 'economic' ? 'rgba(255,185,87,.20)' : 'rgba(56,215,255,.16)');
        const stroke = cls === 'killer' ? '#ff667a' : (cls === 'economic' ? '#ffb957' : '#38d7ff');
        return `<path d="${d}" fill="${fill}" stroke="${stroke}" stroke-width="3" fill-rule="evenodd" vector-effect="non-scaling-stroke"></path>`;
      }).join('');
      svg.innerHTML = zonePaths + `<path d="${parcel}" fill="rgba(255,255,255,.08)" stroke="#fff" stroke-width="5" fill-rule="evenodd" vector-effect="non-scaling-stroke"></path><path d="${parcel}" fill="none" stroke="#111" stroke-width="2" fill-rule="evenodd" vector-effect="non-scaling-stroke"></path>`;
      caption.textContent = options.kind === 'osm' ? '© OpenStreetMap · контур ЕГРН' : 'НСПД · ЕГРН · зоны ограничений';
    }

    function zoom(factor) {
      const [x0, y0, x1, y1] = bbox;
      const cx = (x0 + x1) / 2, cy = (y0 + y1) / 2;
      const hx = (x1 - x0) * factor / 2, hy = (y1 - y0) * factor / 2;
      bbox = [cx - hx, cy - hy, cx + hx, cy + hy];
      paint();
    }

    host.querySelector('[data-map-zoom="in"]').addEventListener('click', () => zoom(.62));
    host.querySelector('[data-map-zoom="out"]').addEventListener('click', () => zoom(1.62));
    host.querySelector('[data-map-zoom="reset"]').addEventListener('click', () => { bbox = initial.slice(); paint(); });
    host.addEventListener('wheel', (event) => { event.preventDefault(); zoom(event.deltaY > 0 ? 1.25 : .8); }, { passive: false });

    let drag = null;
    host.addEventListener('pointerdown', (event) => {
      if (event.target.closest('button')) return;
      drag = { x: event.clientX, y: event.clientY, bbox: bbox.slice() };
      host.setPointerCapture(event.pointerId);
    });
    host.addEventListener('pointerup', (event) => {
      if (!drag) return;
      const rect = host.getBoundingClientRect();
      const dx = event.clientX - drag.x, dy = event.clientY - drag.y;
      const spanX = drag.bbox[2] - drag.bbox[0], spanY = drag.bbox[3] - drag.bbox[1];
      const shiftX = -dx / Math.max(rect.width, 1) * spanX;
      const shiftY = dy / Math.max(rect.height, 1) * spanY;
      bbox = [drag.bbox[0] + shiftX, drag.bbox[1] + shiftY, drag.bbox[2] + shiftX, drag.bbox[3] + shiftY];
      drag = null;
      paint();
    });
    host.addEventListener('pointercancel', () => { drag = null; });
    paint();
  }

  function screeningLabel(flag) {
    return flag === 'killer' ? 'СТОП' : (flag === 'economic' ? 'ВЛИЯЕТ' : 'СПРАВКА');
  }

  function verdictText(verdict) {
    if (!verdict) return '';
    return String(verdict.title || verdict.text || verdict.message || verdict.summary || verdict.disclaimer || '');
  }

  function renderLandData(lookup, screening) {
    const results = (lookup.results || []).filter((item) => item && item.found && Array.isArray(item.contour_merc) && item.contour_merc.length);
    const rings = results.flatMap((item) => item.contour_merc || []);
    const restrictionMap = document.getElementById('v2RestrictionMap');
    const environmentMap = document.getElementById('v2EnvironmentMap');
    const list = document.getElementById('v2RestrictionList');
    const verdict = document.getElementById('v2RestrictionVerdict');
    if (!rings.length) {
      restrictionMap.className = 'land-map-status'; restrictionMap.textContent = 'ЕГРН не вернул границы участка.';
      environmentMap.className = 'land-map-status'; environmentMap.textContent = 'Без границ живую карту привязать к участку нельзя.';
      return;
    }

    const parcels = (screening && screening.parcels) || [];
    const findings = parcels.flatMap((parcel) => parcel.findings || []);
    if (verdict) verdict.textContent = verdictText(screening && screening.verdict) || (findings.length ? `На участке найдено ограничений: ${findings.length}.` : 'По слоям НСПД ограничений на участке не обнаружено.');
    if (list) {
      list.innerHTML = findings.length ? findings.map((finding) => {
        const title = finding.name || finding.type_zone || finding.category || 'Ограничение';
        const share = finding.coverage_pct != null ? ` · ${Number(finding.coverage_pct).toLocaleString('ru-RU', { maximumFractionDigits: 1 })}% участка` : '';
        const numbers = finding.reg_numbers || (finding.reg_number ? [finding.reg_number] : []);
        const basis = [numbers.length ? `реестр № ${numbers.join(', ')}` : '', finding.document_number ? `${finding.document || 'документ'} № ${finding.document_number}` : '', finding.document_date ? `от ${finding.document_date}` : ''].filter(Boolean).join(' · ');
        return `<div class="land-restriction"><div class="land-restriction-head"><span class="land-flag ${esc(finding.flag_class || 'info')}">${esc(screeningLabel(finding.flag_class))}</span><strong>${esc(title)}</strong><span class="source-label">${esc(share.replace(/^ · /, ''))}</span></div><p>${esc(finding.impact || '')}${basis ? `<br>${esc(basis)}` : ''}</p></div>`;
      }).join('') : '<div class="scenario-status">Ограничений, пересекающих участок, в проверенных слоях НСПД не найдено.</div>';
    }

    const restrictionBbox = bboxFromRings(rings, .12, 90);
    const environmentBbox = bboxFromRings(rings, 1.0, 800);
    const zones = findings.filter((finding) => Array.isArray(finding.outline_merc) && finding.outline_merc.length);
    mountLiveMap(restrictionMap, { rings, zones, bbox: restrictionBbox, kind: 'cadastre' });
    mountLiveMap(environmentMap, { rings, zones: [], bbox: environmentBbox, kind: 'osm' });
  }

  function webSession() {
    try { return localStorage.getItem('developaid_web_session') || ''; } catch (error) { return ''; }
  }

  async function loadLandForCurrentProject(force = false) {
    if (scenarioState.landBusy) return;
    const result = currentResult();
    const numbers = result && result.project && Array.isArray(result.project.cadastral_numbers)
      ? result.project.cadastral_numbers.filter(Boolean) : [];
    const signature = numbers.join(',');
    if (!numbers.length) {
      scenarioState.landSignature = '';
      const verdict = document.getElementById('v2RestrictionVerdict');
      if (verdict) verdict.textContent = 'У проекта пока нет кадастрового номера. Добавьте его через поиск, тизер или сохранённый проект.';
      return;
    }
    if (!force && signature === scenarioState.landSignature) return;
    scenarioState.landBusy = true;
    scenarioState.landSignature = signature;
    const restrictionMap = document.getElementById('v2RestrictionMap');
    const environmentMap = document.getElementById('v2EnvironmentMap');
    if (restrictionMap) { restrictionMap.className = 'land-map-status'; restrictionMap.textContent = 'Проверяю ограничения НСПД…'; }
    if (environmentMap) { environmentMap.className = 'land-map-status'; environmentMap.textContent = 'Загружаю границы и окружение…'; }
    try {
      const [lookupResponse, screeningResponse] = await Promise.all([
        fetch('/land/lookup', { method: 'POST', headers: { 'Content-Type': 'application/json' }, cache: 'no-store', body: JSON.stringify({ query: numbers.join(', '), limit: 30, session: webSession() }) }),
        fetch(`/land/screening?cad=${encodeURIComponent(numbers.join(','))}`, { cache: 'no-store' }),
      ]);
      const lookup = await lookupResponse.json().catch(() => ({}));
      const screening = await screeningResponse.json().catch(() => ({}));
      if (!lookupResponse.ok) throw new Error(lookup.detail || 'Не удалось получить границы ЕГРН');
      renderLandData(lookup, screeningResponse.ok ? screening : { parcels: [], verdict: { text: screening.detail || 'Скрининг ограничений временно недоступен.' } });
    } catch (error) {
      if (restrictionMap) { restrictionMap.className = 'land-map-status'; restrictionMap.textContent = String(error.message || error); }
      if (environmentMap) { environmentMap.className = 'land-map-status'; environmentMap.textContent = 'Окружение не загрузилось вместе с границами участка.'; }
      scenarioState.landSignature = '';
    } finally {
      scenarioState.landBusy = false;
    }
  }

  function bindScenarioLandActions() {
    document.addEventListener('click', (event) => {
      const classButton = event.target.closest('[data-project-class]');
      if (classButton) { applyClass(classButton.dataset.projectClass); return; }
      const scenarioButton = event.target.closest('[data-project-scenario]');
      if (scenarioButton) { applyScenario(scenarioButton.dataset.projectScenario); return; }
      if (event.target.closest('#v2CompareScenarios')) { compareScenarios(); return; }
      const nav = event.target.closest('[data-view="scenarios"], [data-view="tep"]');
      if (nav && nav.dataset.view === 'scenarios') setTimeout(renderScenarioControls, 0);
      if (nav && nav.dataset.view === 'tep') setTimeout(() => loadLandForCurrentProject(false), 0);
    });
  }

  function waitForApp() {
    if (!(window.DevelopAidV2 && window.DevelopAidV2.state && window.DevelopAidV2.state.result)) {
      setTimeout(waitForApp, 150);
      return;
    }
    renderScenarioControls();
    const title = document.getElementById('projectName');
    if (title) {
      let queued = false;
      const observer = new MutationObserver(() => {
        if (queued) return;
        queued = true;
        requestAnimationFrame(() => {
          queued = false;
          renderScenarioControls();
          scenarioState.landSignature = '';
          if (window.DevelopAidV2.state.activeView === 'tep') loadLandForCurrentProject(true);
        });
      });
      observer.observe(title, { childList: true, characterData: true, subtree: true });
    }
  }

  injectScenarioLandStyles();
  ensureScenarioNavigation();
  ensureLandPanels();
  bindScenarioLandActions();
  waitForApp();
})();
