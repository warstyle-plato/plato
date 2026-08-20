/* Structured inputs for two assumptions that are tables, not scalar fields.

   The engine keeps compact string representations because they travel with a
   saved project and are also understood by Excel generation. The UI must not
   expose those transport strings to a user. */

(() => {
  const BASE_TEP_TOTAL_PCT = 90;
  const BASE_TEP_SALEABLE_OF_TOTAL_PCT = 70;
  const PF_STEPS_KEY = 'pf_special_steps';
  const TEP_RATIOS_KEY = 'tep_ratios_custom';

  const ratioKeys = new Set(['apartments', 'ground_commercial', 'standalone_retail', 'offices']);

  function numberText(value, digits = 2) {
    const n = Number(value);
    if (!Number.isFinite(n)) return '';
    return n.toLocaleString('ru-RU', { maximumFractionDigits: digits });
  }

  function parsePfSteps(raw) {
    const matches = [...String(raw || '').matchAll(/(\d+(?:[.,]\d+)?)\s*%?\s*[:=\-–—]\s*(\d+(?:[.,]\d+)?)/g)];
    return matches.map((match) => ({
      coverage: Number(match[1].replace(',', '.')),
      rate: Number(match[2].replace(',', '.')),
    })).filter((row) => Number.isFinite(row.coverage) && Number.isFinite(row.rate))
      .sort((a, b) => a.coverage - b.coverage);
  }

  function serializePfSteps(rows) {
    return rows
      .filter((row) => Number.isFinite(row.coverage) && row.coverage > 0 && Number.isFinite(row.rate) && row.rate >= 0)
      .sort((a, b) => a.coverage - b.coverage)
      .map((row) => `${numberText(row.coverage, 2)}:${numberText(row.rate, 4)}`)
      .join('; ');
  }

  function pfLadder(host, field) {
    const card = document.createElement('section');
    card.className = 'structured-card pf-ladder-card';

    const head = document.createElement('div');
    head.className = 'structured-head';
    head.innerHTML = `
      <div>
        <span class="structured-kicker">Эскроу → ставка</span>
        <h4>Ступени ставки ПФ по покрытию</h4>
        <p>Рабочий пример — НКЛ Сбербанка 400F00BVX003. Значения меняются по условиям конкретного договора.</p>
      </div>
      <span class="structured-chip">редактируемая вводная</span>`;
    card.appendChild(head);

    const baseline = document.createElement('div');
    baseline.className = 'structured-baseline';
    baseline.innerHTML = `<span>До первой ступени</span><strong>${numberText(form.draft.inputs.pf_special_pct, 4) || '—'}%</strong><small>базовая специальная ставка</small>`;
    card.appendChild(baseline);

    const table = document.createElement('div');
    table.className = 'structured-table pf-ladder-table';
    card.appendChild(table);

    const actions = document.createElement('div');
    actions.className = 'structured-actions';
    const add = document.createElement('button');
    add.type = 'button';
    add.className = 'structured-button';
    add.textContent = '+ Добавить ступень';
    const reset = document.createElement('button');
    reset.type = 'button';
    reset.className = 'structured-button is-muted';
    reset.textContent = 'Вернуть пример Сбера';
    actions.append(add, reset);
    card.appendChild(actions);

    const sber = [
      { coverage: 100, rate: 3.47 },
      { coverage: 110, rate: 1.75 },
      { coverage: 120, rate: 0.03 },
      { coverage: 130, rate: 0.01 },
    ];
    let rows = parsePfSteps(form.draft.inputs[PF_STEPS_KEY]);
    if (!rows.length && String(form.draft.inputs[PF_STEPS_KEY] || '').trim()) rows = sber.map((row) => ({ ...row }));

    function persist() {
      form.draft.inputs[PF_STEPS_KEY] = serializePfSteps(rows);
    }

    function draw() {
      table.innerHTML = `
        <div class="structured-tr structured-th"><span>Покрытие эскроу от</span><span>Ставка ПФ</span><span></span></div>`;
      if (!rows.length) {
        const empty = document.createElement('div');
        empty.className = 'structured-empty';
        empty.textContent = 'Ступени выключены — действует одна базовая специальная ставка.';
        table.appendChild(empty);
        return;
      }
      rows.forEach((row, index) => {
        const line = document.createElement('div');
        line.className = 'structured-tr';
        const coverageWrap = document.createElement('label');
        coverageWrap.className = 'structured-number';
        const coverage = document.createElement('input');
        coverage.type = 'number'; coverage.step = '0.1'; coverage.min = '0'; coverage.max = '1000';
        coverage.value = String(row.coverage);
        coverage.setAttribute('aria-label', `Порог покрытия, ступень ${index + 1}`);
        coverageWrap.append(coverage, document.createTextNode('%'));

        const rateWrap = document.createElement('label');
        rateWrap.className = 'structured-number';
        const rate = document.createElement('input');
        rate.type = 'number'; rate.step = '0.01'; rate.min = '0'; rate.max = '100';
        rate.value = String(row.rate);
        rate.setAttribute('aria-label', `Ставка ПФ, ступень ${index + 1}`);
        rateWrap.append(rate, document.createTextNode('%'));

        const remove = document.createElement('button');
        remove.type = 'button';
        remove.className = 'structured-remove';
        remove.title = 'Удалить ступень';
        remove.setAttribute('aria-label', `Удалить ступень ${index + 1}`);
        remove.textContent = '×';

        coverage.addEventListener('change', () => {
          rows[index].coverage = Number(coverage.value);
          persist(); draw();
        });
        rate.addEventListener('change', () => {
          rows[index].rate = Number(rate.value);
          persist();
        });
        remove.addEventListener('click', () => {
          rows.splice(index, 1); persist(); draw();
        });
        line.append(coverageWrap, rateWrap, remove);
        table.appendChild(line);
      });
    }

    add.addEventListener('click', () => {
      const last = rows[rows.length - 1];
      rows.push({ coverage: last ? last.coverage + 10 : 100, rate: last ? last.rate : Number(form.draft.inputs.pf_special_pct || 0) });
      persist(); draw();
    });
    reset.addEventListener('click', () => {
      rows = sber.map((row) => ({ ...row }));
      persist(); draw();
    });
    draw();
    host.appendChild(card);
  }

  function parseRatioOverrides(raw) {
    const out = {};
    String(raw || '').split(';').forEach((part) => {
      const match = part.trim().match(/^([^:]+):\s*(\d+(?:[.,]\d+)?)\s*\/\s*(\d+(?:[.,]\d+)?)$/);
      if (!match) return;
      out[match[1].trim()] = {
        total: Number(match[2].replace(',', '.')),
        saleable: Number(match[3].replace(',', '.')),
      };
    });
    return out;
  }

  function serializeRatioOverrides(overrides) {
    return Object.entries(overrides)
      .filter(([, value]) => value && Number.isFinite(value.total) && Number.isFinite(value.saleable))
      .map(([key, value]) => `${key}:${numberText(value.total, 2)}/${numberText(value.saleable, 2)}`)
      .join(';');
  }

  function ratioFromRow(row) {
    const gns = Number(row.gns || 0);
    const total = Number(row.total_area || 0);
    const saleable = Number(row.saleable || 0);
    return {
      total: gns > 0 && total > 0 ? total / gns * 100 : BASE_TEP_TOTAL_PCT,
      saleable: total > 0 && saleable > 0 ? saleable / total * 100 : BASE_TEP_SALEABLE_OF_TOTAL_PCT,
    };
  }

  function sameNumber(left, right) {
    return Math.abs(Number(left || 0) - Number(right || 0)) < 1e-6;
  }

  function isUntouchedEngineDefault(rowKey, row) {
    const baseline = form.defaults && form.defaults.tep && form.defaults.tep[rowKey];
    if (!baseline) return false;
    return ['gns', 'total_area', 'saleable'].every((key) => sameNumber(row[key], baseline[key]));
  }

  function hasFactualTepSource() {
    const imported = form.draft && form.draft.inputs && form.draft.inputs._glavapu_import;
    const source = String((state.result && state.result.project && state.result.project.source_label) || '').toLowerCase();
    return Boolean(imported) || source.includes('глав') || source.includes('гзк') || source.includes('агр') || source.includes('поиск тэп');
  }

  function applyRatio(row, totalPct, saleablePct) {
    const gns = Number(row.gns || 0);
    if (!(gns > 0)) return;
    row.total_area = gns * totalPct / 100;
    row.saleable = row.total_area * saleablePct / 100;
    if ('useful' in row && Number(row.useful || 0) <= Number(row.saleable || 0)) row.useful = row.saleable;
  }

  function tepRatioStrip(rowKey, row, group, rerender) {
    if (!ratioKeys.has(rowKey)) return;
    const overrides = parseRatioOverrides(form.draft.inputs[TEP_RATIOS_KEY]);
    let current = overrides[rowKey];

    /* Existing project / imported TEP wins. Only an untouched model default may
       inherit the DevelopAid 90% → 70% assumption. A GlavAPU/GZK/AGR fact is
       never rewritten just because the Inputs screen was opened. */
    if (!current && !hasFactualTepSource() && isUntouchedEngineDefault(rowKey, row)) {
      current = { total: BASE_TEP_TOTAL_PCT, saleable: BASE_TEP_SALEABLE_OF_TOTAL_PCT };
      overrides[rowKey] = current;
      form.draft.inputs[TEP_RATIOS_KEY] = serializeRatioOverrides(overrides);
      applyRatio(row, current.total, current.saleable);
    }
    if (!current) current = ratioFromRow(row);

    const strip = document.createElement('div');
    strip.className = 'tep-ratio-strip';
    strip.innerHTML = `
      <div class="tep-ratio-copy">
        <span>ГНС → общая → продаваемая</span>
        <small>Наше умолчание: общая 90% от ГНС; продаваемая 70% от общей. Фактические параметры можно заменить здесь.</small>
      </div>`;

    const total = document.createElement('label');
    total.className = 'tep-ratio-field';
    total.innerHTML = '<span>Общая / ГНС</span>';
    const totalInput = document.createElement('input');
    totalInput.type = 'number'; totalInput.min = '0.1'; totalInput.max = '100'; totalInput.step = '0.1';
    totalInput.value = String(Number(current.total.toFixed(2)));
    total.append(totalInput, document.createTextNode('%'));

    const saleable = document.createElement('label');
    saleable.className = 'tep-ratio-field';
    saleable.innerHTML = '<span>Продаваемая / общей</span>';
    const saleableInput = document.createElement('input');
    saleableInput.type = 'number'; saleableInput.min = '0.1'; saleableInput.max = '100'; saleableInput.step = '0.1';
    saleableInput.value = String(Number(current.saleable.toFixed(2)));
    saleable.append(saleableInput, document.createTextNode('%'));

    const reset = document.createElement('button');
    reset.type = 'button';
    reset.className = 'structured-button is-muted tep-ratio-reset';
    reset.textContent = '90% / 70%';
    reset.title = 'Вернуть пропорции DevelopAid';

    function save(totalPct, saleablePct) {
      if (!(totalPct > 0 && totalPct <= 100 && saleablePct > 0 && saleablePct <= 100)) return;
      overrides[rowKey] = { total: totalPct, saleable: saleablePct };
      form.draft.inputs[TEP_RATIOS_KEY] = serializeRatioOverrides(overrides);
      applyRatio(row, totalPct, saleablePct);
      rerender();
    }

    totalInput.addEventListener('change', () => save(Number(totalInput.value), Number(saleableInput.value)));
    saleableInput.addEventListener('change', () => save(Number(totalInput.value), Number(saleableInput.value)));
    reset.addEventListener('click', () => save(BASE_TEP_TOTAL_PCT, BASE_TEP_SALEABLE_OF_TOTAL_PCT));
    strip.append(total, saleable, reset);
    group.appendChild(strip);
  }

  const baseFieldControl = fieldControl;
  fieldControl = function structuredFieldControl(field, value, onChange) {
    if (field.type !== 'text') return baseFieldControl(field, value, onChange);
    const control = document.createElement('input');
    control.type = 'text';
    control.id = `f_${field.key}`;
    control.value = value === undefined || value === null ? '' : String(value);
    control.addEventListener('change', () => onChange(control.value));
    return control;
  };

  renderInputsBlock = function structuredInputsBlock(block, host) {
    block.fields.forEach((field) => {
      if (field.key === PF_STEPS_KEY) {
        pfLadder(host, field);
        return;
      }
      host.appendChild(fieldRow(field, form.draft.inputs[field.key],
        (value) => { form.draft.inputs[field.key] = value; }));
    });
  };

  renderTepBlock = function structuredTepBlock(block, host) {
    block.rows.forEach((row) => {
      const group = document.createElement('div');
      group.className = 'input-group tep-input-group';
      const title = document.createElement('h4');
      title.textContent = row.label;
      group.appendChild(title);
      if (!form.draft.tep[row.key]) form.draft.tep[row.key] = { label: row.label };

      const rerender = () => renderStep();
      tepRatioStrip(row.key, form.draft.tep[row.key], group, rerender);

      row.fields.forEach((field) => {
        group.appendChild(fieldRow(
          { ...field, type: 'number' },
          form.draft.tep[row.key][field.key],
          (value) => {
            form.draft.tep[row.key][field.key] = value;
            if (field.key === 'gns') {
              const overrides = parseRatioOverrides(form.draft.inputs[TEP_RATIOS_KEY]);
              const ratio = overrides[row.key];
              if (ratio) applyRatio(form.draft.tep[row.key], ratio.total, ratio.saleable);
              rerender();
            }
          }));
      });
      host.appendChild(group);
    });
  };
})();
