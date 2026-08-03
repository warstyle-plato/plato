const state = {
  projects: [],
  project: null,
  activeView: 'summary',
};

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

const icons = {
  revenue: '↗', costs: '◫', profit: '₽', margin: '%', bridge: '⌁', pf: '◆',
  gns: '▦', saleable: '▤', apartments: '⌂', commercial: '□', parking: 'P', social: '◎',
};

function formatBn(value) {
  return `${Number(value).toLocaleString('ru-RU', { minimumFractionDigits: value < 1 ? 2 : 1, maximumFractionDigits: 2 })} млрд ₽`;
}

function formatM(value) {
  return `${Number(value).toLocaleString('ru-RU', { maximumFractionDigits: 1 })} млн ₽`;
}

function formatInt(value) {
  return Number(value || 0).toLocaleString('ru-RU');
}

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>'"]/g, (char) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
  }[char]));
}

function kpiCard({ icon, label, value, note = '', tone = '', delta = '' }) {
  return `
    <article class="panel kpi-card ${tone ? `is-${tone}` : ''}">
      <div class="kpi-top"><span class="kpi-icon">${icon}</span><span class="kpi-delta">${escapeHtml(delta)}</span></div>
      <label>${escapeHtml(label)}</label>
      <strong>${escapeHtml(value)}</strong>
      ${note ? `<small>${escapeHtml(note)}</small>` : ''}
    </article>`;
}

