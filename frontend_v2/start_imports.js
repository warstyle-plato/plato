(() => {
  'use strict';

  const WEB_SESSION_KEY = 'developaid_web_session';
  const MAX_TEMPLATE_BYTES = 5 * 1024 * 1024;
  const MAX_TEASER_BYTES = 20 * 1024 * 1024;
  let teaserExtraction = null;

  function esc(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function webSession() {
    try { return localStorage.getItem(WEB_SESSION_KEY) || ''; } catch (error) { return ''; }
  }

  function fileStem(name) {
    return String(name || 'Новый проект').replace(/\.[^.]+$/, '').trim() || 'Новый проект';
  }

  function setInitialView() {
    const params = new URLSearchParams(location.search);
    const explicitView = params.get('view');
    const requestedProject = params.get('project') || '';
    let target = explicitView || 'tepsearch';

    // A deliberately opened saved/demo project is a result, not a new-project start.
    // Old implicit demo URLs (for example ?project=mishina) are not deliberate:
    // the account bridge removes them and the entry screen remains Search.
    if (!explicitView && (requestedProject.startsWith('saved:') || params.get('demo') === '1')) {
      target = 'summary';
    }

    document.querySelectorAll('.view').forEach((section) => {
      section.classList.toggle('is-active', section.id === `view-${target}`);
    });
    document.querySelectorAll('.nav-item, .mobile-tabs button').forEach((button) => {
      button.classList.toggle('is-active', button.dataset.view === target);
    });
  }

  function injectStyles() {
    if (document.getElementById('v2StartImportStyles')) return;
    const style = document.createElement('style');
    style.id = 'v2StartImportStyles';
    style.textContent = `
      .v2-start-lead{margin:0 0 14px;padding:16px 18px;border:1px solid rgba(40,215,161,.2);border-radius:16px;background:linear-gradient(135deg,rgba(40,215,161,.08),rgba(47,140,255,.04))}
      .v2-start-lead strong{display:block;font-size:16px;margin-bottom:4px}.v2-start-lead span{color:#9fb0c4;font-size:13px;line-height:1.45}
      .v2-start-imports{margin-top:14px}.v2-start-imports h3{margin:0 0 5px;font-size:16px}.v2-start-imports>p{margin:0 0 13px;color:#9fb0c4;font-size:13px;line-height:1.45}
      .v2-import-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px}.v2-import-card{border:1px solid rgba(255,255,255,.09);border-radius:13px;padding:13px;background:rgba(255,255,255,.035)}
      .v2-import-card strong{display:block;margin-bottom:5px}.v2-import-card p{margin:0 0 10px;color:#9fb0c4;font-size:12px;line-height:1.45}.v2-import-actions{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
      .v2-import-status{margin-top:12px;color:#9fb0c4;font-size:12px;line-height:1.45}.v2-import-status.is-error{color:#ff9aaa}.v2-import-status.is-ok{color:#68e4ba}
      .v2-teaser-review{margin-top:12px}.v2-teaser-review[hidden]{display:none}.v2-teaser-table{width:100%;border-collapse:collapse;font-size:12px}.v2-teaser-table th,.v2-teaser-table td{padding:8px 6px;border-bottom:1px solid rgba(255,255,255,.08);vertical-align:top;text-align:left}.v2-teaser-table small{display:block;margin-top:3px;color:#91a4ba;line-height:1.35}.v2-teaser-questions{margin:10px 0;color:#9fb0c4;font-size:12px;line-height:1.45}
      @media(max-width:700px){.v2-import-grid{grid-template-columns:1fr}.v2-import-actions .search-button,.v2-import-actions .text-button{width:100%;text-align:center}.v2-teaser-table th:nth-child(4),.v2-teaser-table td:nth-child(4){display:none}}
    `;
    document.head.appendChild(style);
  }

  function injectStartImports() {
    const section = document.getElementById('view-tepsearch');
    const searchPanel = section && section.querySelector('.tep-search-panel');
    if (!section || !searchPanel || document.getElementById('v2StartImports')) return;

    const lead = document.createElement('div');
    lead.className = 'v2-start-lead';
    lead.innerHTML = '<strong>Начните с участка</strong><span>Поиск по кадастровому номеру или адресу — основной вход в новый проект. Если ТЭП уже есть, загрузите наш Excel-шаблон. Если есть тизер — DevelopAid сначала покажет, что прочитал, и задаст вопросы и предложит подтвердить карточку.</span>';
    searchPanel.before(lead);

    const panel = document.createElement('article');
    panel.id = 'v2StartImports';
    panel.className = 'panel v2-start-imports';
    panel.innerHTML = `
      <h3>Или загрузите исходные материалы</h3>
      <p>Оба пути используют уже существующий импорт DevelopAid и тот же расчётный движок — отдельного парсера или второй экономики здесь нет.</p>
      <div class="v2-import-grid">
        <div class="v2-import-card">
          <strong>ТЭП по шаблону DevelopAid</strong>
          <p>Заполненный Excel с листом «ТЭП DevelopAid». После загрузки ТЭП переносятся во вводные и пересчитываются текущим движком.</p>
          <div class="v2-import-actions">
            <button id="v2TemplateUploadButton" class="search-button" type="button">Загрузить ТЭП (.xlsx)</button>
            <a class="text-button" href="/templates/tep">Скачать пустой шаблон</a>
          </div>
          <input id="v2TemplateUpload" type="file" accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" hidden>
        </div>
        <div class="v2-import-card">
          <strong>Тизер проекта</strong>
          <p>PDF, фотография или публичная ссылка проходят общий разбор документа. Перед применением покажем значения и цитаты из файла.</p>
          <div class="v2-import-actions">
            <button id="v2TeaserUploadButton" class="search-button" type="button">Загрузить PDF или фото</button>
          </div>
          <p><label>Ссылка на документ или страницу <input id="v2TeaserUrl" type="url" placeholder="https://…"></label> <button id="v2TeaserUrlButton" class="text-button" type="button">Прочитать ссылку</button></p><input id="v2TeaserUpload" type="file" accept=".pdf,.png,.jpg,.jpeg,application/pdf,image/png,image/jpeg" hidden>
        </div>
      </div>
      <div id="v2ImportStatus" class="v2-import-status"></div>
      <div id="v2TeaserReview" class="v2-teaser-review" hidden></div>`;
    searchPanel.after(panel);

    document.getElementById('v2TemplateUploadButton').addEventListener('click', () => document.getElementById('v2TemplateUpload').click());
    document.getElementById('v2TeaserUploadButton').addEventListener('click', () => document.getElementById('v2TeaserUpload').click());
    document.getElementById('v2TemplateUpload').addEventListener('change', onTemplateFile);
    document.getElementById('v2TeaserUpload').addEventListener('change', onTeaserFile);
    document.getElementById('v2TeaserUrlButton').onclick = () => readTeaser({source_url: document.getElementById('v2TeaserUrl').value.trim()});
  }

  function status(text, tone = '') {
    const node = document.getElementById('v2ImportStatus');
    if (!node) return;
    node.className = `v2-import-status${tone ? ` is-${tone}` : ''}`;
    node.textContent = text || '';
  }

  function mergeTep(defaults, stored) {
    const out = {};
    const left = defaults && typeof defaults === 'object' ? defaults : {};
    const right = stored && typeof stored === 'object' ? stored : {};
    new Set([...Object.keys(left), ...Object.keys(right)]).forEach((key) => {
      out[key] = { ...(left[key] || {}), ...(right[key] || {}) };
    });
    return out;
  }

  function mergePhasing(defaults, stored) {
    const left = defaults && typeof defaults === 'object' ? defaults : {};
    const right = stored && typeof stored === 'object' ? stored : {};
    return { ...left, ...right, products: { ...(left.products || {}), ...(right.products || {}) } };
  }

  async function defaults() {
    const response = await fetch('/api/v2/form', { cache: 'no-store' });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || 'Не удалось получить умолчания движка');
    return data.defaults || {};
  }

  function currentDraft(fallback) {
    try {
      if (typeof form !== 'undefined' && form && form.draft) {
        return {
          inputs: { ...(form.draft.inputs || {}) },
          tep: mergeTep(fallback.tep, form.draft.tep),
          phasing: mergePhasing(fallback.phasing, form.draft.phasing),
        };
      }
    } catch (error) { /* app.js may still be starting */ }
    return {
      inputs: { ...(fallback.inputs || {}) },
      tep: mergeTep(fallback.tep, {}),
      phasing: mergePhasing(fallback.phasing, {}),
    };
  }

  function adoptDraft(draft, message) {
    try {
      if (typeof form !== 'undefined' && form) {
        form.draft = draft;
        if (form.blocks && form.blocks.length && typeof renderStep === 'function') renderStep();
      }
      const inputStatus = document.getElementById('inputStatus');
      if (inputStatus && message) inputStatus.textContent = message;
    } catch (error) { /* result is still valid even if form is not mounted yet */ }
  }

  async function calculateImported(draft, meta) {
    const api = window.DevelopAidV2;
    if (!api || typeof api.calculateProject !== 'function') throw new Error('Интерфейс проекта ещё загружается. Повторите через секунду.');
    adoptDraft(draft, meta.message || 'Импорт применён. Проверьте вводные и пересчитайте при необходимости.');
    await api.calculateProject({
      inputs: draft.inputs,
      tep: draft.tep,
      rates: [],
      phasing: draft.phasing,
      project_name: meta.projectName || 'Новый проект',
      region: meta.region || '',
      cadastral_numbers: meta.cadastralNumbers || [],
      source_label: meta.sourceLabel || 'Импорт в DevelopAid 2.0',
      scenario: 'base',
      sensitivity: true,
    });
    if (typeof setView === 'function') setView('inputs');
  }

  async function onTemplateFile(event) {
    const input = event.target;
    const file = input.files && input.files[0];
    input.value = '';
    if (!file) return;
    if (file.size > MAX_TEMPLATE_BYTES) return status('Шаблон больше 5 МБ — сервер такой файл не принимает.', 'error');
    status('Читаю шаблон DevelopAid…');
    try {
      const bytes = await file.arrayBuffer();
      const response = await fetch(`/import/manual-tep?filename=${encodeURIComponent(file.name)}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' },
        cache: 'no-store',
        body: bytes,
      });
      const parsed = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(parsed.detail || 'Шаблон ТЭП не распознан');
      if (!parsed.tep) throw new Error('В шаблоне не нашлись ТЭП проекта');

      const base = await defaults();
      const inputs = { ...(base.inputs || {}), ...(parsed.inputs || {}) };
      if (Number(parsed.site_area_ha || 0) > 0) inputs.site_area_ha = Number(parsed.site_area_ha);
      const draft = {
        inputs,
        tep: mergeTep(base.tep, parsed.tep),
        phasing: mergePhasing(base.phasing, parsed.phasing),
      };
      await calculateImported(draft, {
        projectName: parsed.project_name || fileStem(file.name),
        region: parsed.region || '',
        cadastralNumbers: Array.isArray(parsed.cadastral_numbers) ? parsed.cadastral_numbers : [],
        sourceLabel: 'ТЭП из шаблона DevelopAid',
        message: 'ТЭП загружены из шаблона DevelopAid. Экономические вводные — умолчания движка; проверьте их перед финальным расчётом.',
      });
      status('Шаблон применён. Открыты «Вводные»: проверьте экономику проекта.', 'ok');
    } catch (error) {
      status(String(error.message || error), 'error');
    }
  }

  function arrayBufferToBase64(buffer) {
    const bytes = new Uint8Array(buffer);
    let binary = '';
    for (let index = 0; index < bytes.length; index += 8192) {
      binary += String.fromCharCode.apply(null, bytes.subarray(index, index + 8192));
    }
    return btoa(binary);
  }

  function cadastralFromExtraction(extraction) {
    const values = (extraction && extraction.fields) || [];
    const found = new Set();
    values.forEach((field) => {
      if (field.key !== 'cadastral_numbers') return;
      const matches = String(field.value || '').match(/\d{2}:\d{2}:\d{5,8}:\d+/g) || [];
      matches.forEach((number) => found.add(number));
    });
    return [...found];
  }

  let teaserBusy = false;

  function cardRows(rows, value) {
    return '<table class="v2-teaser-table"><tbody>' + rows.map(row =>
      '<tr><td>' + esc(row.label) + '</td><td>' + value(row) + '</td></tr>').join('') + '</tbody></table>';
  }

  function renderTeaserReview(data) {
    teaserExtraction = data;
    const host = document.getElementById('v2TeaserReview');
    if (!host) return;
    host.hidden = false;
    const card = data.card;
    if (!card) {
      host.textContent = data.reason || (data.document || {}).reason || 'Разбор не вернул карточку. Повторите загрузку.';
      return;
    }
    const q = card.questions || {};
    host.innerHTML = '<strong>' + esc(card.filename || 'Тизер') + '</strong>'
      + (card.document_reason ? '<p>' + esc(card.document_reason) + '</p>' : '')
      + '<h4>Что найдено в документе</h4>'
      + cardRows(card.found || [], r => '<b>' + esc(Array.isArray(r.value) ? r.value.join(', ') : r.value) + '</b> '
        + esc(r.unit) + '<small>' + esc(r.page_text) + ' · ' + esc(r.status) + '<br>«' + esc(r.quote) + '»</small>')
      + '<h4>Что уйдёт в расчёт</h4>'
      + cardRows(card.to_engine || [], r => '<b>' + esc(r.shown) + '</b><small>' + esc(r.origin) + '</small>')
      + '<h4>Чего не хватает и что возьмётся вместо этого</h4>'
      + cardRows(card.missing || [], r => esc(r.shown) + '<small>' + esc(r.origin) + '</small>')
      + (card.refused || []).map(r => '<p>Не взято: ' + esc(r.label || r.key) + ' — ' + esc(r.reason) + '</p>').join('')
      + (card.notes || []).map(note => '<p>' + esc(note) + '</p>').join('')
      + '<div id="v2TeaserQuestion"></div>'
      + (card.ready ? '<button id="v2TeaserApply" class="search-button" type="button">Всё верно, считать</button>'
        : '<button id="v2TeaserQuestions" class="search-button" type="button">Перейти к вопросам (' + esc(q.total - q.index) + ')</button>');
    const apply = document.getElementById('v2TeaserApply');
    if (apply) apply.onclick = applyTeaserSelection;
    const questions = document.getElementById('v2TeaserQuestions');
    if (questions) questions.onclick = () => { questions.hidden = true; renderTeaserQuestion(card); };
  }

  function renderTeaserQuestion(card) {
    const question = (card.questions || {}).card;
    const host = document.getElementById('v2TeaserQuestion');
    if (!question || !host) return;
    host.innerHTML = '<p><strong>' + esc(question.question) + '</strong></p>'
      + (question.options || []).map((o, index) => '<button class="text-button" data-teaser-choice="' + index + '">' + esc(o.label) + '</button>').join(' ')
      + '<p><label>Своё значение ' + esc(question.unit || '') + ' <input id="v2TeaserAnswer" type="text"></label>'
      + '<button id="v2TeaserAnswerButton" class="text-button">Ответить</button></p>'
      + '<button id="v2TeaserSkip" class="text-button">Пропустить — оставить указанное в карточке</button>';
    host.querySelectorAll('[data-teaser-choice]').forEach(button => {
      button.onclick = () => answerTeaser(card, 'answer', Number(button.dataset.teaserChoice));
    });
    document.getElementById('v2TeaserAnswerButton').onclick = () => answerTeaser(card, 'answer', -1);
    document.getElementById('v2TeaserSkip').onclick = () => answerTeaser(card, 'skip', -1);
  }

  async function answerTeaser(card, action, choice, mode = '') {
    if (teaserBusy) return;
    teaserBusy = true;
    try {
      const draft = currentDraft(await defaults());
      const value = (document.getElementById('v2TeaserAnswer') || {}).value || '';
      const response = await fetch('/agent/document/answer', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({intake_id: card.id, index: card.questions.index, action, choice, value, mode,
          inputs: draft.inputs, tep: draft.tep, session: webSession()}),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || 'Ответ не сохранился.');
      if (data.confirm) {
        const host = document.getElementById('v2TeaserQuestion');
        host.innerHTML = '<p>' + esc(data.confirm.label) + ': уже стоит ' + esc(data.confirm.current)
          + ', из ответа ' + esc(data.confirm.adding) + ' ' + esc(data.confirm.unit) + '. Прибавить или заменить?</p>'
          + '<button data-mode="add" class="text-button">Прибавить</button> '
          + '<button data-mode="replace" class="text-button">Заменить</button>'
          + '<input id="v2TeaserAnswer" type="hidden" value="' + esc(value) + '">';
        host.querySelectorAll('[data-mode]').forEach(b => {
          b.onclick = () => answerTeaser(card, action, choice, b.dataset.mode);
        });
        return;
      }
      renderTeaserReview({...teaserExtraction, card: data.card});
      if (!data.card.ready) {
        const next = document.getElementById('v2TeaserQuestions');
        if (next) next.hidden = true;
        renderTeaserQuestion(data.card);
      }
    } catch (error) { status(String(error.message || error), 'error'); }
    finally { teaserBusy = false; }
  }

  async function readTeaser(payload) {
    if (teaserBusy) return;
    teaserBusy = true;
    status('Читаю документ. Модель пока не меняется…');
    try {
      const draft = currentDraft(await defaults());
      const data = await window.PlatoDocumentClient.read({...payload,
        inputs: draft.inputs, tep: draft.tep, session: webSession()});
      renderTeaserReview(data);
      status(data.card ? 'Проверьте карточку и ответы перед расчётом.' : 'Документ не применён.', data.card ? 'ok' : 'error');
    } catch (error) { status(String(error.message || error), 'error'); }
    finally { teaserBusy = false; }
  }

  async function onTeaserFile(event) {
    const input = event.target;
    const file = input.files && input.files[0];
    if (!file) return;
    if (file.size > MAX_TEASER_BYTES) return status('Файл больше 20 МБ. Пришлите нужные страницы отдельно.', 'error');
    try {
      const buffer = await file.arrayBuffer(); // Read before clearing the iOS file picker.
      input.value = '';
      await readTeaser({filename: file.name, content_b64: arrayBufferToBase64(buffer)});
    } catch (error) { status(String(error.message || error), 'error'); }
  }

  async function applyTeaserSelection() {
    if (teaserBusy || !teaserExtraction || !teaserExtraction.card || !teaserExtraction.card.ready) return;
    teaserBusy = true;
    status('Сверяю подтверждённую карточку…');
    try {
      const before = currentDraft(await defaults());
      const card = teaserExtraction.card;
      const response = await fetch('/agent/document/apply', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({intake_id: card.id, card_key: card.card_key,
          inputs: before.inputs, tep: before.tep, session: webSession()}),
      });
      const applied = await response.json();
      if (!response.ok) throw new Error(applied.detail || 'Карточка не применена.');
      if (applied.stale) {
        renderTeaserReview({...teaserExtraction, card: applied.card});
        status('Вводные изменились. Проверьте обновлённую карточку и подтвердите её ещё раз.');
        return;
      }
      await calculateImported({inputs: applied.inputs, tep: applied.tep, phasing: before.phasing}, {
        projectName: fileStem(card.filename), cadastralNumbers: applied.cadastral_numbers,
        sourceLabel: 'Тизер · подтверждённая карточка',
        message: 'Применена подтверждённая карточка документа. Происхождение значений сохранено.',
      });
      status('Карточка применена, проект пересчитан.', 'ok');
    } catch (error) { status(String(error.message || error), 'error'); }
    finally { teaserBusy = false; }
  }

  setInitialView();
  injectStyles();
  injectStartImports();
})();
