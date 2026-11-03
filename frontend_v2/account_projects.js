(() => {
  'use strict';

  const WEB_SESSION_KEY = 'developaid_web_session';
  const SAVED_SLUG_PREFIX = 'saved:';
  const baseFetch = window.fetch.bind(window);
  const savedState = { session: '', projects: [], promise: null };

  function webSession() {
    try { return localStorage.getItem(WEB_SESSION_KEY) || ''; } catch (error) { return ''; }
  }

  function jsonResponse(source, payload) {
    const headers = new Headers(source.headers || {});
    headers.set('Content-Type', 'application/json; charset=utf-8');
    headers.set('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0');
    return new Response(JSON.stringify(payload), {
      status: source.status || 200,
      statusText: source.statusText || 'OK',
      headers,
    });
  }

  function errorResponse(error, status = 400) {
    return new Response(JSON.stringify({ detail: String(error && error.message || error) }), {
      status,
      headers: { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' },
    });
  }

  async function projectsCall(path, body = {}) {
    const session = webSession();
    if (!session) throw new Error('Войдите через Telegram, чтобы открыть сохранённые проекты.');
    const response = await baseFetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      cache: 'no-store',
      body: JSON.stringify({ session, ...body }),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || 'Хранилище проектов недоступно');
    return data;
  }

  function resetSavedCache() {
    savedState.session = '';
    savedState.projects = [];
    savedState.promise = null;
  }

  async function savedProjects(force = false) {
    const session = webSession();
    if (!session) {
      resetSavedCache();
      return [];
    }
    if (!force && savedState.session === session && savedState.promise) return savedState.promise;
    savedState.session = session;
    savedState.promise = projectsCall('/projects/list').then((data) => {
      savedState.projects = Array.isArray(data.projects) ? data.projects : [];
      return savedState.projects;
    }).catch((error) => {
      savedState.projects = [];
      savedState.promise = null;
      throw error;
    });
    return savedState.promise;
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
    return {
      ...left,
      ...right,
      products: { ...(left.products || {}), ...(right.products || {}) },
    };
  }

  async function savedProjectAsV2Response(projectId) {
    try {
      const [record, formResponse] = await Promise.all([
        projectsCall('/projects/open', { id: projectId }),
        baseFetch('/api/v2/form', { cache: 'no-store' }),
      ]);
      const formDescription = await formResponse.json().catch(() => ({}));
      if (!formResponse.ok) throw new Error(formDescription.detail || 'Не удалось получить умолчания движка');
      const defaults = formDescription.defaults || {};
      const stored = record.payload || {};
      const payload = {
        inputs: { ...(defaults.inputs || {}), ...(stored.inputs || {}) },
        tep: mergeTep(defaults.tep, stored.tep),
        rates: Array.isArray(stored.rates) ? stored.rates : [],
        phasing: mergePhasing(defaults.phasing, stored.phasing),
        project_name: record.name || 'Сохранённый проект',
        region: record.region || '',
        cadastral_numbers: Array.isArray(record.cadastral) ? record.cadastral : [],
        source_label: 'Сохранённый проект · личный кабинет',
        scenario: stored.scenario || 'base',
        sensitivity: true,
      };
      return await baseFetch('/api/v2/calculate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        cache: 'no-store',
        body: JSON.stringify(payload),
      });
    } catch (error) {
      return errorResponse(error);
    }
  }

  function neutralProject() {
    return {
      slug: 'new',
      name: 'Новый проект',
      region: '',
      subtitle: 'Умолчания движка · без демонстрационной предустановки',
      demo: false,
    };
  }

  function savedDescriptor(project) {
    const cadastral = Array.isArray(project.cadastral) && project.cadastral.length
      ? project.cadastral.join(', ')
      : 'Личный кабинет';
    return {
      slug: `${SAVED_SLUG_PREFIX}${project.id}`,
      name: project.name || 'Сохранённый проект',
      region: '',
      subtitle: cadastral,
      demo: false,
      saved: true,
    };
  }

  function neutralizeStaleDemoQuery(projects) {
    const url = new URL(location.href);
    const requested = url.searchParams.get('project');
    if (!requested || url.searchParams.get('demo') === '1') return;
    const chosen = projects.find((project) => project.slug === requested);
    if (!chosen || chosen.demo === false || chosen.saved) return;
    // Старый v2 сам записывал `?project=mishina` в адрес после первого запуска.
    // После появления нейтрального старта такой исторический query не должен
    // превращаться в вечный дефолт. Явная deep-link демо остаётся через demo=1.
    url.searchParams.delete('project');
    url.searchParams.delete('demo');
    history.replaceState(null, '', `${url.pathname}${url.search}${url.hash}`);
  }

  window.fetch = async function developAidV2AccountFetch(input, init) {
    const options = { ...(init || {}) };
    const rawUrl = typeof input === 'string' ? input : String((input && input.url) || '');
    let parsed;
    try { parsed = new URL(rawUrl, location.href); } catch (error) { parsed = new URL(location.href); }
    const path = parsed.pathname;
    const method = String(options.method || (input && input.method) || 'GET').toUpperCase();

    if (method === 'GET' && path === '/api/v2/projects') {
      const response = await baseFetch(input, options);
      if (!response.ok) return response;
      const catalog = await response.clone().json().catch(() => null);
      if (!Array.isArray(catalog)) return response;

      const projects = catalog.filter((project) => project && project.slug !== 'new' && !String(project.slug || '').startsWith(SAVED_SLUG_PREFIX));
      projects.unshift(neutralProject());
      try {
        const stored = await savedProjects();
        projects.splice(1, 0, ...stored.map(savedDescriptor));
      } catch (error) {
        // Авторизация может быть рабочей при временно недоступном хранилище.
        // Каталог демо/нейтрального проекта из-за этого не ломаем.
      }
      neutralizeStaleDemoQuery(projects);
      return jsonResponse(response, projects);
    }

    if (method === 'GET' && path.startsWith('/api/v2/projects/')) {
      const slug = decodeURIComponent(path.slice('/api/v2/projects/'.length));
      if (slug.startsWith(SAVED_SLUG_PREFIX)) {
        const id = slug.slice(SAVED_SLUG_PREFIX.length);
        if (!id) return errorResponse(new Error('Не указан сохранённый проект'));
        return savedProjectAsV2Response(id);
      }
    }

    return baseFetch(input, options);
  };

  function formatSavedAt(value) {
    if (!value) return '';
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? '' : date.toLocaleDateString('ru-RU');
  }

  function removeManualSavedEntries() {
    document.querySelectorAll('#projectMenu [data-v2-saved-entry]').forEach((node) => node.remove());
  }

  function syncSidebarSaved(projects) {
    const menu = document.getElementById('projectMenu');
    if (!menu || !window.DevelopAidV2 || typeof window.DevelopAidV2.loadProject !== 'function') return;
    removeManualSavedEntries();
    const existing = new Set(Array.from(menu.querySelectorAll('[data-slug]')).map((node) => node.dataset.slug));
    let anchor = menu.querySelector('[data-slug="new"]');
    projects.forEach((project) => {
      const slug = `${SAVED_SLUG_PREFIX}${project.id}`;
      if (existing.has(slug)) return;
      const button = document.createElement('button');
      button.type = 'button';
      button.dataset.slug = slug;
      button.dataset.v2SavedEntry = '1';
      const note = Array.isArray(project.cadastral) && project.cadastral.length
        ? project.cadastral.join(', ')
        : 'Сохранённый проект';
      button.innerHTML = `<strong>${escapeHtml(project.name || 'Сохранённый проект')}</strong><small>${escapeHtml(note)}</small>`;
      button.addEventListener('click', async () => {
        menu.hidden = true;
        try { await window.DevelopAidV2.loadProject(slug); } catch (error) { alert(String(error.message || error)); }
      });
      if (anchor && anchor.nextSibling) menu.insertBefore(button, anchor.nextSibling);
      else if (anchor) menu.appendChild(button);
      else menu.prepend(button);
      anchor = button;
    });
  }

  function escapeHtml(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  async function openSavedProject(id, status) {
    const api = window.DevelopAidV2;
    if (!api || typeof api.loadProject !== 'function') {
      if (status) status.textContent = 'Интерфейс проекта ещё загружается. Нажмите ещё раз через секунду.';
      return;
    }
    if (status) status.textContent = 'Открываю сохранённый проект и пересчитываю текущим движком…';
    await api.loadProject(`${SAVED_SLUG_PREFIX}${id}`);
    const popover = document.getElementById('v2AccountPopover');
    if (popover) popover.hidden = true;
  }

  async function enhanceAccount() {
    const button = document.getElementById('v2AccountButton');
    const popover = document.getElementById('v2AccountPopover');
    if (!button || !popover) return;
    if (!button.classList.contains('v2-authenticated') || !webSession()) {
      removeManualSavedEntries();
      resetSavedCache();
      return;
    }
    if (popover.querySelector('#v2SavedProjects')) return;

    const section = document.createElement('section');
    section.id = 'v2SavedProjects';
    section.className = 'v2-saved-projects';
    section.innerHTML = '<div class="v2-saved-head"><strong>Сохранённые проекты</strong><span>загрузка…</span></div>';
    const actions = popover.querySelector('.v2-account-actions');
    if (actions) actions.before(section); else popover.appendChild(section);

    try {
      const projects = await savedProjects(true);
      syncSidebarSaved(projects);
      const rows = projects.map((project) => {
        const date = formatSavedAt(project.saved_at);
        const cadastral = Array.isArray(project.cadastral) && project.cadastral.length
          ? project.cadastral.join(', ')
          : '';
        const meta = [cadastral, date].filter(Boolean).join(' · ') || 'Проект DevelopAid';
        return `<button type="button" class="v2-saved-project" data-v2-saved-id="${escapeHtml(project.id)}"><span><strong>${escapeHtml(project.name || 'Сохранённый проект')}</strong><small>${escapeHtml(meta)}</small></span><b>Открыть</b></button>`;
      }).join('');
      section.innerHTML = `
        <div class="v2-saved-head"><strong>Сохранённые проекты</strong><span>${projects.length}</span></div>
        <div class="v2-saved-list">${rows || '<p>Пока нет сохранённых проектов.</p>'}</div>
        <p id="v2SavedStatus" class="v2-saved-status"></p>`;
      section.querySelectorAll('[data-v2-saved-id]').forEach((projectButton) => {
        projectButton.addEventListener('click', async () => {
          const status = document.getElementById('v2SavedStatus');
          try {
            await openSavedProject(projectButton.dataset.v2SavedId, status);
          } catch (error) {
            if (status) status.textContent = String(error.message || error);
          }
        });
      });
    } catch (error) {
      section.innerHTML = `
        <div class="v2-saved-head"><strong>Сохранённые проекты</strong></div>
        <p class="v2-saved-status">${escapeHtml(error.message || error)}</p>`;
    }
  }

  function injectAccountStyles() {
    if (document.getElementById('v2AccountProjectsStyles')) return;
    const style = document.createElement('style');
    style.id = 'v2AccountProjectsStyles';
    style.textContent = `
      .v2-saved-projects{margin:12px 0;padding:12px 0;border-top:1px solid rgba(255,255,255,.1);border-bottom:1px solid rgba(255,255,255,.1)}
      .v2-saved-head{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:8px}.v2-saved-head span{color:#91a4ba;font-size:12px}
      .v2-saved-list{display:grid;gap:7px;max-height:260px;overflow:auto}.v2-saved-list>p{margin:4px 0!important;color:#91a4ba!important}
      .v2-saved-project{appearance:none;width:100%;display:flex;align-items:center;justify-content:space-between;gap:12px;text-align:left;border:1px solid rgba(255,255,255,.08);border-radius:10px;background:rgba(255,255,255,.05);color:#eef5ff;padding:9px 10px;cursor:pointer}
      .v2-saved-project span{min-width:0}.v2-saved-project strong{display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.v2-saved-project small{display:block;margin-top:3px;color:#91a4ba;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.v2-saved-project b{font-size:11px;color:#28d7a1}
      .v2-saved-status{margin:8px 0 0!important;color:#9fb0c4!important;font-size:12px!important}
    `;
    document.head.appendChild(style);
  }

  injectAccountStyles();
  const accountPopover = document.getElementById('v2AccountPopover');
  if (accountPopover) {
    const observer = new MutationObserver(() => { enhanceAccount(); });
    observer.observe(accountPopover, { childList: true, subtree: true });
  }
  const accountButton = document.getElementById('v2AccountButton');
  if (accountButton) {
    const observer = new MutationObserver(() => { enhanceAccount(); });
    observer.observe(accountButton, { attributes: true, attributeFilter: ['class'] });
  }
  queueMicrotask(() => enhanceAccount());
})();
