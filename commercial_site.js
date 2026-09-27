/* Native commercial form; all financial arithmetic belongs to the Python engine. */
(function () {
  'use strict';
  const $ = id => document.getElementById(id);
  const fmt = new Intl.NumberFormat('ru-RU', {maximumFractionDigits: 2});
  const money = v => v == null ? '—' : fmt.format(v) + ' ₽';
  const percent = v => v == null ? '—' : fmt.format(v * 100) + '%';
  const multiple = v => v == null ? '—' : fmt.format(v) + '×';
  let schema, loading, currentAsset = 'office', values = {}, revision = 0, initialized = false;
  const saved = {};
  const selection = () => [$('ce-asset').value, $('ce-strategy').value, $('ce-financing').value];
  function element(tag, text, cls) {
    const el = document.createElement(tag);
    if (text != null) el.textContent = text;
    if (cls) el.className = cls;
    return el;
  }
  function capture() {
    document.querySelectorAll('#ce-fields [data-field]').forEach(el => {
      values[el.dataset.field] = el.type === 'number' ? (el.value === '' ? null : Number(el.value)) : el.value;
    });
    saved[currentAsset] = {...values};
  }
  function stale() {
    revision++;
    $('ce-results').dataset.stale = 'true';
    $('ce-status').textContent = 'Параметры изменены — пересчитайте модель.';
    $('ce-error').hidden = true;
  }
  function renderFields() {
    const [asset, strategy, financing] = selection();
    $('ce-fields').replaceChildren();
    schema.groups[selection().join('/')].forEach(group => {
      const fieldset = element('fieldset');
      fieldset.append(element('legend', group.label));
      const grid = element('div', null, 'ce-fields');
      group.keys.forEach(key => {
        const meta = schema.fields.find(f => f.key === key);
        const label = element('label', meta.label + (meta.unit && key !== 'sales_curve' ? ', ' + meta.unit : ''));
        let input;
        if (key === 'sales_curve') {
          input = element('select');
          [['bell','Колокол'],['flat','Равномерно'],['front_loaded','В начале'],['back_loaded','В конце']].forEach(([v,t]) => {
            const option = element('option',t); option.value=v; input.append(option);
          });
        } else {
          input = element('input'); input.type='number'; input.required=true;
          input.min=meta.min; input.max=meta.max; input.step=meta.step;
        }
        input.id='ce-'+key; input.dataset.field=key;
        input.value=values[key] ?? ''; label.htmlFor=input.id;
        label.append(input); grid.append(label);
      });
      fieldset.append(grid); $('ce-fields').append(fieldset);
    });
    $('ce-method').textContent = strategy === 'sale'
      ? 'Продажи поступают напрямую в проект. Эскроу: 0 ₽. Операционные доходы и терминальная стоимость не начисляются.'
      : (asset === 'retail' ? 'Арендная выручка — максимум базовой аренды и процента с оборота. Поэтому изменение меньшей ставки не увеличивает выручку, пока она не превысит большую. ' : '') + 'Эксплуатация начинается после завершения строительства; выход — продажа актива по NOI / cap rate.';
    $('ce-operations').hidden = strategy !== 'income';
  }
  function cards(target, rows) {
    target.replaceChildren();
    rows.forEach(([label,value]) => {
      const card=element('div',null,'ce-kpi'); card.append(element('span',label),element('strong',value)); target.append(card);
    });
  }
  function cashTable(rows, monthly) {
    const columns = [
      [monthly?'month':'year',monthly?'Месяц':'Год','number'],
      ['development_spend','Development'],['operating_revenue','Operating revenue'],
      ['operating_cost','OPEX / TI / fees'],['sale_quantity','Продано, '+(selection()[0]==='hotel'?'номеров':'м²'),'number'],
      ['sale_revenue','Продажи'],['selling_cost','Расходы продаж'],['terminal_value','Exit gross'],
      ['disposition_cost','Расходы выхода'],['project_cashflow','Project CF'],
      ['debt_draw','Выдача кредита'],['interest','Проценты'],['loan_fees','Комиссии'],
      ...(monthly ? [['debt_before_repayment','Долг до погашения']] : []),
      ['debt_repayment','Погашение'],[monthly?'debt_balance':'ending_debt','Остаток долга'],
      ['equity_injection','Взнос equity'],['equity_distribution','Выплата equity'],['equity_cashflow','Equity CF']
    ];
    const table=element('table'), head=element('thead'), hr=element('tr'), body=element('tbody');
    columns.forEach(([,name])=>hr.append(element('th',name))); head.append(hr);
    rows.forEach(row=>{
      const tr=element('tr');
      columns.forEach(([key,,kind])=>tr.append(element('td',row[key] == null ? '—' : fmt.format(kind==='number'?row[key]:row[key]/1e6))));
      body.append(tr);
    }); table.append(head,body); return table;
  }
  function renderResult(result) {
    const k=result.kpi, o=result.operating;
    const income=result.strategy==='income', debt=result.financing_mode==='equity_debt';
    const rows=[['Development cost',money(k.development_cost)],['Operating revenue · весь период',money(k.operating_revenue)],
      ['NOI · год на стабилизации',income?money(k.stabilized_noi_annual):'—'],
      ['Gross exit value',income?money(k.exit_value):'—'],['Net exit value · до погашения долга',income?money(k.net_exit_proceeds):'—'],
      ['Project IRR',percent(k.project_irr)],['Project NPV',money(k.project_npv)],
      ['Equity IRR',percent(k.equity_irr)],['Equity multiple',multiple(k.equity_multiple)],
      ['Equity required · все взносы',money(k.equity_required)],['Peak debt · до погашения',money(k.peak_debt)],
      ['LTC · peak debt / development',percent(k.ltc)],['Exit LTV',income&&debt?percent(k.exit_ltv):'—'],
      ['Interest cover · на пиковый долг',income&&debt?multiple(k.interest_cover):'—'],
      ['Debt yield',income&&debt?percent(k.debt_yield):'—'],['Yield on Cost',income?percent(k.yield_on_cost):'—']];
    if(!income) rows.push(['Выручка продаж',money(k.sale_revenue)],['Прямые поступления · после расходов продаж',money(k.net_sale_proceeds)],['Эскроу',money(0)]);
    cards($('ce-kpis'),rows);
    let operations=[['Загрузка',percent(o.occupancy)],['Operating revenue · месяц',money(o.revenue)],['OPEX · месяц',money(o.opex)],['NOI · месяц',money(o.noi)]];
    if(result.asset_type==='hotel') operations=operations.concat([
      ['ADR',money(o.adr)],['RevPAR',money(o.revpar)],['Room revenue',money(o.room_revenue)],
      ['Other revenue',money(o.other_revenue)],['GOP',money(o.gop)],['Management fee',money(o.management_fee)],['FF&E reserve',money(o.ffe_reserve)]]);
    if(result.asset_type==='office') operations=operations.concat([['Базовая аренда',money(o.base_rent)],['Прочая выручка',money(o.other_revenue)],['Leasing / TI / LC',money(o.leasing_cost)]]);
    if(result.asset_type==='retail') operations=operations.concat([['Базовая аренда',money(o.base_rent)],['Аренда с оборота',money(o.turnover_rent)]]);
    cards($('ce-operating-kpis'),operations);
    $('ce-annual').replaceChildren(cashTable(result.annual,false));
    const monthly=result.monthly.months.map((month,i)=>{
      const row={month}; Object.entries(result.monthly).forEach(([key,series])=>{row[key]=series[i];}); return row;
    });
    $('ce-monthly').replaceChildren(cashTable(monthly,true));
    $('ce-result-context').textContent=selection().map((_,i)=>[$('ce-asset'),$('ce-strategy'),$('ce-financing')][i].selectedOptions[0].textContent).join(' · ');
    $('ce-validation').textContent=result.warnings.filter(w=>!w.startsWith('Beta:')&&!w.startsWith('Продажная модель')).join(' ');
    $('ce-results').hidden=false; $('ce-results').dataset.stale='false';
  }
  async function calculate() {
    if(!initialized) return;
    if(!$('ce-form').reportValidity()) return;
    capture(); const requestRevision=++revision;
    $('ce-status').textContent='Расчёт…'; $('ce-error').hidden=true;
    const [asset,strategy,financing]=selection();
    const inputs={}; schema.groups[selection().join('/')].forEach(g=>g.keys.forEach(k=>inputs[k]=values[k]));
    try {
      const response=await fetch('/api/commercial/calculate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({asset_type:asset,strategy,financing_mode:financing,inputs})});
      const result=await response.json();
      if(!response.ok) throw new Error(typeof result.detail==='string'?result.detail:'Проверьте параметры расчёта.');
      if(requestRevision!==revision) return;
      renderResult(result); $('ce-status').textContent='Расчёт актуален.';
    } catch(error) {
      if(requestRevision!==revision) return;
      $('ce-error').textContent='Не удалось рассчитать: '+error.message; $('ce-error').hidden=false;
      $('ce-status').textContent='Расчёт не выполнен.'; $('ce-results').dataset.stale='true';
    }
  }
  window.commercialEnsureInit = function () {
    if(initialized) return;
    if(loading) return loading;
    loading=(async()=>{
      try {
        const response=await fetch('/api/commercial/form');
        if(!response.ok) throw new Error('HTTP '+response.status);
        schema=await response.json(); values={...schema.defaults[currentAsset]};
        renderFields(); initialized=true;
        $('ce-form').addEventListener('submit',e=>{e.preventDefault();calculate();});
        $('ce-fields').addEventListener('input',stale);
        ['ce-asset','ce-strategy','ce-financing'].forEach(id=>$(id).addEventListener('change',()=>{
          capture(); const asset=selection()[0];
          if(asset!==currentAsset){currentAsset=asset;values={...(saved[asset]||schema.defaults[asset])};}
          stale(); renderFields(); $('ce-results').hidden=true;
          calculate();
        }));
        $('ce-defaults').addEventListener('click',()=>{values={...schema.defaults[currentAsset]};stale();renderFields();calculate();});
        calculate();
      }catch(error){$('ce-error').textContent='Не удалось загрузить параметры: '+error.message+'. Откройте раздел повторно.';$('ce-error').hidden=false;}
      finally{loading=null;}
    })(); return loading;
  };
  // The existing global recalculate action must act on the currently open model.
  document.addEventListener('click',e=>{
    const button=e.target.closest('button');
    if(button && button.textContent.trim()==='Пересчитать модель' && $('commercial').classList.contains('active')){
      e.preventDefault();e.stopImmediatePropagation();calculate();
    }
  },true);
})();
