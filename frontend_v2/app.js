/* DevelopAid 2.0 — интерфейс единственного результата движка.

   Здесь ничего не считается. Страница отправляет вводные, получает
   ProjectResult и рисует его поля. Единственная арифметика в файле —
   форматирование (рубли в миллиарды) и геометрия графиков (доли круга,
   координаты точек): экономику считает движок, и второй её реализации на
   странице быть не должно. */

const state = {
  projects: [],
  slug: null,
  result: null,
  activeView: 'summary',
};

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

const icons = {
  revenue: '↗', costs: '◫', profit: '₽', margin: '%', bridge: '⌁', pf: '◆',
  gns: '▦', saleable: '▤', apartments: '⌂', commercial: '□', parking: 'P', social: '◎',
};

const LLCR_TARGET = 1.2;

// --- форматирование ---------------------------------------------------------

const num = (value) => (value === null || value === undefined || Number.isNaN(Number(value)))
  ? null : Number(value);

function formatMoney(value) {
  const amount = num(value);
  if (amount === null) return '—';
  const billions = amount / 1e9;
  if (Math.abs(billions) >= 1) {
    return `${billions.toLocaleString('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} млрд ₽`;
  }
  return `${(amount / 1e6).toLocaleString('ru-RU', { maximumFractionDigits: 1 })} млн ₽`;
}

function formatInt(value) {
  const amount = num(value);
  return amount === null ? '—' : amount.toLocaleString('ru-RU', { maximumFractionDigits: 0 });
}

function formatRatio(value, digits = 2) {
  const amount = num(value);
  return amount === null ? '—' : `${amount.toFixed(digits).replace('.', ',')}x`;
}

function formatPercent(fraction, digits = 1) {
  const amount = num(fraction);
  return amount === null ? '—' : `${(amount * 100).toFixed(digits).replace('.', ',')}%`;
}

function formatMonth(iso) {
  if (!iso) return '';
  const [year, month] = String(iso).split('-');
  return `${month}.${String(year).slice(2)}`;
}