function setView(view) {
  state.activeView = view;
  $$('.view').forEach((section) => section.classList.toggle('is-active', section.id === `view-${view}`));
  $$('.nav-item, .mobile-tabs button').forEach((button) => button.classList.toggle('is-active', button.dataset.view === view));
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

function bindNavigation() {
  $$('.nav-item, .mobile-tabs button').forEach((button) => {
    button.addEventListener('click', () => setView(button.dataset.view));
  });
  $$('[data-view-target]').forEach((button) => {
    button.addEventListener('click', () => setView(button.dataset.viewTarget));
  });
}

function linePath(values, width, height, minValue, maxValue) {
  const range = maxValue - minValue || 1;
  const step = values.length > 1 ? width / (values.length - 1) : width;
  const points = values.map((value, index) => {
    const x = index * step;
    const y = height - ((value - minValue) / range) * height;
    return [x, y];
  });
  const path = points.map(([x, y], index) => `${index ? 'L' : 'M'} ${x.toFixed(2)} ${y.toFixed(2)}`).join(' ');
  return { path, points };
}

function renderMultiChart(element, project, mode = 'all') {
  const width = 980;
  const height = 250;
  const padding = 10;
  const series = mode === 'finance'
    ? [project.debt, project.escrow]
    : [project.cashflow, project.debt, project.escrow];
  const values = series.flat().concat([0]);
  const rawMin = Math.min(...values);
  const rawMax = Math.max(...values);
  const buffer = Math.max((rawMax - rawMin) * 0.12, 1);
  const minValue = rawMin - buffer;
  const maxValue = rawMax + buffer;
  const innerHeight = height - padding * 2;
  const cash = linePath(project.cashflow, width, innerHeight, minValue, maxValue);
  const debt = linePath(project.debt, width, innerHeight, minValue, maxValue);
  const escrow = linePath(project.escrow, width, innerHeight, minValue, maxValue);
  const zeroY = padding + innerHeight - ((0 - minValue) / (maxValue - minValue)) * innerHeight;
  const gridLines = [0, .25, .5, .75, 1].map((fraction) => {
    const y = padding + innerHeight * fraction;
    return `<line class="chart-grid" x1="0" y1="${y}" x2="${width}" y2="${y}"></line>`;
  }).join('');
  const area = `${cash.path} L ${width} ${zeroY} L 0 ${zeroY} Z`;
  const dots = (points, className, color) => points.map(([x, y], index) => {
    if (index !== points.length - 1) return '';
    return `<circle class="chart-dot ${className}" cx="${x}" cy="${y + padding}" r="5" fill="${color}"></circle>`;
  }).join('');

  element.innerHTML = `
    <svg viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" role="img" aria-label="График динамики проекта">
      <defs>
        <linearGradient id="cashGradient-${mode}" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stop-color="#38d7ff" stop-opacity=".32"></stop>
          <stop offset="1" stop-color="#38d7ff" stop-opacity="0"></stop>
        </linearGradient>
      </defs>
      ${gridLines}
      <line class="chart-zero" x1="0" y1="${zeroY}" x2="${width}" y2="${zeroY}"></line>
      ${mode === 'all' ? `<path d="${area}" fill="url(#cashGradient-${mode})"></path>` : ''}
      ${mode === 'all' ? `<path class="chart-cash" d="${cash.path}" transform="translate(0 ${padding})"></path>${dots(cash.points, 'cash-dot', '#38d7ff')}` : ''}
      <path class="chart-debt" d="${debt.path}" transform="translate(0 ${padding})"></path>
      <path class="chart-escrow" d="${escrow.path}" transform="translate(0 ${padding})"></path>
      ${dots(debt.points, 'debt-dot', '#ffb957')}
      ${dots(escrow.points, 'escrow-dot', '#27d7a2')}
    </svg>`;
}

function renderTimeline(element, labels) {
  element.innerHTML = labels.map((label) => `<span>${escapeHtml(label)}</span>`).join('');
}

function renderDecision(project) {
  const belowTarget = project.kpi.llcr < 1.2;
  const isMytishchi = project.slug === 'mytishchi';
  const headline = isMytishchi
    ? 'Сильная третья очередь пока оплачивает слабость первой'
    : 'Проект прибыльный, но кредитная устойчивость ниже целевой';
  const copy = isMytishchi
    ? 'Без цены входа вывод о покупке не формируется. О1 убыточна, а общий LLCR держится ниже 1,20x — проект нельзя оценивать только по консолидированной прибыли.'
    : 'LLCR ниже 1,20x, а фактический пик БРИДЖа существенно выше расчётного. Нужна настройка цены покупки, сроков, себестоимости и земельных платежей.';
  $('#decisionCard').innerHTML = `
    <span class="eyebrow">Инвестиционный вывод</span>
    <h2>${headline}</h2>
    <p>${copy}</p>
    <div class="decision-meta"><span>${escapeHtml(project.status)}</span><span>${escapeHtml(project.source)}</span><span>${belowTarget ? 'Ковенант не держится' : 'Ковенант выполнен'}</span></div>`;
}

function renderGauge(project) {
  const llcr = project.kpi.llcr;
  const score = Math.max(0, Math.min(100, (llcr / 1.35) * 100));
  const color = llcr >= 1.2 ? '#27d7a2' : llcr >= 1.1 ? '#ffb957' : '#ff667a';
  $('#llcrGauge').style.setProperty('--value', score.toFixed(1));
  $('#llcrGauge').style.setProperty('--gauge-color', color);
  $('#llcrGaugeValue').textContent = `${llcr.toFixed(2).replace('.', ',')}x`;
  $('#llcrChip').textContent = llcr >= 1.2 ? 'Цель выполнена' : `−${(1.2 - llcr).toFixed(2).replace('.', ',')}x до цели`;
  $('#llcrChip').style.color = llcr >= 1.2 ? '#66e5bd' : '';
  $('#llcrComment').textContent = llcr >= 1.2
    ? 'Долговая нагрузка покрывается денежным потоком с нормативным запасом.'
    : 'Денежного потока недостаточно для целевого запаса обслуживания долга.';
}

function renderKpis(project) {
  const k = project.kpi;
  const cards = [
    { icon: icons.revenue, label: 'Выручка', value: formatBn(k.revenue), note: 'весь проект' },
    { icon: icons.costs, label: 'Расходы', value: formatBn(k.costs), note: `${((k.costs / k.revenue) * 100).toFixed(1).replace('.', ',')}% выручки` },
    { icon: icons.profit, label: 'Чистая прибыль', value: formatBn(k.netProfit), note: `маржа ${k.margin.toFixed(1).replace('.', ',')}%`, tone: k.netProfit > 0 ? 'good' : 'critical' },
    { icon: icons.bridge, label: 'Пик БРИДЖа', value: formatBn(k.bridgePeak), note: `расчётный ${formatBn(k.bridgeCalc)}`, tone: k.bridgePeak > k.bridgeCalc * 2 ? 'critical' : '' },
    { icon: icons.pf, label: 'Пиковый долг ПФ', value: formatBn(k.pfPeak), note: 'не покрыт эскроу' },
    { icon: '₽', label: 'Проценты и комиссии', value: formatBn(k.interest), note: `${((k.interest / k.costs) * 100).toFixed(1).replace('.', ',')}% расходов` },
  ];
  $('#kpiGrid').innerHTML = cards.map(kpiCard).join('');
}

function renderCosts(project) {
  const max = Math.max(...project.costStructure.map((item) => item.value));
  $('#costBars').innerHTML = project.costStructure.map((item) => `
    <div class="cost-row">
      <label>${escapeHtml(item.name)}</label><strong>${formatBn(item.value)}</strong>
      <div class="cost-track"><i style="width:${Math.max(5, item.value / max * 100)}%"></i></div>
    </div>`).join('');
}

function renderProducts(project) {
  const colors = ['#2f8cff', '#38d7ff', '#7b61ff', '#27d7a2', '#ffb957'];
  let cursor = 0;
  const gradient = project.products.map((item, index) => {
    const start = cursor;
    cursor += item.share;
    return `${colors[index % colors.length]} ${start}% ${cursor}%`;
  }).join(', ');
  $('#productDonut').style.setProperty('--segments', `conic-gradient(${gradient})`);
  $('#productLegend').innerHTML = project.products.map((item, index) => `
    <div class="product-item"><i style="background:${colors[index % colors.length]}"></i><span>${escapeHtml(item.name)}</span><strong>${item.share.toFixed(1).replace('.', ',')}%</strong></div>`).join('');
}

function renderRisks(project) {
  $('#riskList').innerHTML = project.risks.map((risk, index) => `
    <div class="risk-item"><i>${String(index + 1).padStart(2, '0')}</i><span>${escapeHtml(risk)}</span></div>`).join('');
}

function renderTep(project) {
  const t = project.tep;
  const cards = [
    { icon: icons.gns, label: 'ГНС проекта', value: `${formatInt(t.gns)} м²`, note: 'совокупный объём' },
    { icon: icons.saleable, label: 'Продаваемая площадь', value: `${formatInt(t.saleable)} м²`, note: `${(t.saleable / t.gns * 100).toFixed(1).replace('.', ',')}% ГНС` },
    { icon: icons.apartments, label: 'Квартиры', value: `${formatInt(t.apartments)} м²`, note: 'продаваемая площадь' },
    { icon: icons.parking, label: 'Паркинг', value: `${formatInt(t.parking)} м/м`, note: 'подземные места' },
  ];
  $('#tepGrid').innerHTML = cards.map(kpiCard).join('');
  $('#tepSource').textContent = project.source;

  const blocks = [
    { name: 'Жильё', value: t.apartments, color: '#2f8cff' },
    { name: 'Коммерция', value: t.commercial || 0, color: '#38d7ff' },
    { name: 'Офисы', value: t.offices || 0, color: '#7b61ff' },
    { name: 'Паркинг', value: t.parking * 35, color: '#27d7a2' },
  ].filter((item) => item.value > 0);
  const maxBlock = Math.max(...blocks.map((item) => item.value));
  $('#buildingStack').innerHTML = blocks.map((item) => `
    <div class="building-block" style="height:${Math.max(52, item.value / maxBlock * 270)}px;border-color:${item.color};background:linear-gradient(to top, ${item.color}55, ${item.color}12)"><label>${escapeHtml(item.name)}</label></div>`).join('');

  const social = [
    t.kindergarten ? `ДОУ: ${formatInt(t.kindergarten)} мест` : '',
    t.school ? `СОШ: ${formatInt(t.school)} мест` : '',
    t.clinic ? `Поликлиника: ${formatInt(t.clinic)} посещений` : '',
  ].filter(Boolean).join(' · ');
  $('#landCards').innerHTML = `
    <div class="land-card"><span>Смена ВРИ / земельные права</span><strong>${formatBn(t.vri)}</strong><small>Должна попадать в cash flow по выбранному графику платежей.</small></div>
    <div class="land-card"><span>Социальная инфраструктура</span><strong>${formatInt((t.kindergarten || 0) + (t.school || 0) + (t.clinic || 0))}</strong><small>${escapeHtml(social || 'Нет отдельных объектов')}</small></div>
    <div class="land-card"><span>Коммерция и офисы</span><strong>${formatInt((t.commercial || 0) + (t.offices || 0))} м²</strong><small>Продаваемая нежилая площадь проекта.</small></div>`;
}

function renderFinance(project) {
  const k = project.kpi;
  $('#financeKpis').innerHTML = [
    { icon: icons.bridge, label: 'Расчётный БРИДЖ', value: formatBn(k.bridgeCalc), note: 'структура до РнС' },
    { icon: '▲', label: 'Фактический пик', value: formatBn(k.bridgePeak), note: `${(k.bridgePeak / k.bridgeCalc).toFixed(1).replace('.', ',')}x расчётного`, tone: 'critical' },
    { icon: icons.pf, label: 'Пиковый долг ПФ', value: formatBn(k.pfPeak), note: 'не покрыт эскроу' },
    { icon: '₽', label: 'Стоимость финансирования', value: formatBn(k.interest), note: 'проценты и комиссии' },
    { icon: '✓', label: 'Долг на конец', value: '0,0 млрд ₽', note: 'по контрольному отчёту', tone: 'good' },
    { icon: '×', label: 'LLCR', value: `${k.llcr.toFixed(2).replace('.', ',')}x`, note: 'цель 1,20x', tone: k.llcr >= 1.2 ? 'good' : 'critical' },
  ].map(kpiCard).join('');
  renderMultiChart($('#financeChart'), project, 'finance');
  renderTimeline($('#financeTimeline'), project.timeline);
}

function renderPhases(project) {
  $('#phaseRows').innerHTML = project.phases.map((phase) => `
    <div class="phase-row"><label>${escapeHtml(phase.name)}</label><div class="phase-track"><i class="phase-bar tone-${phase.tone}" style="left:${phase.start}%;width:${phase.length}%"></i></div></div>`).join('');
  if (!project.queues.length) {
    $('#queueTable').innerHTML = '<div class="empty-state">Очередность не включена. Экран остаётся компактным для одностадийного проекта.</div>';
    return;
  }
  $('#queueTable').innerHTML = `
    <table>
      <thead><tr><th>Очередь</th><th>ГНС, м²</th><th>Прод., м²</th><th>Выручка</th><th>Расходы</th><th>Прибыль</th><th>LLCR</th></tr></thead>
      <tbody>${project.queues.map((q) => `<tr>
        <td><strong>${q.name}</strong></td><td>${formatInt(q.gns)}</td><td>${formatInt(q.saleable)}</td><td>${formatBn(q.revenue)}</td><td>${formatBn(q.costs)}</td>
        <td class="${q.profit < 0 ? 'negative' : 'positive'}">${formatBn(q.profit)}</td><td class="${q.llcr < 1.2 ? 'negative' : 'positive'}">${q.llcr.toFixed(2).replace('.', ',')}x</td>
      </tr>`).join('')}</tbody>
    </table>`;
}

function renderTornado(project) {
  const spreads = project.sensitivity.map((row) => Math.max(Math.abs(row.base - row.low), Math.abs(row.high - row.base)));
  const maxSpread = Math.max(...spreads, .01);
  $('#tornadoChart').innerHTML = project.sensitivity.map((row) => {
    const lowWidth = Math.abs(row.base - row.low) / maxSpread * 48;
    const highWidth = Math.abs(row.high - row.base) / maxSpread * 48;
    return `
      <div class="tornado-row">
        <label>${escapeHtml(row.name)}</label>
        <div class="tornado-track"><i class="tornado-low" style="width:${lowWidth}%"></i><i class="tornado-high" style="width:${highWidth}%"></i></div>
        <strong>${row.base.toFixed(3).replace('.', ',')}</strong>
      </div>`;
  }).join('');
}

function renderPlaton(project) {
  const answer = project.slug === 'mytishchi'
    ? 'Главная проблема — первая очередь: чистая прибыль отрицательная, LLCR 0,98x. Консолидированный результат маскирует зависимость проекта от О3. До решения о входе нужно задать цену покупки и проверить разрыв между расчётным и фактическим БРИДЖем.'
    : 'Главная проблема — не прибыль, а ликвидность. LLCR 1,12x ниже цели, а фактический пик БРИДЖа 2,17 млрд ₽ против расчётных 0,83 млрд ₽. Сначала проверил бы график ВРИ, срок до РнС и цену входа.';
  $('#platonAnswer').textContent = answer;
}

function renderProject(project) {
  state.project = project;
  $('#projectName').textContent = project.name;
  $('#projectRegion').textContent = project.region;
  $('#projectSubtitle').textContent = project.subtitle;
  $('#projectButtonName').textContent = project.name;
  $('#projectButtonRegion').textContent = project.region;
  renderDecision(project);
  renderGauge(project);
  renderKpis(project);
  renderMultiChart($('#cashflowChart'), project, 'all');
  renderTimeline($('#chartTimeline'), project.timeline);
  renderCosts(project);
  renderProducts(project);
  renderRisks(project);
  renderTep(project);
  renderFinance(project);
  renderPhases(project);
  renderTornado(project);
  renderPlaton(project);
  $$('#projectMenu button').forEach((button) => button.classList.toggle('is-active', button.dataset.slug === project.slug));
  document.title = `${project.name} · DevelopAid 2.0`;
}

async function loadProject(slug) {
  const response = await fetch(`/api/v2/projects/${encodeURIComponent(slug)}`);
  if (!response.ok) throw new Error('Не удалось загрузить проект');
  const project = await response.json();
  renderProject(project);
  history.replaceState(null, '', `/v2?project=${encodeURIComponent(slug)}`);
}

function renderProjectMenu() {
  $('#projectMenu').innerHTML = state.projects.map((project) => `
    <button type="button" data-slug="${escapeHtml(project.slug)}"><strong>${escapeHtml(project.name)}</strong><small>${escapeHtml(project.subtitle)}</small></button>`).join('');
  $$('#projectMenu button').forEach((button) => {
    button.addEventListener('click', async () => {
      $('#projectMenu').hidden = true;
      $('#projectButton').setAttribute('aria-expanded', 'false');
      await loadProject(button.dataset.slug);
    });
  });
}

function bindProjectMenu() {
  $('#projectButton').addEventListener('click', () => {
    const menu = $('#projectMenu');
    menu.hidden = !menu.hidden;
    $('#projectButton').setAttribute('aria-expanded', String(!menu.hidden));
  });
  document.addEventListener('click', (event) => {
    if (!event.target.closest('.project-switcher')) {
      $('#projectMenu').hidden = true;
      $('#projectButton').setAttribute('aria-expanded', 'false');
    }
  });
}

// --- Поиск ТЭП: настоящий движок, та же точка, что у кнопки бота -----------

const tepSearch = { region: 'msk', busy: false };

function detectRegionFromQuery(query) {
  const cadastral = String(query).match(/(\d{2}):\d{2}:/);
  if (!cadastral) return null;
  return cadastral[1] === '50' ? 'mo' : cadastral[1] === '77' ? 'msk' : null;
}

function setTepSearchRegion(region) {
  tepSearch.region = region;
  $$('.region-chip').forEach((chip) => chip.classList.toggle('is-active', chip.dataset.region === region));
  $('#tepSearchMoFields').hidden = region !== 'mo';
}

async function runTepSearch() {
  if (tepSearch.busy) return;
  const status = $('#tepSearchStatus');
  const result = $('#tepSearchResult');
  const download = $('#tepSearchDownload');
  const query = $('#tepSearchQuery').value.trim();
  const area = Number($('#tepSearchArea').value || 0);
  if (!query && !(tepSearch.region === 'mo' && area > 0)) {
    status.textContent = 'Введите кадастровый номер или адрес участка — либо площадь в гектарах для Подмосковья.';
    return;
  }
  // Плотность в метрике ГлавАПУ: до 1000 — тыс. м² СПП/га, больше — уже
  // м² квартир/га. Конверсия та же, что в боте: 94% жилой доли, 65% выхода.
  const rawDensity = Number($('#tepSearchDensity').value || 0);
  const density = rawDensity > 0
    ? (rawDensity <= 1000 ? rawDensity * 1000 * 0.94 * 0.65 : rawDensity)
    : null;
  tepSearch.busy = true;
  status.textContent = 'Считаю ТЭП и ВРИ…';
  result.hidden = true;
  download.hidden = true;
  if ($('#tepSearchTemplate')) $('#tepSearchTemplate').hidden = true;
  try {
    const response = await fetch('/api/v2/tep-search', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        region: tepSearch.region,
        query,
        site_area_ha: tepSearch.region === 'mo' && area > 0 ? area : null,
        district: tepSearch.region === 'mo' ? ($('#tepSearchDistrict').value.trim() || null) : null,
        density_sqm_per_ha: tepSearch.region === 'mo' ? density : null,
      }),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || 'Расчёт не получился');
    // Карточка приходит той же разметкой, что в Telegram: наш собственный
    // серверный HTML с <b>/<i>/<code>.
    result.innerHTML = payload.card.replace(/\n/g, '<br>');
    result.hidden = false;
    const attach = (link, b64, name) => {
      if (!link || !b64) return;
      const bytes = Uint8Array.from(atob(b64), (char) => char.charCodeAt(0));
      const blob = new Blob([bytes], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' });
      if (link.dataset.url) URL.revokeObjectURL(link.dataset.url);
      link.href = link.dataset.url = URL.createObjectURL(blob);
      link.download = name;
      link.hidden = false;
    };
    attach(download, payload.file_b64, payload.filename);
    attach($('#tepSearchTemplate'), payload.template_b64, payload.template_filename);
    status.textContent = 'Готово. Оба файла читаются импортом DevelopAid: шаблон можно поправить и загрузить обратно.';
  } catch (error) {
    status.textContent = String(error.message || error);
  } finally {
    tepSearch.busy = false;
  }
}

