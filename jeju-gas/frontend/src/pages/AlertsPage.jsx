import { useCallback, useEffect, useState } from 'react'
import { api } from '../api'
import AlertCard from '../components/AlertCard'
import AlertForm from '../components/AlertForm'
import { DEFAULT_CENTER } from '../constants'
import { enablePush } from '../hooks/usePush'

export default function AlertsPage() {
  const [rules, setRules] = useState(null)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [form, setForm] = useState(null) // {mode:'new'|'edit', rule?, suggestion?}
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    try {
      setRules(await api.listAlerts())
      setError('')
    } catch (e) {
      setError(e.message)
    }
  }, [])
  useEffect(() => {
    load()
  }, [load])

  const openNew = async () => {
    setForm({ mode: 'new', suggestion: null })
    try {
      // 현재 최저가보다 -20원 목표가 자동 제안
      const d = await api.stations({ lat: DEFAULT_CENTER.lat, lng: DEFAULT_CENTER.lng, radius: 3000, fuel_type: 'B027' })
      const min = Math.min(...d.stations.map((s) => s.price).filter(Boolean))
      if (Number.isFinite(min)) setForm({ mode: 'new', suggestion: { price: min - 20, min } })
    } catch {
      /* 제안 없이 진행 */
    }
  }

  const save = async (body) => {
    setBusy(true)
    setNotice('')
    try {
      if (form.mode === 'edit') {
        await api.updateAlert(form.rule.id, body)
      } else {
        const push = await enablePush() // "🔔 알림 등록" 클릭 시점에만 권한 요청
        await api.createAlert(body)
        if (push.status !== 'ok') setNotice(push.message)
      }
      setForm(null)
      await load()
    } catch (e) {
      setNotice(e.message)
    } finally {
      setBusy(false)
    }
  }

  const toggle = async (r) => {
    try {
      await api.updateAlert(r.id, { is_active: !r.is_active })
      await load()
    } catch (e) {
      setNotice(e.message)
    }
  }
  const remove = async (r) => {
    try {
      await api.deleteAlert(r.id)
      await load()
    } catch (e) {
      setNotice(e.message)
    }
  }

  if (form) {
    const base = form.mode === 'edit' ? form.rule : { label: DEFAULT_CENTER.label, lat: DEFAULT_CENTER.lat, lng: DEFAULT_CENTER.lng }
    return (
      <div>
        <h2>{form.mode === 'edit' ? '알림 수정' : '새 알림'}</h2>
        {notice && <p className="error" role="alert">{notice}</p>}
        <AlertForm
          key={form.suggestion?.price ?? form.rule?.id ?? 'new'}
          initial={base}
          suggestedPrice={form.mode === 'new' ? form.suggestion?.price : null}
          currentMin={form.suggestion?.min}
          onSubmit={save}
          onCancel={() => setForm(null)}
          busy={busy}
          submitLabel={form.mode === 'edit' ? '저장' : '🔔 알림 등록'}
        />
      </div>
    )
  }

  return (
    <div>
      <div className="page-head">
        <h2>내 알림</h2>
        <button className="btn primary" onClick={openNew}>＋ 새 알림</button>
      </div>
      {notice && <p className="notice" role="status">{notice}</p>}
      {error && <p className="error" role="alert">{error}</p>}
      {rules === null && !error && <p className="muted">불러오는 중…</p>}
      {rules?.length === 0 && <p className="muted">등록된 알림이 없습니다. 지도 화면에서 주유소를 눌러 “🔔 이 가격에 알림”을 사용하거나 새 알림을 만들어 보세요.</p>}
      {rules?.map((r) => (
        <AlertCard key={r.id} rule={r} onToggle={toggle} onEdit={(rule) => setForm({ mode: 'edit', rule })} onDelete={remove} />
      ))}
    </div>
  )
}
