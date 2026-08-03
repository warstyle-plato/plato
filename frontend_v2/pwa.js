(() => {
  'use strict';

  const installBar = document.getElementById('installBar');
  const installButton = document.getElementById('installButton');
  const installText = document.getElementById('installText');
  const installDismiss = document.getElementById('installDismiss');
  const launchMode = document.getElementById('launchMode');

  let deferredPrompt = null;
  const isTelegram = Boolean(window.Telegram?.WebApp?.initData || /Telegram/i.test(navigator.userAgent));
  const isIos = /iphone|ipad|ipod/i.test(navigator.userAgent);
  const isStandalone = window.matchMedia('(display-mode: standalone)').matches || window.navigator.standalone === true;

  function setModeLabel() {
    if (!launchMode) return;
    if (isTelegram) {
      launchMode.textContent = 'Telegram Mini App';
      launchMode.dataset.mode = 'telegram';
    } else if (isStandalone) {
      launchMode.textContent = 'Приложение установлено';
      launchMode.dataset.mode = 'standalone';
    } else {
      launchMode.textContent = 'Веб-приложение';
      launchMode.dataset.mode = 'browser';
    }
  }

  function hideInstallBar(permanently = false) {
    if (!installBar) return;
    installBar.hidden = true;
    if (permanently) localStorage.setItem('developaid-install-dismissed', '1');
  }

  function showInstallBar(message, buttonLabel = 'Установить') {
    if (!installBar || isTelegram || isStandalone) return;
    if (localStorage.getItem('developaid-install-dismissed') === '1') return;
    installText.textContent = message;
    installButton.textContent = buttonLabel;
    installBar.hidden = false;
  }

  window.addEventListener('beforeinstallprompt', (event) => {
    event.preventDefault();
    deferredPrompt = event;
    showInstallBar('Установите DevelopAid: отдельная иконка, полноэкранный запуск и быстрый доступ к проектам.');
  });

  window.addEventListener('appinstalled', () => {
    deferredPrompt = null;
    hideInstallBar();
    setModeLabel();
  });

  installButton?.addEventListener('click', async () => {
    if (deferredPrompt) {
      deferredPrompt.prompt();
      await deferredPrompt.userChoice;
      deferredPrompt = null;
      hideInstallBar();
      return;
    }

    if (isIos) {
      installText.textContent = 'На iPhone: нажмите «Поделиться» в Safari → «На экран Домой».';
      installButton.textContent = 'Понятно';
      installButton.onclick = () => hideInstallBar(true);
    }
  });

  installDismiss?.addEventListener('click', () => hideInstallBar(true));

  if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => {
      navigator.serviceWorker.register('/v2/service-worker.js', { scope: '/v2/' }).catch((error) => {
        console.warn('DevelopAid PWA registration failed', error);
      });
    });
  }

  if (isTelegram && window.Telegram?.WebApp) {
    window.Telegram.WebApp.ready();
    window.Telegram.WebApp.expand();
  }

  setModeLabel();

  if (isIos && !isStandalone && !isTelegram && !localStorage.getItem('developaid-install-dismissed')) {
    window.setTimeout(() => showInstallBar('Добавьте DevelopAid на экран «Домой», чтобы открывать его как приложение.', 'Как установить'), 900);
  }
})();