function formatDateTime(iso) {
  if (!iso) return '—';
  const date = new Date(iso);
  return Number.isNaN(date.getTime())
    ? String(iso)
    : date.toLocaleString('ru-RU', { dateStyle: 'short', timeStyle: 'short' });
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

// --- графики: только геометрия ---------------------------------------------

function linePath(values, width, height, minValue, maxValue) {
  const range = maxValue - minValue || 1;
  const step = values.length > 1 ? width / (values.length - 1) : width;
  const points = values.map((value, index) => {
    const x = index * step;
    const y = height - ((Number(value || 0) - minValue) / range) * height;
    return [x, y];
  });
  const path = points.map(([x, y], index) => `${index ? 'L' : 'M'} ${x.toFixed(2)} ${y.toFixed(2)}`).join(' ');
  return { path, points };
}

function renderMultiChart(element, mode = 'all') {
  const monthly = state.result.monthly || {};
  const cash = (monthly.cashflow_project || []).map((value) => Number(value || 0));
  const debt = (monthly.pf_balance || []).map((value, index) => Number(value || 0) + Number((monthly.bridge_balance || [])[index] || 0));
  const escrow = (monthly.escrow || []).map((value) => Number(value || 0));
  const width = 980;
  const height = 250;
  const padding = 10;
  const series = mode === 'finance' ? [debt, escrow] : [cash, debt, escrow];
  const values = series.flat().concat([0]);
  if (!values.length) { element.innerHTML = ''; return; }
  const rawMin = Math.min(...values);
  const rawMax = Math.max(...values);
  const buffer = Math.max((rawMax - rawMin) * 0.12, 1);
  const minValue = rawMin - buffer;
  const maxValue = rawMax + buffer;
  const innerHeight = height - padding * 2;
  const cashLine = linePath(cash, width, innerHeight, minValue, maxValue);
  const debtLine = linePath(debt, width, innerHeight, minValue, maxValue);
  const escrowLine = linePath(escrow, width, innerHeight, minValue, maxValue);
  const zeroY = padding + innerHeight - ((0 - minValue) / (maxValue - minValue)) * innerHeight;
  const gridLines = [0, .25, .5, .75, 1].map((fraction) => {
    const y = padding + innerHeight * fraction;
    return `<line class="chart-grid" x1="0" y1="${y}" x2="${width}" y2="${y}"></line>`;
  }).join('');
  const area = `${cashLine.path} L ${width} ${zeroY} L 0 ${zeroY} Z`;
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
      ${mode === 'all' ? `<path class="chart-cash" d="${cashLine.path}" transform="translate(0 ${padding})"></path>${dots(cashLine.points, 'cash-dot', '#38d7ff')}` : ''}
      <path class="chart-debt" d="${debtLine.path}" transform="translate(0 ${padding})"></path>
      <path class="chart-escrow" d="${escrowLine.path}" transform="translate(0 ${padding})"></path>
      ${dots(debtLine.points, 'debt-dot', '#ffb957')}
      ${dots(escrowLine.points, 'escrow-dot', '#27d7a2')}
    </svg>`;
}

function renderTimeline(element) {
  const months = (state.result.monthly || {}).months || [];
  if (!months.length) { element.innerHTML = ''; return; }
  const picks = 7;
  const labels = [];
  for (let index = 0; index < picks; index += 1) {
    labels.push(months[Math.round((months.length - 1) * (index / (picks - 1)))]);
  }
  element.innerHTML = labels.map((iso) => `<span>${escapeHtml(formatMonth(iso))}</span>`).join('');
}

// --- разделы ----------------------------------------------------------------

function renderMeta() {
  const result = state.result;
  $('#engineBadge').textContent = `Движок ${result.engine_version}`;
  $('#resultMeta').innerHTML = [
    `<span>Расчёт <code>${escapeHtml(String(result.calculation_id).slice(0, 12))}</code></span>`,
    `<span>${escapeHtml(formatDateTime(result.calculated_at))}</span>`,
    `<span title="${escapeHtml(result.input_hash)}">вводные <code>${escapeHtml(String(result.input_hash).slice(7, 19))}</code></span>`,
    `<span>${escapeHtml(result.engine_entry_point)}</span>`,
  ].join('');
}

function renderDecision() {
  const result = state.result;
  const verdict = result.verdict || {};
  const llcr = num(result.kpi.llcr);
  const covenant = llcr === null ? '—' : (llcr >= LLCR_TARGET ? 'Ковенант выполнен' : 'Ковенант не держится');
  $('#decisionCard').innerHTML = `
    <span class="eyebrow">Инвестиционный вывод</span>
    <h2>${escapeHtml(verdict.title || 'Вывод не сформирован')}</h2>
    <p>${escapeHtml(verdict.text || '')}</p>
    <div class="decision-meta"><span>${escapeHtml(result.project.source_label || 'Расчёт движка DevelopAid')}</span><span>${escapeHtml(covenant)}</span></div>`;
}

function renderGauge() {
  const llcr = num(state.result.kpi.llcr) ?? 0;
  const score = Math.max(0, Math.min(100, (llcr / 1.35) * 100));
  const color = llcr >= LLCR_TARGET ? '#27d7a2' : llcr >= 1.1 ? '#ffb957' : '#ff667a';
  $('#llcrGauge').style.setProperty('--value', score.toFixed(1));
  $('#llcrGauge').style.setProperty('--gauge-color', color);
  $('#llcrGaugeValue').textContent = formatRatio(llcr);
  $('#llcrChip').textContent = llcr >= LLCR_TARGET ? 'Цель выполнена' : 'Ниже цели 1,20x';
  $('#llcrComment').textContent = llcr >= LLCR_TARGET
    ? 'Долговая нагрузка покрывается денежным потоком с нормативным запасом.'
    : 'Денежного потока недостаточно для целевого запаса обслуживания долга.';
}

function renderKpis() {
  const kpi = state.result.kpi;
  const financing = state.result.financing || {};
  const netProfit = num(kpi.net_profit) ?? 0;
  const cards = [
    { icon: icons.revenue, label: 'Выручка', value: formatMoney(kpi.revenue), note: 'весь проект' },
    { icon: icons.costs, label: 'Расходы всего', value: formatMoney(kpi.total_expenses), note: 'CAPEX, коммерческие и финансирование' },
    { icon: icons.profit, label: 'Чистая прибыль', value: formatMoney(kpi.net_profit), note: `маржа ${formatPercent(kpi.margin)}`, tone: netProfit > 0 ? 'good' : 'critical' },
    { icon: icons.bridge, label: 'Пик БРИДЖа', value: formatMoney(financing.actual_bridge), note: `расчётный ${formatMoney(financing.calculated_bridge)}` },
    { icon: icons.pf, label: 'Пик ПФ без эскроу', value: formatMoney(financing.pf_uncovered_peak), note: `пик тела ${formatMoney(financing.pf_peak)}` },
    { icon: '₽', label: 'Проценты и комиссии', value: formatMoney(kpi.financing_cost), note: `EBITDA ${formatMoney(kpi.ebitda)}` },
  ];
  $('#kpiGrid').innerHTML = cards.map(kpiCard).join('');
}

function renderCosts() {
  const structure = (state.result.capex || {}).structure || [];
  const rows = [...structure].sort((a, b) => Number(b.value || 0) - Number(a.value || 0)).slice(0, 6);
  const max = Math.max(...rows.map((item) => Number(item.value || 0)), 1);
  $('#costBars').innerHTML = rows.map((item) => `
    <div class="cost-row">
      <label>${escapeHtml(item.label)}</label><strong>${formatMoney(item.value)}</strong>
      <div class="cost-track"><i style="width:${Math.max(5, Number(item.value || 0) / max * 100)}%"></i></div>
    </div>`).join('');
}

function renderProducts() {
  const colors = ['#2f8cff', '#38d7ff', '#7b61ff', '#27d7a2', '#ffb957', '#ff667a'];
  const products = ((state.result.revenue || {}).products || [])
    .filter((item) => Number(item.revenue || 0) > 0);
  // Доли круга — геометрия отрисовки, а не показатель: подписи несут рубли.
  const total = products.reduce((sum, item) => sum + Number(item.revenue || 0), 0) || 1;
  let cursor = 0;
  const gradient = products.map((item, index) => {
    const start = cursor;
    cursor += Number(item.revenue || 0) / total * 100;
    return `${colors[index % colors.length]} ${start}% ${cursor}%`;
  }).join(', ');
  $('#productDonut').style.setProperty('--segments', `conic-gradient(${gradient || '#2f8cff 0% 100%'})`);
  $('#productLegend').innerHTML = products.map((item, index) => `
    <div class="product-item"><i style="background:${colors[index % colors.length]}"></i><span>${escapeHtml(item.label)}</span><strong>${formatMoney(item.revenue)}</strong></div>`).join('');
}

function renderRisks() {
  const warnings = state.result.warnings || [];
  if (!warnings.length) {
    $('#riskList').innerHTML = '<div class="empty-state">Движок не сообщил предупреждений по этому расчёту.</div>';
    return;
  }
  $('#riskList').innerHTML = warnings.map((risk, index) => `
    <div class="risk-item"><i>${String(index + 1).padStart(2, '0')}</i><span>${escapeHtml(risk)}</span></div>`).join('');
}

function tepRow(key) {
  return ((state.result.tep || {}).rows || []).find((row) => row.key === key) || {};
}

function renderTep() {
  const result = state.result;
  const total = (result.tep || {}).total || {};
  const apartments = tepRow('apartments');
  const parking = tepRow('underground_parking');
  const cards = [
    { icon: icons.gns, label: 'ГНС проекта', value: `${formatInt(result.kpi.project_gns_sqm ?? total.gns)} м²`, note: 'совокупный объём' },
    { icon: icons.saleable, label: 'Продаваемая площадь', value: `${formatInt(result.kpi.monetizable_saleable_sqm)} м²`, note: 'монетизируемая' },
    { icon: icons.apartments, label: 'Квартиры', value: `${formatInt(apartments.saleable)} м²`, note: `${formatInt(apartments.units)} шт.` },
    { icon: icons.parking, label: 'Подземный паркинг', value: `${formatInt(parking.units)} м/м`, note: `${formatInt(parking.gns)} м² ГНС` },
  ];
  $('#tepGrid').innerHTML = cards.map(kpiCard).join('');
  $('#tepSource').textContent = result.project.source_label || 'Расчёт движка DevelopAid';

  const blocks = ((result.tep || {}).rows || [])
    .filter((row) => Number(row.gns || 0) > 0)
    .map((row) => ({ name: row.label, value: Number(row.gns || 0) }));
  const maxBlock = Math.max(...blocks.map((item) => item.value), 1);
  const palette = ['#2f8cff', '#38d7ff', '#7b61ff', '#27d7a2', '#ffb957', '#ff667a'];
  $('#buildingStack').innerHTML = blocks.map((item, index) => {
    const color = palette[index % palette.length];
    return `<div class="building-block" style="height:${Math.max(52, item.value / maxBlock * 270)}px;border-color:${color};background:linear-gradient(to top, ${color}55, ${color}12)"><label>${escapeHtml(item.name)}</label></div>`;
  }).join('');

  const program = (result.social || {}).program || {};
  const social = [
    program.kindergarten_places ? `ДОУ: ${formatInt(program.kindergarten_places)} мест` : '',
    program.school_places ? `СОШ: ${formatInt(program.school_places)} мест` : '',
    program.clinic_capacity ? `Поликлиника: ${formatInt(program.clinic_capacity)} посещений` : '',
  ].filter(Boolean).join(' · ');
  const vri = (result.vri || {}).totals || {};
  $('#landCards').innerHTML = `
    <div class="land-card"><span>Смена ВРИ / земельные права</span><strong>${formatMoney(vri.amount)}</strong><small>Касса ${formatMoney(vri.cash)} · БРИДЖ ${formatMoney(vri.bridge)} · ПФ ${formatMoney(vri.pf)}</small></div>
    <div class="land-card"><span>Социальная нагрузка</span><strong>${formatMoney((result.social || {}).payment)}</strong><small>${escapeHtml((result.social || {}).payment_mode || '')}${social ? ` · ${social}` : ''}</small></div>
    <div class="land-card"><span>Стоимость проекта</span><strong>${formatMoney(result.kpi.full_project_cost)}</strong><small>CAPEX ${formatMoney(result.kpi.capex)} · коммерческие ${formatMoney(result.kpi.commercial_costs)}</small></div>`;
}

function renderFinance() {
  const financing = state.result.financing || {};
  const kpi = state.result.kpi;
  const ending = num(financing.ending_pf) ?? 0;
  $('#financeKpis').innerHTML = [
    { icon: icons.bridge, label: 'Расчётный БРИДЖ', value: formatMoney(financing.calculated_bridge), note: 'структура до РнС' },
    { icon: '▲', label: 'Фактический пик БРИДЖа', value: formatMoney(financing.actual_bridge), note: `с капитализацией ${formatMoney(financing.bridge_peak_capitalized)}` },
    { icon: icons.pf, label: 'Лимит ПФ', value: formatMoney(financing.pf_limit), note: `пик тела ${formatMoney(financing.pf_peak)}` },
    { icon: '₽', label: 'Стоимость финансирования', value: formatMoney(financing.interest_and_fees), note: `средняя ставка ПФ ${formatPercent(financing.avg_pf_rate)}` },
    { icon: ending > 0 ? '×' : '✓', label: 'Долг ПФ на конец', value: formatMoney(financing.ending_pf), note: ending > 0 ? 'не погашен' : 'погашен полностью', tone: ending > 0 ? 'critical' : 'good' },
    { icon: '×', label: 'LLCR', value: formatRatio(kpi.llcr), note: 'цель 1,20x', tone: (num(kpi.llcr) ?? 0) >= LLCR_TARGET ? 'good' : 'critical' },
  ].map(kpiCard).join('');
  renderMultiChart($('#financeChart'), 'finance');
  renderTimeline($('#financeTimeline'));
}

function renderPhases() {
  const result = state.result;
  const months = (result.monthly || {}).months || [];
  const queues = result.queues || [];
  if (!queues.length) {
    $('#phaseRows').innerHTML = '<div class="empty-state">Проект одноочередной: очередность в расчёте не включена.</div>';
    $('#queueTable').innerHTML = '<div class="empty-state">Сравнение очередей появляется, когда движок считает проект по очередям.</div>';
    return;
  }
  const tones = ['blue', 'amber', 'green', 'violet', 'cyan'];
  // Полоса очереди — её собственный календарь строительства из расчёта,
  // положенный на общую ось месяцев. Никаких сроков здесь не выводится.
  const position = (iso) => {
    const index = months.indexOf(String(iso || '').slice(0, 7) + '-01');
    return index < 0 ? null : index / Math.max(months.length - 1, 1) * 100;
  };
  $('#phaseRows').innerHTML = queues.map((queue, index) => {
    const calendar = queue.calendar || {};
    const start = position(calendar.start) ?? 0;
    const end = position(calendar.end) ?? 100;
    return `<div class="phase-row"><label>${escapeHtml(queue.name)}</label><div class="phase-track"><i class="phase-bar tone-${tones[index % tones.length]}" style="left:${start}%;width:${Math.max(4, end - start)}%"></i></div></div>`;
  }).join('');

  $('#queueTable').innerHTML = `
    <table>
      <thead><tr><th>Очередь</th><th>ГНС, м²</th><th>Прод., м²</th><th>Выручка</th><th>Расходы</th><th>Прибыль</th><th>LLCR</th></tr></thead>
      <tbody>${queues.map((queue) => {
        const kpi = queue.kpi || {};
        const profit = num(kpi.net_profit) ?? 0;
        const llcr = num(kpi.llcr) ?? 0;
        return `<tr>
        <td><strong>${escapeHtml(queue.name)}</strong></td><td>${formatInt(kpi.project_gns_sqm)}</td><td>${formatInt(kpi.monetizable_saleable_sqm)}</td>
        <td>${formatMoney(kpi.revenue)}</td><td>${formatMoney(kpi.total_expenses)}</td>
        <td class="${profit < 0 ? 'negative' : 'positive'}">${formatMoney(kpi.net_profit)}</td>
        <td class="${llcr < LLCR_TARGET ? 'negative' : 'positive'}">${formatRatio(llcr)}</td>
      </tr>`;
      }).join('')}</tbody>
    </table>`;
}

function renderTornado() {
  const sensitivity = state.result.sensitivity;
  const element = $('#tornadoChart');
  if (!sensitivity || !(sensitivity.items || []).length) {
    const reason = state.result.sensitivity_error
      ? `Анализ не выполнен: ${state.result.sensitivity_error}`
      : 'Анализ чувствительности не запрашивался для этого расчёта.';
    element.innerHTML = `<div class="empty-state">${escapeHtml(reason)}</div>`;
    return;
  }
  const base = Number(sensitivity.base.value || 0);
  const digits = Number(sensitivity.base.digits ?? 3);
  const spreads = sensitivity.items.map((row) => Math.max(
    Math.abs(base - Number(row.low_result || base)),
    Math.abs(Number(row.high_result || base) - base),
  ));
  const maxSpread = Math.max(...spreads, .001);
  element.innerHTML = sensitivity.items.map((row) => {
    const lowWidth = Math.abs(base - Number(row.low_result || base)) / maxSpread * 48;
    const highWidth = Math.abs(Number(row.high_result || base) - base) / maxSpread * 48;
    return `
      <div class="tornado-row">
        <label>${escapeHtml(row.label)}</label>
        <div class="tornado-track"><i class="tornado-low" style="width:${lowWidth}%"></i><i class="tornado-high" style="width:${highWidth}%"></i></div>
        <strong>${escapeHtml(Number(row.low_result ?? base).toFixed(digits).replace('.', ','))} → ${escapeHtml(Number(row.high_result ?? base).toFixed(digits).replace('.', ','))}</strong>
      </div>`;
  }).join('');
}

function renderPlaton() {
  const result = state.result;
  const verdict = result.verdict || {};
  const lines = [
    `${verdict.title || 'Вывод не сформирован'}. ${verdict.text || ''}`,
    ...(result.warnings || []),
  ];
  $('#platonAnswer').textContent = lines.join(' ');
}

function renderResult(result) {
  state.result = result;
  const project = result.project || {};
  const title = project.name || (project.cadastral_numbers || []).join(', ') || 'Проект';
  $('#projectName').textContent = title;
  $('#projectRegion').textContent = project.region || '';
  $('#projectSubtitle').textContent = (state.projects.find((item) => item.slug === project.slug) || {}).subtitle
    || (project.cadastral_numbers || []).join(', ')
    || (result.mode === 'phased' ? 'Многоочередной расчёт' : 'Одноочередной расчёт');
  $('#projectButtonName').textContent = title;
  $('#projectButtonRegion').textContent = project.region || '';
  renderMeta();
  renderDecision();
  renderGauge();
  renderKpis();
  renderMultiChart($('#cashflowChart'), 'all');
  renderTimeline($('#chartTimeline'));
  renderCosts();
  renderProducts();
  renderRisks();
  renderTep();
  renderFinance();
  renderPhases();
  renderTornado();
  renderPlaton();
  $$('#projectMenu button').forEach((button) => button.classList.toggle('is-active', button.dataset.slug === project.slug));
  document.title = `${title} · DevelopAid 2.0`;
}

// --- Форма вводных: блоки движка, по одному за раз ------------------------
// Справочник полей приходит с сервера из FIELD_GROUPS — того же, которым
// рисуется действующая страница. Своего списка полей здесь нет: третья копия
// разъехалась бы молча, а поле, которого нет в карте, остаётся мусором.

const form = { blocks: [], defaults: null, step: 0, draft: null };

function draftFromResult(result) {
  // Форма показывает то, из чего посчитан текущий результат: вводные едут
  // вместе с ним полем request.
  const request = (result && result.request) || {};
  return {
    inputs: { ...(form.defaults ? form.defaults.inputs : {}), ...(request.inputs || {}) },
    tep: JSON.parse(JSON.stringify(request.tep || (form.defaults || {}).tep || {})),
    phasing: { ...(form.defaults ? form.defaults.phasing : {}), ...(request.phasing || {}) },
  };
}

function fieldControl(field, value, onChange) {
  const id = `f_${field.key}`;
  let control;
  if (field.type === 'checkbox') {
    control = document.createElement('input');
    control.type = 'checkbox';
    control.checked = value === true;
    control.addEventListener('change', () => onChange(control.checked));
  } else if (field.type === 'select') {
    control = document.createElement('select');
    field.options.forEach((option) => {
      const node = document.createElement('option');
      node.value = option.value;
      node.textContent = option.label;
      control.appendChild(node);
    });
    control.value = value === undefined || value === null ? '' : String(value);
    control.addEventListener('change', () => onChange(control.value));
  } else {
    control = document.createElement('input');
    control.type = field.type === 'date' ? 'date' : 'number';
    if (control.type === 'number') control.step = 'any';
    control.value = value === undefined || value === null ? '' : String(value);
    control.addEventListener('change', () => onChange(
      control.type === 'number'
        ? (control.value === '' ? '' : Number(control.value))
        : control.value));
  }
  control.id = id;
  return control;
}

function fieldRow(field, value, onChange) {
  const row = document.createElement('label');
  row.className = 'input-row';
  const caption = document.createElement('span');
  caption.className = 'input-label';
  caption.textContent = field.label;
  const unit = document.createElement('small');
  unit.textContent = field.unit || '';
  row.append(caption, fieldControl(field, value, onChange), unit);
  return row;
}

function renderInputsBlock(block, host) {
  block.fields.forEach((field) => {
    host.appendChild(fieldRow(field, form.draft.inputs[field.key],
      (value) => { form.draft.inputs[field.key] = value; }));
  });
}

function renderTepBlock(block, host) {
  block.rows.forEach((row) => {
    const group = document.createElement('div');
    group.className = 'input-group';
    const title = document.createElement('h4');
    title.textContent = row.label;
    group.appendChild(title);
    if (!form.draft.tep[row.key]) form.draft.tep[row.key] = { label: row.label };
    row.fields.forEach((field) => {
      group.appendChild(fieldRow(
        { ...field, type: 'number' },
        form.draft.tep[row.key][field.key],
        (value) => { form.draft.tep[row.key][field.key] = value; }));
    });
    host.appendChild(group);
  });
}

function renderPhasingBlock(block, host) {
  block.fields.forEach((field) => {
    host.appendChild(fieldRow(field, form.draft.phasing[field.key], (value) => {
      form.draft.phasing[field.key] = value;
      if (field.key === 'phase_count' || field.key === 'enabled') renderStep();
    }));
  });
  const count = Math.max(1, Math.min(5, Number(form.draft.phasing.phase_count || 1)));
  if (!form.draft.phasing.enabled || count < 2) return;
  const group = document.createElement('div');
  group.className = 'input-group';
  const title = document.createElement('h4');
  title.textContent = 'Доли продуктов по очередям, %';
  group.appendChild(title);
  if (!form.draft.phasing.products) form.draft.phasing.products = {};
  block.products.forEach((product) => {
    const weights = form.draft.phasing.products[product.key] || [];
    const row = document.createElement('div');
    row.className = 'input-row weights-row';
    const caption = document.createElement('span');
    caption.className = 'input-label';
    caption.textContent = product.label;
    row.appendChild(caption);
    for (let index = 0; index < count; index += 1) {
      const cell = document.createElement('input');
      cell.type = 'number';
      cell.step = 'any';
      cell.setAttribute('aria-label', `${product.label}, очередь ${index + 1}`);
      cell.value = weights[index] === undefined ? '' : String(weights[index]);
      cell.addEventListener('change', () => {
        const current = form.draft.phasing.products[product.key] || [];
        while (current.length < count) current.push(0);
        current[index] = cell.value === '' ? 0 : Number(cell.value);
        form.draft.phasing.products[product.key] = current.slice(0, count);
      });
      row.appendChild(cell);
    }
    group.appendChild(row);
  });
  host.appendChild(group);
}

function renderSteps() {
  $('#inputSteps').innerHTML = form.blocks.map((block, index) => `
    <button type="button" data-step="${index}" class="${index === form.step ? 'is-active' : ''}">${escapeHtml(block.title)}</button>`).join('');
  $$('#inputSteps button').forEach((button) => {
    button.addEventListener('click', () => { form.step = Number(button.dataset.step); renderStep(); });
  });
}

function renderStep() {
  const block = form.blocks[form.step];
  if (!block) return;
  $('#inputBlockTitle').textContent = block.title;
  $('#inputProgress').textContent = `Блок ${form.step + 1} из ${form.blocks.length}`;
  $('#inputHint').textContent = block.hint || '';
  $('#inputHint').hidden = !block.hint;
  const host = $('#inputBlock');
  host.innerHTML = '';
  if (block.kind === 'tep') renderTepBlock(block, host);
  else if (block.kind === 'phasing') renderPhasingBlock(block, host);
  else renderInputsBlock(block, host);
  $('#inputPrev').disabled = form.step === 0;
  $('#inputNext').disabled = form.step === form.blocks.length - 1;
  renderSteps();
}

async function submitDraft() {
  const status = $('#inputStatus');
  const project = (state.result && state.result.project) || {};
  status.textContent = 'Считаю движком…';
  try {
    await calculateProject({
      inputs: form.draft.inputs,
      tep: form.draft.tep,
      rates: [],
      phasing: form.draft.phasing,
      project_name: project.name || '',
      region: project.region || '',
      cadastral_numbers: project.cadastral_numbers || [],
      source_label: 'Вводные из формы 2.0',
      scenario: project.scenario || 'base',
      sensitivity: true,
    });
    status.textContent = 'Готово — на «Обзоре» результат этого расчёта.';
    setView('summary');
  } catch (error) {
    status.textContent = String(error.message || error);
  }
}

async function initForm() {
  const response = await fetch('/api/v2/form', { cache: 'no-store' });
  if (!response.ok) throw new Error('Не удалось получить описание формы');
  const description = await response.json();
  form.blocks = description.blocks;
  form.defaults = description.defaults;
  form.draft = draftFromResult(state.result);
  $('#inputPrev').addEventListener('click', () => { form.step -= 1; renderStep(); });
  $('#inputNext').addEventListener('click', () => { form.step += 1; renderStep(); });
  $('#inputCalc').addEventListener('click', submitDraft);
  renderStep();
}

/* Расчёт по произвольным вводным: тот же payload, что шлёт действующее
   мини-приложение. Страница ничего не считает — только отправляет и рисует. */
async function calculateProject(payload) {
  const response = await fetch('/api/v2/calculate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    cache: 'no-store',
    body: JSON.stringify(payload),
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.detail || 'Расчёт не выполнен');
  renderResult(result);
  return result;
}

async function loadProject(slug) {
  const response = await fetch(`/api/v2/projects/${encodeURIComponent(slug)}`, { cache: 'no-store' });
  const result = await response.json();
  if (!response.ok) throw new Error(result.detail || 'Не удалось посчитать проект');
  state.slug = slug;
  renderResult(result);
  // Форма показывает вводные того расчёта, который на экране: иначе правка
  // уйдёт от чужих значений, а выглядеть будет как правка этого проекта.
  if (form.blocks.length) {
    form.draft = draftFromResult(result);
    renderStep();
  }
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
  const projectsResponse = await fetch('/api/v2/projects', { cache: 'no-store' });
  if (!projectsResponse.ok) throw new Error('Не удалось получить список проектов');
  state.projects = await projectsResponse.json();
  renderProjectMenu();
  const requested = new URLSearchParams(location.search).get('project');
  const fallback = (state.projects[0] || {}).slug;
  const slug = state.projects.some((project) => project.slug === requested) ? requested : fallback;
  await loadProject(slug);
  await initForm();
  $('#loading').classList.add('is-hidden');
}

/* Установка на экран. Worker кеширует только оболочку: за расчётом он всегда
   ходит в сеть, потому что сохранённый ProjectResult — это вчерашние цифры,
   выглядящие как сегодняшние. Обновление применяется сразу, без ожидания
   закрытия всех вкладок: устаревшая страница здесь дороже перезагрузки. */
function registerServiceWorker() {
  if (!('serviceWorker' in navigator)) return;
  navigator.serviceWorker.register('/v2/sw.js', { scope: '/v2' }).then((registration) => {
    registration.addEventListener('updatefound', () => {
      const installing = registration.installing;
      if (!installing) return;
      installing.addEventListener('statechange', () => {
        if (installing.state === 'installed' && navigator.serviceWorker.controller) {
          installing.postMessage('skip-waiting');
        }
      });
    });
  }).catch((error) => console.warn('Service worker не зарегистрирован:', error));
  let reloading = false;
  navigator.serviceWorker.addEventListener('controllerchange', () => {
    if (reloading) return;
    reloading = true;
    window.location.reload();
  });
}

if (typeof window !== 'undefined' && typeof document !== 'undefined') {
  registerServiceWorker();
  // Точка входа для формы вводных: оболочка и Telegram-режим зовут её с тем
  // же payload, что уходит из действующего мини-приложения.
  window.DevelopAidV2 = { calculateProject, loadProject, renderResult, state };
  init().catch((error) => {
    console.error(error);
    // Без сети оболочка открывается из кеша, а расчёта нет и быть не может:
    // за ним ходят в движок. Сказать это прямо честнее, чем показать
    // сохранённые цифры или системное «Failed to fetch».
    const offline = !navigator.onLine || error instanceof TypeError;
    $('#loading').innerHTML = offline
      ? '<p>Нет связи с сервером. Приложение открылось из памяти устройства, '
        + 'но расчёт считает движок — без сети показывать нечего.</p>'
      : `<p>${escapeHtml(error.message)}</p>`;
  });
}
