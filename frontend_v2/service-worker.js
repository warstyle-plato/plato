const CACHE_NAME = 'developaid-v2-shell-2026-08-03';
const APP_SHELL = [
  '/v2/',
  '/v2/assets/styles.css',
  '/v2/assets/app.js',
  '/v2/assets/pwa.css',
  '/v2/assets/pwa.js',
  '/v2/assets/icon.svg',
  '/v2/assets/icon-maskable.svg',
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
      .then((keys) => Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const request = event.request;
  const url = new URL(request.url);

  if (request.method !== 'GET' || url.origin !== self.location.origin) return;

  // Расчётные API всегда идут в сеть. Service worker не должен показывать
  // пользователю устаревший финансовый результат.
  if (url.pathname.startsWith('/api/')) {
    event.respondWith(fetch(request));
    return;
  }

  if (request.mode === 'navigate' && url.pathname.startsWith('/v2')) {
    event.respondWith(
      fetch(request)
        .then((response) => {
          const copy = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put('/v2/', copy));
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
