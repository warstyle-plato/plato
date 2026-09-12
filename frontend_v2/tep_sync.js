(() => {
  'use strict';

  const syncState = {
    derived: {},
    seenImports: new Set(),
    requestSeq: 0,
  };

  function injectStyles() {
    if (document.getElementById('v2TepSyncStyles')) return;
    const style = document.createElement('style');
    style.id = 'v2TepSyncStyles';
    style.textContent = `
      .tep-derived-chip{display:inline-flex;align-items:center;margin-left:7px;padding:2px 7px;border-radius:999px;border:1px solid rgba(56,215,255,.28);background:rgba(56,215,255,.08);color:#8ddfff;font-size:10px;font-weight:700;line-height:1.4;vertical-align:middle;white-space:nowrap}
      .tep-origin-chip{border-color:rgba(39,215,162,.3);background:rgba(39,215,162,.09);color:#79e8c3}
      .tep-sync-note{margin:5px 0 8px;color:#8fa7c1;font-size:11px;line-height:1.45}
      .input-group.is-tep-synced{border-color:rgba(56,215,255,.16)}
    `;
    document.head.appendChild(style);
  }

  function renameTerritoryView() {
    const desktop = document.querySelector('.main-nav [data-view="tep"]');
    if (desktop && !desktop.dataset.v2Renamed) {
      desktop.dataset.v2Renamed = '1';
      const icon = desktop.querySelector('span');
      desktop.textContent = '';
      if (icon) desktop.appendChild(icon);
      desktop.append('Участок и ВРИ');
    }
    const mobile = document.querySelector('.mobile-tabs [data-view="tep"]');
    if (mobile && mobile.textContent.trim() !== 'Участок') mobile.textContent = 'Участок';
    const heading = document.querySelector('#view-tep .section-heading h2');
    if (heading) heading.textContent = 'Участок, ВРИ и обязательства';
    const eyebrow = document.querySelector('#view-tep .section-heading .eyebrow');
    if (eyebrow) eyebrow.textContent = 'Параметры территории';
  }

  function currentTepBlock() {
    try {
      if (typeof form === 'undefined' || !form || !Array.isArray(form.blocks)) return null;
      const block = form.blocks[form.step];
      return block && block.kind === 'tep' ? block : null;
    } catch (error) {
      return null;
    }
  }

  function decorateTepEditor() {
    const block = currentTepBlock();
    const host = document.getElementById('inputBlock');
    if (!block || !host) return;
    const groups = Array.from(host.querySelectorAll('.input-group'));
    groups.forEach((group, index) => {
      const row = block.rows[index];
      if (!row) return;
      group.dataset.rowKey = row.key;
      const meta = syncState.derived[row.key];
      group.classList.toggle('is-tep-synced', Boolean(meta));
      group.querySelectorAll('.tep-derived-chip,.tep-sync-note').forEach((node) => node.remove());
      if (!meta) return;

      const title = group.querySelector('h4');
      if (title && meta.origin) {
        const origin = document.createElement('span');
        origin.className = 'tep-derived-chip tep-origin-chip';
        origin.textContent = meta.origin;
        title.appendChild(origin);
      }

      group.querySelectorAll('.input-row').forEach((inputRow) => {
        const control = inputRow.querySelector('input,select');
        const caption = inputRow.querySelector('.input-label');
        if (!control || !caption || !control.id.startsWith('f_')) return;
        const key = control.id.slice(2);
        const rule = meta.derived && meta.derived[key];
        if (!rule) return;
        const chip = document.createElement('span');
        chip.className = 'tep-derived-chip';
        chip.textContent = `авто · ${rule}`;
        caption.appendChild(chip);
      });

      if (title && meta.changedField) {
        const note = document.createElement('div');
        note.className = 'tep-sync-note';
        note.textContent = meta.origin === 'из тизера'
          ? 'Исходное значение взято из тизера; связанные площади и количество пересчитаны правилами основной версии DevelopAid.'
          : 'После изменения одного связанного показателя остальные значения строки пересчитаны правилами основной версии DevelopAid.';
        title.insertAdjacentElement('afterend', note);
      }
    });
  }

  function projectPayload() {
    const api = window.DevelopAidV2;
    const project = ((api && api.state && api.state.result) || {}).project || {};
    return {
      inputs: form.draft.inputs,
      tep: form.draft.tep,
      rates: [],
      phasing: form.draft.phasing,
      project_name: project.name || '',
      region: project.region || '',
      cadastral_numbers: project.cadastral_numbers || [],
      source_label: project.source_label || 'Вводные из формы 2.0',
      scenario: project.scenario || 'base',
      sensitivity: false,
    };
  }

  async function recalculateCurrentProject() {
    const api = window.DevelopAidV2;
    if (!api || typeof api.calculateProject !== 'function') return;
    await api.calculateProject(projectPayload());
  }

  async function syncRow(rowKey, fieldKey, value, options = {}) {
    if (!rowKey || !fieldKey || typeof form === 'undefined' || !form || !form.draft) return;
    const seq = ++syncState.requestSeq;
    const status = document.getElementById('inputStatus');
    if (status) status.textContent = 'Пересчитываю связанные ТЭП…';
    try {
      const response = await fetch('/api/v2/tep-sync', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        cache: 'no-store',
        body: JSON.stringify({
          inputs: form.draft.inputs,
          tep: form.draft.tep,
          row_key: rowKey,
          field_key: fieldKey,
          value,
        }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || 'Связанные ТЭП не пересчитались');
      if (seq !== syncState.requestSeq) return;

      form.draft.inputs = data.inputs || form.draft.inputs;
      form.draft.tep = data.tep || form.draft.tep;
      syncState.derived[rowKey] = {
        changedField: data.changed_field || fieldKey,
        derived: data.derived || {},
        origin: options.origin || 'пересчитано',
      };
      if (typeof renderStep === 'function') renderStep();
      decorateTepEditor();

      if (options.recalculate !== false) await recalculateCurrentProject();
      if (status) {
        status.textContent = Object.keys(data.derived || {}).length
          ? 'Связанные ТЭП пересчитаны. Экономика проекта обновлена тем же движком.'
          : 'Значение принято. Экономика проекта обновлена.';
      }
    } catch (error) {
      if (status) status.textContent = String(error.message || error);
    }
  }

  function fieldFromControl(control) {
    return control && control.id && control.id.startsWith('f_') ? control.id.slice(2) : '';
  }

  document.addEventListener('change', (event) => {
    const control = event.target.closest('#inputBlock input, #inputBlock select');
    if (!control) return;
    const block = currentTepBlock();
    if (!block) return;
    const group = control.closest('.input-group');
    const rowKey = group && group.dataset.rowKey;
    const fieldKey = fieldFromControl(control);
    if (!rowKey || !fieldKey) return;
    const value = control.type === 'number' ? Number(control.value || 0) : control.value;
    // app.js updates form.draft in the target listener. Run after that handler.
    setTimeout(() => syncRow(rowKey, fieldKey, value, { origin: 'вручную' }), 0);
  });

  function maybeSyncTeaserImport() {
    const api = window.DevelopAidV2;
    if (!api || !api.state || !api.state.result || typeof form === 'undefined' || !form || !form.draft) return;
    const result = api.state.result;
    const project = result.project || {};
    const source = String(project.source_label || '');
    if (!/тизер/i.test(source)) return;
    const row = (form.draft.tep || {}).apartments || {};
    const gns = Number(row.gns || 0);
    if (!(gns > 0)) return;
    const signature = `${project.name || ''}|${source}|${gns}`;
    if (syncState.seenImports.has(signature)) return;
    syncState.seenImports.add(signature);
    syncRow('apartments', 'gns', gns, { origin: 'из тизера' });
  }

  injectStyles();
  renameTerritoryView();
  decorateTepEditor();
  maybeSyncTeaserImport();

  let observerScheduled = false;
  const observer = new MutationObserver(() => {
    // decorateTepEditor itself adds/removes chips. Watching those mutations while
    // decorating creates a self-triggering microtask loop that starves taps,
    // file-picker change events and uploads on iPhone. Collapse external DOM
    // changes to one animation frame and disconnect while we mutate our own UI.
    if (observerScheduled) return;
    observerScheduled = true;
    requestAnimationFrame(() => {
      observerScheduled = false;
      observer.disconnect();
      try {
        renameTerritoryView();
        decorateTepEditor();
        maybeSyncTeaserImport();
      } finally {
        observer.observe(document.body, { childList: true, subtree: true });
      }
    });
  });
  observer.observe(document.body, { childList: true, subtree: true });
})();
