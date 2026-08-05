const CACHE_NAME = 'developaid-v2-shell-2026-08-06-1';
const APP_SHELL = [
  '/v2/',
  '/v2/assets/styles.css',
  '/v2/assets/app.js',
  '/v2/assets/pwa.css',
  '/v2/assets/pwa.js',
  '/v2/assets/icon.svg',
  '/v2/assets/icon-maskable.svg',
  '/v2/assets/icon-192.png',
  '/v2/assets/icon-512.png',
  '/v2/manifest.webmanifest'
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then((cache) => cache.addAll(APP_SHELL))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(
        keys.filter((key) => key.startsWith('developaid-v2-shell-') && key !== CACHE_NAME)
          .map((key) => caches.delete(key))
      ))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('message', (event) => {
  if (event.data?.type === 'SKIP_WAITING') self.skipWaiting();
});

self.addEventListener('fetch', (event) => {
  const request = event.request;
  const url = new URL(request.url);

  if (request.method !== 'GET' || url.origin !== self.location.origin) return;

  if (url.pathname.startsWith('/api/') ||
      url.pathname.startsWith('/report/') ||
      url.pathname.startsWith('/model/') ||
      url.pathname.startsWith('/telegram/')) {
    event.respondWith(fetch(request));
    return;
  }

  if (request.mode === 'navigate' && url.pathname.startsWith('/v2')) {
    event.respondWith(
      fetch(request)
        .then((response) => {
          if (response.ok) {
            const copy = response.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put('/v2/', copy));
          }
          return response;
        })
        .catch(() => caches.match('/v2/'))
    );
    return;
  }

  if (url.pathname.startsWith('/v2/')) {
    event.respondWith(
      caches.match(request).then((cached) => {
        const network = fetch(request)
          .then((response) => {
            if (response.ok) {
              const copy = response.clone();
              caches.open(CACHE_NAME).then((cache) => cache.put(request, copy));
            }
            return response;
          })
          .catch(() => cached);
        return cached || network;
      })
    );
  }
});