function bindTepSearch() {
  if (!$('#tepSearchButton')) return;
  $$('.region-chip').forEach((chip) => {
    chip.addEventListener('click', () => setTepSearchRegion(chip.dataset.region));
  });
  $('#tepSearchQuery').addEventListener('input', () => {
    const detected = detectRegionFromQuery($('#tepSearchQuery').value);
    if (detected && detected !== tepSearch.region) setTepSearchRegion(detected);
  });
  $('#tepSearchQuery').addEventListener('keydown', (event) => {
    if (event.key === 'Enter') runTepSearch();
  });
  $('#tepSearchButton').addEventListener('click', runTepSearch);
}

async function init() {
  bindNavigation();
  bindProjectMenu();
  bindTepSearch();
  const projectsResponse = await fetch('/api/v2/projects');
  if (!projectsResponse.ok) throw new Error('Не удалось получить список проектов');
  state.projects = await projectsResponse.json();
  renderProjectMenu();
  const requested = new URLSearchParams(location.search).get('project');
  const slug = state.projects.some((project) => project.slug === requested) ? requested : 'mishina';
  await loadProject(slug);
  $('#loading').classList.add('is-hidden');
}

init().catch((error) => {
  console.error(error);
  $('#loading').innerHTML = `<p>${escapeHtml(error.message)}</p>`;
});
