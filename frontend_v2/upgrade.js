(() => {
  'use strict';

  const WEB_SESSION_KEY = 'developaid_web_session';
  const nativeFetch = window.fetch.bind(window);
  const photoState = { suggestions: [], busy: false, previewUrl: '' };

  function webSession() {
    try { return localStorage.getItem(WEB_SESSION_KEY) || ''; } catch (error) { return ''; }
  }

  function saveSession(value) {
    try {
      if (value) localStorage.setItem(WEB_SESSION_KEY, value);
      else localStorage.removeItem(WEB_SESSION_KEY);
    } catch (error) { /* private mode may deny storage */ }
  }

  // V2 uses the same identity as the main site. app.js knows nothing about
  // login, so add the existing browser session to Platon without duplicating
  // the agent endpoint or its auth rules.
  window.fetch = async function developAidV2Fetch(input, init) {
    const options = { ...(init || {}) };
    const url = typeof input === 'string' ? input : String((input && input.url) || '');
    let path = url;
    try { path = new URL(url, location.href).pathname; } catch (error) { /* relative is fine */ }
    if (path === '/agent/chat' && String(options.method || 'GET').toUpperCase() === 'POST' && options.body) {
      try {
        const body = JSON.parse(options.body);
        const session = webSession();
        if (session && !body.session) {
          body.session = session;
          options.body = JSON.stringify(body);
        }
      } catch (error) { /* not JSON: leave request untouched */ }
    }
    return nativeFetch(input, options);
  };

  function injectStyles() {
    if (document.getElementById('v2UpgradeStyles')) return;
    const style = document.createElement('style');
    style.id = 'v2UpgradeStyles';
    style.textContent = `
      .v2-account-popover{position:fixed;z-index:10020;top:72px;right:max(16px,env(safe-area-inset-right));width:min(380px,calc(100vw - 32px));background:#0d1928;border:1px solid rgba(255,255,255,.12);border-radius:18px;box-shadow:0 24px 70px rgba(0,0,0,.42);padding:18px;color:#eef5ff}
      .v2-account-popover[hidden]{display:none}
      .v2-account-popover h3{margin:0 0 7px;font-size:17px}.v2-account-popover p{margin:6px 0 14px;color:#9fb0c4;font-size:13px;line-height:1.45}
      .v2-account-actions{display:flex;gap:9px;flex-wrap:wrap}.v2-account-actions button,.v2-account-actions a,.v2-photo-button,.v2-photo-apply{appearance:none;border:0;border-radius:11px;padding:10px 13px;font:inherit;font-weight:700;cursor:pointer;text-decoration:none}
      .v2-account-primary,.v2-photo-button,.v2-photo-apply{background:#28d7a1;color:#041710}.v2-account-secondary{background:rgba(255,255,255,.08);color:#eef5ff}
      .v2-account-status{min-height:18px;margin-top:10px!important}.v2-account-qr{display:grid;grid-template-columns:112px 1fr;gap:12px;align-items:center;margin:14px 0;padding:10px;background:#fff;border-radius:13px;color:#132031}.v2-account-qr img{width:112px;height:112px}.v2-account-qr span{font-size:12px;line-height:1.4}
      .v2-photo-panel{margin:0 0 16px;padding:14px;border:1px solid rgba(40,215,161,.25);background:rgba(40,215,161,.055);border-radius:15px}.v2-photo-panel[hidden]{display:none}
      .v2-photo-title{display:flex;align-items:flex-start;justify-content:space-between;gap:12px}.v2-photo-title strong{font-size:15px}.v2-photo-title span{display:block;color:#9fb0c4;font-size:12px;margin-top:4px;line-height:1.4}
      .v2-photo-actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}.v2-photo-actions .secondary{background:rgba(255,255,255,.08);color:#eef5ff}
      .v2-photo-preview{display:flex;gap:12px;align-items:flex-start;margin-top:12px}.v2-photo-preview img{width:92px;height:92px;object-fit:cover;border-radius:10px;border:1px solid rgba(255,255,255,.12)}
      .v2-photo-status{color:#9fb0c4;font-size:12px;line-height:1.45;margin-top:10px}.v2-photo-review{margin-top:12px;display:grid;gap:7px;max-height:330px;overflow:auto}
      .v2-photo-suggestion{display:grid;grid-template-columns:22px 1fr auto;gap:8px;align-items:center;padding:9px 10px;border-radius:10px;background:rgba(255,255,255,.05);font-size:12px}.v2-photo-suggestion small{color:#91a4ba}.v2-photo-suggestion b{font-variant-numeric:tabular-nums}
      .v2-photo-raw{margin-top:10px;color:#9fb0c4;font-size:11px}.v2-photo-raw pre{white-space:pre-wrap;max-height:160px;overflow:auto;background:rgba(0,0,0,.18);padding:9px;border-radius:9px}
      .avatar.v2-authenticated{background:#28d7a1;color:#061812}
      @media(max-width:700px){.v2-account-popover{top:64px;right:10px;width:calc(100vw - 20px)}.v2-account-qr{grid-template-columns:96px 1fr}.v2-account-qr img{width:96px;height:96px}.v2-photo-actions{display:grid;grid-template-columns:1fr 1fr}.v2-photo-button{width:100%}.v2-photo-preview{display:block}.v2-photo-preview img{width:100%;height:auto;max-height:230px;margin-bottom:8px}}
    `;
    document.head.appendChild(style);
  }

  function esc(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function initials(name) {
    const parts = String(name || '').trim().split(/\s+/).filter(Boolean);
    if (!parts.length) return 'TG';
    return parts.slice(0, 2).map((part) => part[0]).join('').toUpperCase();
  }

  function accountElements() {
    let button = document.querySelector('.topbar-actions .avatar');
    if (!button) return {};
    button.id = 'v2AccountButton';
    button.setAttribute('aria-label', 'Личный кабинет');
    let popover = document.getElementById('v2AccountPopover');
    if (!popover) {
      popover = document.createElement('section');
      popover.id = 'v2AccountPopover';
      popover.className = 'v2-account-popover';
      popover.hidden = true;
      document.body.appendChild(popover);
      button.addEventListener('click', (event) => {
        event.stopPropagation();
        popover.hidden = !popover.hidden;
      });
      document.addEventListener('click', (event) => {
        if (!popover.hidden && !event.target.closest('#v2AccountPopover') && !event.target.closest('#v2AccountButton')) popover.hidden = true;
      });
    }
    return { button, popover };
  }

  function renderLoggedOut(message) {
    const { button, popover } = accountElements();
    if (!button || !popover) return;
    button.textContent = 'TG';
    button.classList.remove('v2-authenticated');
    popover.innerHTML = `
      <h3>Личный кабинет</h3>
      <p>Вход через тот же Telegram, что и на основном DevelopAid. Отдельного аккаунта для v2 нет.</p>
      <div class="v2-account-actions"><button id="v2TelegramLogin" class="v2-account-primary" type="button">Войти через Telegram</button></div>
      <p id="v2AccountStatus" class="v2-account-status">${esc(message || '')}</p>`;
    document.getElementById('v2TelegramLogin').addEventListener('click', startTelegramLogin);
  }

  function renderLoggedIn(data) {
    const { button, popover } = accountElements();
    if (!button || !popover) return;
    const profile = (data && data.profile) || {};
    const name = profile.name || profile.telegram_name || `Telegram #${data.chat_id || ''}`;
    const company = profile.company || '';
    const role = profile.role || '';
    button.textContent = initials(name);
    button.classList.add('v2-authenticated');
    popover.innerHTML = `
      <h3>${esc(name)}</h3>
      <p>${esc([company, role].filter(Boolean).join(' · ') || 'Вход подтверждён Telegram')}</p>
      <div class="v2-account-actions"><button id="v2Logout" class="v2-account-secondary" type="button">Выйти</button></div>
      <p class="v2-account-status">Эта сессия используется и для Платона, и для кабинета.</p>`;
    document.getElementById('v2Logout').addEventListener('click', () => {
      saveSession('');
      renderLoggedOut('Вы вышли на этом устройстве.');
    });
  }

  async function loadAccount() {
    const session = webSession();
    if (!session) return renderLoggedOut('');
    try {
      const response = await nativeFetch('/profile/get', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, cache: 'no-store',
        body: JSON.stringify({ session }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || 'Сессия истекла');
      renderLoggedIn(data);
    } catch (error) {
      saveSession('');
      renderLoggedOut('Сессия истекла — войдите снова.');
    }
  }

  async function startTelegramLogin() {
    const status = document.getElementById('v2AccountStatus');
    const say = (text) => { if (status) status.textContent = text; };
    let popup = null;
    try { popup = window.open('about:blank', '_blank'); } catch (error) { /* blocked */ }
    try {
      say('Запрашиваю код входа…');
      const response = await nativeFetch('/auth/telegram/start', { method: 'POST', cache: 'no-store' });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || 'Вход через Telegram недоступен');
      if (popup) popup.location.href = data.link;
      const { popover } = accountElements();
      if (!popover) return;
      popover.innerHTML = `
        <h3>Подтвердите вход в Telegram</h3>
        <p>После подтверждения вернитесь сюда — кабинет войдёт автоматически.</p>
        <div class="v2-account-actions"><a class="v2-account-primary" href="${esc(data.link)}" target="_blank" rel="noopener">Открыть бота</a></div>
        <div class="v2-account-qr"><img src="/auth/telegram/qr?code=${encodeURIComponent(data.code)}" alt="QR для входа"><span>Если Telegram открыт на телефоне, наведите камеру на QR. Код одноразовый.</span></div>
        <p id="v2AccountStatus" class="v2-account-status">Жду подтверждения…</p>`;
      const until = Date.now() + 2 * 60 * 1000;
      while (Date.now() < until) {
        await new Promise((resolve) => setTimeout(resolve, 2500));
        const claim = await nativeFetch('/auth/telegram/claim', {
          method: 'POST', headers: { 'Content-Type': 'application/json' }, cache: 'no-store',
          body: JSON.stringify({ code: data.code }),
        });
        const result = await claim.json().catch(() => ({}));
        if (!claim.ok) throw new Error(result.detail || 'Код входа не принят');
        if (result.ready && result.session) {
          saveSession(result.session);
          await loadAccount();
          return;
        }
      }
      throw new Error('Время ожидания вышло — нажмите «Войти через Telegram» ещё раз.');
    } catch (error) {
      if (popup && !popup.closed && popup.location.href === 'about:blank') popup.close();
      renderLoggedOut(String(error.message || error));
      const { popover } = accountElements();
      if (popover) popover.hidden = false;
    }
  }

  function ensurePhotoPanel() {
    const host = document.getElementById('inputBlock');
    const panelHost = host && host.closest('.input-panel');
    if (!host || !panelHost) return null;
    let panel = document.getElementById('v2PhotoPanel');
    if (!panel) {
      panel = document.createElement('div');
      panel.id = 'v2PhotoPanel';
      panel.className = 'v2-photo-panel';
      panel.innerHTML = `
        <div class="v2-photo-title"><div><strong>ТЭП с фотографии</strong><span>Снимите таблицу камерой iPhone. Сначала покажем распознанные цифры — ничего не подставляется без подтверждения.</span></div></div>
        <div class="v2-photo-actions">
          <button id="v2CameraButton" class="v2-photo-button" type="button">Сфотографировать ТЭПы</button>
          <button id="v2GalleryButton" class="v2-photo-button secondary" type="button">Выбрать из Фото</button>
        </div>
        <input id="v2CameraInput" type="file" accept="image/*" capture="environment" hidden>
        <input id="v2GalleryInput" type="file" accept="image/*" hidden>
        <div id="v2PhotoPreview" class="v2-photo-preview" hidden></div>
        <div id="v2PhotoStatus" class="v2-photo-status"></div>
        <div id="v2PhotoReview" class="v2-photo-review"></div>`;
      panelHost.insertBefore(panel, host);
      document.getElementById('v2CameraButton').addEventListener('click', () => document.getElementById('v2CameraInput').click());
      document.getElementById('v2GalleryButton').addEventListener('click', () => document.getElementById('v2GalleryInput').click());
      document.getElementById('v2CameraInput').addEventListener('change', onPhotoChosen);
      document.getElementById('v2GalleryInput').addEventListener('change', onPhotoChosen);
    }
    const title = String((document.getElementById('inputBlockTitle') || {}).textContent || '');
    panel.hidden = !/ТЭП/i.test(title);
    return panel;
  }

  function fileAsDataURL(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result || ''));
      reader.onerror = () => reject(reader.error || new Error('Файл не прочитан'));
      reader.readAsDataURL(file);
    });
  }

  function currentField(rowLabel, fieldLabel) {
    const groups = Array.from(document.querySelectorAll('#inputBlock .input-group'));
    const group = groups.find((node) => String((node.querySelector('h4') || {}).textContent || '').trim() === rowLabel);
    if (!group) return null;
    const rows = Array.from(group.querySelectorAll('.input-row'));
    const row = rows.find((node) => String((node.querySelector('.input-label') || {}).textContent || '').trim() === fieldLabel);
    return row ? row.querySelector('input') : null;
  }

  function formatNumber(value) {
    const number = Number(value);
    if (!Number.isFinite(number)) return String(value);
    return new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 3 }).format(number);
  }

  function renderPhotoReview(payload) {
    photoState.suggestions = Array.isArray(payload.suggestions) ? payload.suggestions : [];
    const review = document.getElementById('v2PhotoReview');
    const status = document.getElementById('v2PhotoStatus');
    if (!review || !status) return;
    if (!photoState.suggestions.length) {
      status.textContent = payload.warning || 'Цифры не сопоставились со строками ТЭП.';
      review.innerHTML = payload.text ? `<details class="v2-photo-raw"><summary>Показать распознанный текст</summary><pre>${esc(payload.text)}</pre></details>` : '';
      return;
    }
    status.textContent = `Распознано строк: ${payload.recognized_rows || 0} из ${payload.total_rows || 0}. Проверьте значения и отметьте, что подставить.`;
    review.innerHTML = photoState.suggestions.map((item, index) => {
      const input = currentField(item.row_label, item.field_label);
      const oldValue = input && input.value !== '' ? formatNumber(input.value) : 'пусто';
      const confidence = Math.round(Number(item.confidence || 0) * 100);
      return `<label class="v2-photo-suggestion">
        <input type="checkbox" data-photo-index="${index}" checked>
        <span><strong>${esc(item.row_label)}</strong> · ${esc(item.field_label)}<br><small>сейчас: ${esc(oldValue)} · уверенность ${confidence}%</small></span>
        <b>${esc(formatNumber(item.value))}</b>
      </label>`;
    }).join('') + `
      <button id="v2PhotoApply" class="v2-photo-apply" type="button">Применить отмеченные значения</button>
      <details class="v2-photo-raw"><summary>Показать распознанный текст</summary><pre>${esc(payload.text || '')}</pre></details>`;
    document.getElementById('v2PhotoApply').addEventListener('click', applyPhotoSuggestions);
  }

  function applyPhotoSuggestions() {
    const checks = Array.from(document.querySelectorAll('[data-photo-index]:checked'));
    let applied = 0;
    for (const check of checks) {
      const item = photoState.suggestions[Number(check.dataset.photoIndex)];
      if (!item) continue;
      const input = currentField(item.row_label, item.field_label);
      if (!input) continue;
      input.value = String(item.value);
      input.dispatchEvent(new Event('change', { bubbles: true }));
      applied += 1;
    }
    const status = document.getElementById('v2PhotoStatus');
    if (status) status.textContent = applied
      ? `Подставлено ${applied} значений. Проверьте ТЭП и нажмите «Посчитать движком».`
      : 'Ничего не подставлено. Откройте первый блок «ТЭП проекта» и повторите.';
  }

  async function onPhotoChosen(event) {
    const file = event.target.files && event.target.files[0];
    event.target.value = '';
    if (!file || photoState.busy) return;
    if (file.size > 12 * 1024 * 1024) {
      document.getElementById('v2PhotoStatus').textContent = 'Фото больше 12 МБ. Снимите таблицу ближе или выберите файл меньшего размера.';
      return;
    }
    photoState.busy = true;
    const status = document.getElementById('v2PhotoStatus');
    const preview = document.getElementById('v2PhotoPreview');
    const review = document.getElementById('v2PhotoReview');
    if (review) review.innerHTML = '';
    if (photoState.previewUrl) URL.revokeObjectURL(photoState.previewUrl);
    photoState.previewUrl = URL.createObjectURL(file);
    if (preview) {
      preview.hidden = false;
      preview.innerHTML = `<img src="${esc(photoState.previewUrl)}" alt="Снимок ТЭП"><div><strong>${esc(file.name || 'Фото с камеры')}</strong><br><small>${Math.round(file.size / 1024)} КБ</small></div>`;
    }
    try {
      status.textContent = 'Распознаю таблицу…';
      const dataUrl = await fileAsDataURL(file);
      const response = await nativeFetch('/api/v2/tep-photo', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, cache: 'no-store',
        body: JSON.stringify({ image_base64: dataUrl, content_type: file.type || '', filename: file.name || '' }),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.detail || 'Фото не распознано');
      renderPhotoReview(payload);
    } catch (error) {
      status.textContent = String(error.message || error);
    } finally {
      photoState.busy = false;
    }
  }

  function watchTepForm() {
    const block = document.getElementById('inputBlock');
    const title = document.getElementById('inputBlockTitle');
    if (!block || !title) return;
    const observer = new MutationObserver(() => ensurePhotoPanel());
    observer.observe(block, { childList: true, subtree: true });
    observer.observe(title, { childList: true, characterData: true, subtree: true });
    ensurePhotoPanel();
  }

  injectStyles();
  accountElements();
  loadAccount();
  watchTepForm();
})();
