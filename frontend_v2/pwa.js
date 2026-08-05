(() => {
  'use strict';

  const STORAGE_PROJECT = 'developaid-v2:last-project';
  const STORAGE_INSTALL_DISMISSED = 'developaid-v2:install-dismissed';
  const STORAGE_UPDATE_DISMISSED = 'developaid-v2:update-dismissed';

  const isTelegram = Boolean(window.Telegram?.WebApp?.initData || /Telegram/i.test(navigator.userAgent));
  const isIos = /iphone|ipad|ipod/i.test(navigator.userAgent);
  const isStandalone = window.matchMedia('(display-mode: standalone)').matches || window.navigator.standalone === true;

  function currentProjectFromUrl(url = location.href) {
    return new URL(url, location.origin).searchParams.get('project') || '';
  }

  const requestedProject = currentProjectFromUrl();
  const savedProject = localStorage.getItem(STORAGE_PROJECT) || '';
  if (!requestedProject && savedProject) {
    const url = new URL(location.href);
    url.searchParams.set('project', savedProject);
    history.replaceState(history.state, '', url);
  }

  const originalReplaceState = history.replaceState.bind(history);
  history.replaceState = (state, unused, url) => {
    const project = url ? currentProjectFromUrl(url) : currentProjectFromUrl();
    if (project) localStorage.setItem(STORAGE_PROJECT, project);
    return originalReplaceState(state, unused, url);
  };

  function initials(user) {
    const parts = [user?.first_name, user?.last_name].filter(Boolean);
    if (!parts.length && user?.username) parts.push(user.username);
    return parts.map((part) => String(part).trim().charAt(0)).join('').slice(0, 2).toUpperCase() || 'DA';
  }

  function createLaunchMode() {
    const actions = document.querySelector('.topbar-actions');
    if (!actions || document.getElementById('launchMode')) return;

    const badge = document.createElement('span');
    badge.id = 'launchMode';
    badge.className = 'launch-mode';

    if (isTelegram) {
      badge.textContent = 'Telegram Mini App';
      badge.dataset.mode = 'telegram';
    } else if (isStandalone) {
      badge.textContent = 'Приложение установлено';
      badge.dataset.mode = 'standalone';
    } else {
      badge.textContent = 'Веб-приложение';
      badge.dataset.mode = 'browser';
    }
    actions.prepend(badge);
  }

  function applyTelegramProfile() {
    if (!isTelegram || !window.Telegram?.WebApp) return;
    const webApp = window.Telegram.WebApp;
    webApp.ready();
    webApp.expand();

    const user = webApp.initDataUnsafe?.user;
    const avatar = document.querySelector('.topbar-actions .avatar');
    if (avatar && user) {
      avatar.textContent = initials(user);
      const fullName = [user.first_name, user.last_name].filter(Boolean).join(' ');
      avatar.title = fullName || user.username || 'Telegram';
    }
  }

  function makeBar({ id, title, text, actionLabel, onAction, dismissKey }) {
    if (document.getElementById(id)) return null;
    const bar = document.createElement('div');
    bar.id = id;
    bar.className = 'pwa-bar';
    bar.innerHTML = `
      <span class="pwa-app-icon"><img src="/v2/assets/icon-192.png" alt=""></span>
      <span class="pwa-copy"><strong></strong><span></span></span>
      <button class="pwa-action" type="button"></button>
      <button class="pwa-dismiss" type="button" aria-label="Закрыть">×</button>`;
    bar.querySelector('.pwa-copy strong').textContent = title;
    bar.querySelector('.pwa-copy span').textContent = text;
    bar.querySelector('.pwa-action').textContent = actionLabel;
    bar.querySelector('.pwa-action').addEventListener('click', onAction);
    bar.querySelector('.pwa-dismiss').addEventListener('click', () => {
      bar.remove();
      if (dismissKey) localStorage.setItem(dismissKey, '1');
    });
    document.body.appendChild(bar);
    return bar;
  }

  let deferredPrompt = null;

  function showInstallBar() {
    if (isTelegram || isStandalone || localStorage.getItem(STORAGE_INSTALL_DISMISSED) === '1') return;

    const iosText = 'На iPhone добавьте DevelopAid на экран «Домой» — приложение будет открываться отдельно от Safari.';
    const standardText = 'Установите DevelopAid: отдельная иконка, полноэкранный запуск и быстрый доступ к проектам.';

    makeBar({
      id: 'installBar',
      title: 'DevelopAid — приложение',
      text: isIos ? iosText : standardText,
      actionLabel: isIos ? 'Как установить' : 'Установить',
      dismissKey: STORAGE_INSTALL_DISMISSED,
      onAction: async () => {
        if (deferredPrompt) {
          deferredPrompt.prompt();
          await deferredPrompt.userChoice;
          deferredPrompt = null;
          document.getElementById('installBar')?.remove();
          return;
        }
        const copy = document.querySelector('#installBar .pwa-copy span');
        const action = document.querySelector('#installBar .pwa-action');
        if (copy) copy.textContent = 'Нажмите «Поделиться» в Safari, затем выберите «На экран Домой».';
        if (action) {
          action.textContent = 'Понятно';
          action.onclick = () => document.getElementById('installBar')?.remove();
        }
      }
    });
  }

  function showUpdateBar(registration) {
    if (localStorage.getItem(STORAGE_UPDATE_DISMISSED) === '1') return;
    makeBar({
      id: 'updateBar',
      title: 'Доступна новая версия',
      text: 'Обновите интерфейс. Расчётные данные будут снова загружены из действующего движка.',
      actionLabel: 'Обновить',
      dismissKey: STORAGE_UPDATE_DISMISSED,
      onAction: () => {
        localStorage.removeItem(STORAGE_UPDATE_DISMISSED);
        registration.waiting?.postMessage({ type: 'SKIP_WAITING' });
        location.reload();
      }
    });
  }

  window.addEventListener('beforeinstallprompt', (event) => {
    event.preventDefault();
    deferredPrompt = event;
    showInstallBar();
  });

  window.addEventListener('appinstalled', () => {
    deferredPrompt = null;
    document.getElementById('installBar')?.remove();
  });

  if ('serviceWorker' in navigator) {
    window.addEventListener('load', async () => {
      try {
        const registration = await navigator.serviceWorker.register('/v2/service-worker.js', { scope: '/v2/' });
        if (registration.waiting && navigator.serviceWorker.controller) showUpdateBar(registration);
        registration.addEventListener('updatefound', () => {
          const worker = registration.installing;
          worker?.addEventListener('statechange', () => {
            if (worker.state === 'installed' && navigator.serviceWorker.controller) showUpdateBar(registration);
          });
        });
      } catch (error) {
        console.warn('DevelopAid PWA registration failed', error);
      }
    });
  }

  document.addEventListener('DOMContentLoaded', () => {
    createLaunchMode();
    applyTelegramProfile();
    if (isIos && !isStandalone && !isTelegram) window.setTimeout(showInstallBar, 800);
  });
})();
