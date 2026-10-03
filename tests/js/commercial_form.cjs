// Run with NODE_PATH=<jsdom installation>/node_modules node tests/js/commercial_form.cjs.
// A DOM integration check against the real commercial API, not a browser acceptance test.
const fs=require('fs');
const assert=require('node:assert/strict');
const {JSDOM}=require('jsdom');
const base=process.env.COMMERCIAL_TEST_URL || 'http://127.0.0.1:8000';
const dom=new JSDOM(fs.readFileSync('commercial_site_panel.html','utf8'),{url:base,runScripts:'outside-only'});
const w=dom.window, d=w.document;
let calls=[], results=[];
w.fetch=async(url,options)=>{
  const response=await fetch(base+url,options);
  if(options?.body) calls.push(JSON.parse(options.body));
  if(options?.body && response.ok) results.push(await response.clone().json());
  return response;
};
w.eval(fs.readFileSync('commercial_site.js','utf8'));
const waitFor=async(test)=>{
  for(let n=0;n<300;n++) {if(test())return; await new Promise(r=>setTimeout(r,10));}
  throw new Error('UI did not settle: '+d.getElementById('ce-status').textContent+' '+d.getElementById('ce-error').textContent);
};
const settled=()=>waitFor(()=>d.getElementById('ce-status').textContent==='Расчёт актуален.');
const change=async(id,value)=>{
  const el=d.getElementById(id); el.value=value;
  el.dispatchEvent(new w.Event('change',{bubbles:true})); await settled();
};
(async()=>{
  await w.commercialEnsureInit(); await settled();
  for(const asset of ['office','retail','hotel']) {
    await change('ce-asset',asset);
    for(const strategy of ['income','sale']){
      await change('ce-strategy',strategy);
      for(const financing of ['equity','equity_debt']){
        await change('ce-financing',financing);
        assert.equal(!!d.getElementById('ce-debt_rate_pct'),financing==='equity_debt');
        assert.equal(!!d.getElementById('ce-exit_cap_rate_pct'),strategy==='income');
        assert.equal(!!d.getElementById('ce-sale_price_rub_key'),asset==='hotel'&&strategy==='sale');
        assert.equal(d.getElementById('ce-operations').hidden,strategy!=='income');
        assert.ok(d.querySelectorAll('#ce-kpis .ce-kpi').length>=16);
        assert.ok(d.querySelectorAll('#ce-monthly tbody tr').length>12);
        const result=results.at(-1), picker=d.getElementById('ce-month-picker');
        const last=result.monthly.months.length-1;
        assert.equal(picker.options.length,last+1);
        assert.equal(d.querySelectorAll('#ce-monthly thead th').length,financing==='equity_debt'?4:3);
        assert.equal(!!d.querySelector('[data-series="debt_draw"]'),financing==='equity_debt');
        picker.value=last;picker.dispatchEvent(new w.Event('change',{bubbles:true}));
        const formatMoney=v=>new Intl.NumberFormat('ru-RU',{maximumFractionDigits:2}).format(v)+' ₽';
        assert.equal(d.querySelector('[data-series="equity_cashflow"] dd').textContent,formatMoney(result.monthly.equity_cashflow[last]));
        assert.equal(d.getElementById('ce-month-next').disabled,true);
        d.getElementById('ce-month-prev').click();
        assert.equal(Number(picker.value),last-1);
        assert.equal(d.querySelector('[data-series="project_cashflow"] dd').textContent,formatMoney(result.monthly.project_cashflow[last-1]));
        picker.value=0;picker.dispatchEvent(new w.Event('change',{bubbles:true}));
        assert.equal(d.getElementById('ce-month-prev').disabled,true);
        if(strategy==='sale') assert.ok(d.querySelector('[data-series="sale_quantity"]'));
        else assert.ok(d.querySelector('[data-series="operating_revenue"]'));
        assert.ok(d.querySelectorAll('#ce-annual tbody tr').length>1);
        const request=calls.at(-1);
        assert.equal(request.asset_type,asset);assert.equal(request.strategy,strategy);assert.equal(request.financing_mode,financing);
      }
    }
  }
  await change('ce-asset','retail');await change('ce-strategy','income');
  const rent=d.getElementById('ce-rent_rub_sqm_month');rent.value=12345;
  rent.dispatchEvent(new w.Event('input',{bubbles:true}));
  assert.equal(d.getElementById('ce-results').dataset.stale,'true');
  d.getElementById('ce-form').dispatchEvent(new w.Event('submit',{cancelable:true}));await settled();
  assert.equal(calls.at(-1).inputs.rent_rub_sqm_month,12345);
  await change('ce-strategy','sale');await change('ce-strategy','income');
  assert.equal(d.getElementById('ce-rent_rub_sqm_month').value,'12345');
  await change('ce-asset','hotel');await change('ce-asset','retail');
  assert.equal(d.getElementById('ce-rent_rub_sqm_month').value,'12345');
  w.fetch=async()=>{throw new Error('network unavailable');};
  d.getElementById('ce-form').dispatchEvent(new w.Event('submit',{cancelable:true}));
  await waitFor(()=>!d.getElementById('ce-error').hidden);
  assert.match(d.getElementById('ce-error').textContent,/network unavailable/);
  console.log('PASS: 12 combinations, native fields, KPI/CF rendering, entered values, switches, network error');
})().catch(e=>{console.error(e);process.exitCode=1;}).finally(()=>dom.window.close());
