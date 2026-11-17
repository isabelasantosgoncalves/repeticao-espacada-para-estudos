/* Revisa: service worker.
   Permite instalar o app e mostra uma página simples quando não há internet.
   Estratégia "rede primeiro": sempre busca a versão mais nova no servidor e só
   usa o cache se a rede falhar, então uma atualização do site aparece na hora. */
const CACHE = 'revisa-v1';
const ESSENCIAIS = ['/static/css/estilo.css', '/static/js/app.js', '/static/favicon.svg', '/offline'];

self.addEventListener('install', (ev) => {
  ev.waitUntil(caches.open(CACHE).then((c) => c.addAll(ESSENCIAIS)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (ev) => {
  ev.waitUntil(
    caches.keys()
      .then((nomes) => Promise.all(nomes.filter((n) => n !== CACHE).map((n) => caches.delete(n))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (ev) => {
  const req = ev.request;
  if (req.method !== 'GET' || new URL(req.url).origin !== location.origin) return;

  // Arquivos estáticos: rede primeiro, guarda a cópia para usar sem internet.
  if (req.url.includes('/static/')) {
    ev.respondWith(
      fetch(req)
        .then((res) => { const copia = res.clone(); caches.open(CACHE).then((c) => c.put(req, copia)); return res; })
        .catch(() => caches.match(req))
    );
    return;
  }

  // Páginas: sempre da rede (dados de cada usuário não ficam em cache); sem internet, aviso.
  if (req.mode === 'navigate') {
    ev.respondWith(fetch(req).catch(() => caches.match('/offline')));
  }
});
