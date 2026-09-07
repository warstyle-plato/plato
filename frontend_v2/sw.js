/* Service worker DevelopAid 2.0.

   Главное правило здесь — не то, что кешировать, а что кешировать нельзя.
   Расчёт не кешируется никогда: сохранённый ProjectResult на экране — это
   второй источник экономики, ровно тот, ради устранения которого /v2 переведён
   на движок. Поэтому всё под /api/ идёт только в сеть, и офлайн-ответа у него
   нет: лучше честная ошибка, чем вчерашние цифры, выглядящие как сегодняшние.

   Оболочка (страница, скрипт, стили, иконки) — сеть вперёд, кеш запасным
   вариантом. Свежая выкатка видна сразу же, а без сети приложение открывается.

   Имя кеша несёт версию приложения: она подставляется сервером из
   main_legacy.VERSION, и новый выпуск сбрасывает прежние кеши сам. Руками
   номер здесь не поднимают — его негде поднимать, кроме VERSION. */

const VERSION = '__DEVELOPAID_VERSION__';
const CACHE = `developaid-v2-${VERSION}`;

const SHELL = [
  '/v2/',
  '/v2/assets/app.js',
  '/v2/assets/styles.css',
  '/v2/assets/structured_inputs.js',
  '/v2/assets/structured_inputs.css',
  '/v2/manifest.webmanifest',
  '/v2/assets/icons/icon-192.png',
  '/v2/assets/icons/icon-512.png',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE)
      // Оболочка кладётся заранее, но отказ одного файла не должен valить
      // установку целиком: без части кеша приложение работает, без worker'а — нет.
      .then((cache) => Promise.allSettled(SHELL.map((url) => cache.add(url))))
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((names) => Promise.all(names
        .filter((name) => name.startsWith('developaid-v2-') && name !== CACHE)
        .map((name) => caches.delete(name))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener('fetch', (event) => {
  const request = event.request;
  if (request.method !== 'GET') return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  // Расчёт и справочники движка — только сеть. Кеша у них нет и быть не должно.
  if (url.pathname.startsWith('/api/')) return;

  event.respondWith(
    fetch(request)
      .then((response) => {
        if (response && response.ok) {
          const copy = response.clone();
          caches.open(CACHE).then((cache) => cache.put(request, copy)).catch(() => {});
        }
        return response;
      })
      .catch(() => caches.match(request).then(
        // Навигация без сети открывает сохранённую оболочку; она честно скажет,
        // что расчёт не получен, потому что за ним ходят в /api/.
        (cached) => cached || (request.mode === 'navigate'
          ? caches.match('/v2/')
          : undefined),
      )),
  );
});

self.addEventListener('message', (event) => {
  if (event.data === 'skip-waiting') self.skipWaiting();
});
