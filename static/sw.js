// Service worker: alert notifications and a friendly page when the house computer is unreachable.
const OFFLINE = '/static/offline.html';

self.addEventListener('install', event => {
  event.waitUntil(caches.open('casa-presente-v1').then(cache => cache.addAll([OFFLINE, '/static/icon-192.png'])).then(() => self.skipWaiting()));
});
self.addEventListener('activate', event => event.waitUntil(self.clients.claim()));

self.addEventListener('fetch', event => {
  // Only page navigations get the offline fallback; data and video always come from the network.
  if (event.request.mode === 'navigate') {
    event.respondWith(fetch(event.request).catch(() => caches.match(OFFLINE)));
  }
});

self.addEventListener('push', event => {
  const data = event.data ? event.data.json() : {title: 'Casa Presente', body: ''};
  event.waitUntil(self.registration.showNotification(data.title, {
    body: data.body, tag: data.tag, image: data.image || undefined, renotify: true, icon: '/static/icon-192.png', badge: '/static/icon-192.png',
    requireInteraction: Boolean(data.urgent), vibrate: data.urgent ? [300, 100, 300, 100, 300] : [120],
    data: {url: data.url || '/'},
  }));
});

self.addEventListener('notificationclick', event => {
  event.notification.close();
  const url = new URL(event.notification.data.url, self.location.origin).href;
  event.waitUntil(self.clients.matchAll({type: 'window', includeUncontrolled: true}).then(windows => {
    const open = windows.find(client => new URL(client.url).origin === self.location.origin);
    return open ? open.navigate(url).then(client => (client || open).focus()) : self.clients.openWindow(url);
  }));
});
