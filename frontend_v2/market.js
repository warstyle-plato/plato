(() => {
  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  const fmt = (value) => Number(value || 0).toLocaleString('ru-RU');
  const price = (value) => `${fmt(value)} ₽/м²`;
  const esc = (value) => String(value ?? '').replace(/[&<>'"]/g, (char) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
  }[char]));

  function injectNavigation() {
    const nav = $('.main-nav');
    if (nav && !nav.querySelector('[data-view="market"]')) {
      const button = document.createElement('button');
      button.className = 'nav-item';
      button.dataset.view = 'market';
      button.innerHTML = '<span>₽</span>Рынок и цена';
      const tep = nav.querySelector('[data-view="tep"]');
      nav.insertBefore(button, tep || null);
    }
    const mobile = $('.mobile-tabs');
    if (mobile && !mobile.querySelector('[data-view="market"]')) {
      const button = document.createElement('button');
      button.dataset.view = 'market';
      button.textContent = 'Рынок';
      const tep = mobile.querySelector('[data-view="tep"]');
      mobile.insertBefore(button, tep || null);
    }
  }

  function injectView() {
    if ($('#view-market')) return;
    const section = document.createElement('section');
    section.id = 'view-market';
    section.className = 'view';
    section.innerHTML = `
      <div class="section-heading">
        <div><span class="eyebrow">Локация и экспозиция</span><h2>Рынок и рекомендация цены</h2></div>
        <span class="source-label">НАШ.ДОМ.РФ · Домклик</span>
      </div>
      <article class="panel market-search-panel">
        <div class="market-form">
          <label>Адрес<input id="marketAddress" value="Москва, ул. Мишина, 46" autocomplete="off"></label>
          <label>Старт продаж<input id="marketSaleStart" type="date" value="2027-06-01"></label>
          <label>Продаваемая площадь, м²<input id="marketSaleable" type="number" min="0" step="100" value="15150"></label>
          <label>Рост цены, % в год<input id="marketGrowth" type="number" step="0.1" value="6"></label>
          <button id="marketRun" class="search-button" type="button">Рассчитать</button>
        </div>
        <div id="marketStatus" class="tep-search-status">Пилот использует контрольный срез Мишина, 46. Другие адреса пока не рассчитываются по неподтверждённым данным.</div>
      </article>
      <div id="marketResult" hidden>
        <div id="marketKpis" class="kpi-grid market-kpis"></div>
        <div class="content-grid two-one">
          <article class="panel">
            <div class="panel-heading"><div><span class="eyebrow">Ценовые ориентиры</span><h2>Рекомендация</h2></div><span id="marketConfidence" class="metric-chip"></span></div>
            <div id="marketRecommendation" class="market-recommendation"></div>
          </article>
          <article class="panel">
            <div class="panel-heading"><div><span class="eyebrow">Предложение рядом</span><h2>Масштаб рынка</h2></div></div>
            <div id="marketSupply" class="market-supply"></div>
          </article>
        </div>
        <article class="panel market-table-panel">
          <div class="panel-heading"><div><span class="eyebrow">Сопоставимые проекты</span><h2>Аналоги</h2></div><span id="marketSource" class="source-label"></span></div>
          <div id="marketComparables" class="market-table"></div>
        </article>
        <article class="panel market-note-panel"><div id="marketNotes"></div></article>
      </div>`;
    const tepView = $('#view-tep');
    (tepView?.parentElement || $('.workspace')).insertBefore(section, tepView || null);
  }

  function bindNavigation() {
    $$('[data-view="market"]').forEach((button) => {
      button.addEventListener('click', () => {
        $$('.view').forEach((view) => view.classList.toggle('is-active', view.id === 'view-market'));
        $$('.nav-item, .mobile-tabs button').forEach((item) => item.classList.toggle('is-active', item.dataset.view === 'market'));
        window.scrollTo({ top: 0, behavior: 'smooth' });
      });
    });
  }

  function render(payload) {
    $('#marketResult').hidden = false;
    $('#marketConfidence').textContent = `Достоверность ${payload.confidence_score}%`;
    $('#marketSource').textContent = `${payload.source_label} · ${payload.source_date}`;
    const low = payload.recommended_price_range.low;
    const high = payload.recommended_price_range.high;
    $('#marketKpis').innerHTML = [
      ['Ориентир сегодня', price(payload.market_price_today), 'взвешенная экспозиция'],
      ['Цена старта', price(payload.recommended_launch_price), `${payload.months_to_launch} мес. до старта`],
      ['Средняя реализация', price(payload.weighted_average_project_price), `${payload.sales_duration_months} мес. продаж`],
      ['Рабочий диапазон', `${fmt(low)}–${fmt(high)}`, '₽/м²'],
    ].map(([label, value, note]) => `
      <article class="panel kpi-card"><div class="kpi-top"><span class="kpi-icon">₽</span></div>
      <label>${esc(label)}</label><strong>${esc(value)}</strong><small>${esc(note)}</small></article>`).join('');

    $('#marketRecommendation').innerHTML = `
      <strong>${price(payload.recommended_launch_price)}</strong>
      <p>Базовая цена для старта продаж. Консервативный сценарий — ${price(low)}, целевой — ${price(high)}.</p>
      <div class="market-formula">Текущий взвешенный ориентир × рост рынка до старта × дисконт запуска.</div>`;

    const market = payload.market;
    const share = market.project_share_of_nearby_area == null
      ? '—'
      : `${(market.project_share_of_nearby_area * 100).toFixed(1).replace('.', ',')}%`;
    $('#marketSupply').innerHTML = `
      <div><span>Проектов в выборке</span><strong>${market.projects}</strong></div>
      <div><span>Объём рядом</span><strong>${fmt(market.total_area_sqm)} м²</strong></div>
      <div><span>Активных предложений</span><strong>${fmt(market.active_listings)}</strong></div>
      <div><span>Доля нашего проекта</span><strong>${share}</strong></div>`;

    $('#marketComparables').innerHTML = `
      <div class="market-row market-head"><span>Проект</span><span>Расстояние</span><span>Роль</span><span>Экспозиция</span><span>Цена</span><span>Вес</span></div>
      ${payload.comparables.map((item) => `
        <div class="market-row"><span><b>${esc(item.name)}</b><small>${esc(item.status)}</small></span>
        <span>${String(item.distance_km).replace('.', ',')} км</span><span>${esc(item.role)}</span>
        <span>${fmt(item.active_listings)}</span><span>${price(item.price_sqm)}</span>
        <span>${Math.round(item.weight * 100)}%</span></div>`).join('')}`;
    $('#marketNotes').innerHTML = payload.notes.map((note) => `<p>• ${esc(note)}</p>`).join('');
  }

  async function run() {
    const status = $('#marketStatus');
    const button = $('#marketRun');
    button.disabled = true;
    status.textContent = 'Собираю рынок и рассчитываю ценовой ориентир…';
    try {
      const response = await fetch('/api/v2/market-analysis', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          address: $('#marketAddress').value.trim(),
          sale_start_date: $('#marketSaleStart').value || null,
          saleable_area_sqm: Number($('#marketSaleable').value || 0) || null,
          annual_price_growth: Number($('#marketGrowth').value || 0) / 100,
          sales_duration_months: 42,
        }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || 'Рынок не рассчитан');
      render(payload);
      status.textContent = `Готово. Источник: ${payload.source_label}, данные на ${payload.source_date}.`;
    } catch (error) {
      $('#marketResult').hidden = true;
      status.textContent = String(error.message || error);
    } finally {
      button.disabled = false;
    }
  }

  function init() {
    injectNavigation();
    injectView();
    bindNavigation();
    $('#marketRun').addEventListener('click', run);
    $('#marketAddress').addEventListener('keydown', (event) => { if (event.key === 'Enter') run(); });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
