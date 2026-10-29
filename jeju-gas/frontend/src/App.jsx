import { useEffect, useState } from 'react'
import AlertsPage from './pages/AlertsPage'
import HomePage from './pages/HomePage'

/** 해시 라우터: #/ (지도), #/alerts (알림 관리). 푸시 클릭은 #/?station=ID&lat=..&lng=.. */
function parseHash() {
  const raw = window.location.hash.replace(/^#/, '') || '/'
  const [path, query = ''] = raw.split('?')
  const q = new URLSearchParams(query)
  return {
    path: path || '/',
    focus: q.get('station') ? { station: q.get('station'), lat: parseFloat(q.get('lat')), lng: parseFloat(q.get('lng')) } : null,
  }
}

export default function App() {
  const [route, setRoute] = useState(parseHash)
  useEffect(() => {
    const on = () => setRoute(parseHash())
    window.addEventListener('hashchange', on)
    return () => window.removeEventListener('hashchange', on)
  }, [])

  const onAlerts = route.path.startsWith('/alerts')
  return (
    <div className="app">
      <header className="topbar">
        <h1>⛽ 제주 주유 도우미</h1>
        <nav>
          <a href="#/" className={onAlerts ? '' : 'active'}>주유소</a>
          <a href="#/alerts" className={onAlerts ? 'active' : ''}>🔔 알림</a>
        </nav>
      </header>
      <main>{onAlerts ? <AlertsPage /> : <HomePage focus={route.focus} />}</main>
    </div>
  )
}
