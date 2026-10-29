/* 제주 주유 PWA service worker: 앱 셸 캐시 + 웹 푸시 */
const CACHE = 'jeju-gas-shell-v1'
const SHELL = ['/', '/manifest.json', '/icon.svg']
const API_PREFIXES = ['/stations', '/alerts', '/push', '/meta']

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()))
})

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  )
})

self.addEventListener('fetch', (event) => {
  const req = event.request
  const url = new URL(req.url)
  if (req.method !== 'GET' || url.origin !== self.location.origin) return
  if (API_PREFIXES.some((p) => url.pathname.startsWith(p))) return // API 는 항상 네트워크
  event.respondWith(
    fetch(req)
      .then((res) => {
        if (res.ok) {
          const copy = res.clone()
          caches.open(CACHE).then((c) => c.put(req, copy))
        }
        return res
      })
      .catch(() => caches.match(req).then((hit) => hit || caches.match('/'))),
  )
})

self.addEventListener('push', (event) => {
  let data = {}
  try {
    data = event.data ? event.data.json() : {}
  } catch (e) {
    data = { body: event.data ? event.data.text() : '' }
  }
  const title = data.title || '제주 주유 알림'
  event.waitUntil(
    self.registration.showNotification(title, {
      body: data.body || '',
      icon: '/icon.svg',
      badge: '/icon.svg',
      tag: data.tag || undefined,
      data: { url: data.url || '/' },
    }),
  )
})

// 클릭하면 해당 주유소 지도(#/?station=..&lat=..&lng=..)로 이동
self.addEventListener('notificationclick', (event) => {
  event.notification.close()
  const target = new URL((event.notification.data && event.notification.data.url) || '/', self.location.origin).href
  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clients) => {
      for (const c of clients) {
        if (c.url.startsWith(self.location.origin) && 'focus' in c) {
          return c.focus().then(() => c.navigate(target))
        }
      }
      return self.clients.openWindow(target)
    }),
  )
})
