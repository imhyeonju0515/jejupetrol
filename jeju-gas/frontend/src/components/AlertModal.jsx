import { useState } from 'react'
import { api } from '../api'
import { enablePush } from '../hooks/usePush'
import AlertForm from './AlertForm'

/**
 * 주유소 "🔔 이 가격에 알림" 모달. 제출(버튼 클릭) 시점에만 알림 권한을 요청한다.
 */
export default function AlertModal({ station, context, onClose, onDone }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [done, setDone] = useState('')

  const initial = {
    label: context.center.label || '',
    lat: context.center.lat,
    lng: context.center.lng,
    radius_km: context.radiusKm,
    fuel_type: context.fuel,
    target_price: station.price,
    return_lat: context.dest?.lat ?? null,
    return_lng: context.dest?.lng ?? null,
    return_label: context.dest?.label || '',
  }

  const submit = async (body) => {
    setBusy(true)
    setError('')
    try {
      const push = await enablePush() // 사용자가 버튼을 누른 이 시점에만 권한 요청
      await api.createAlert(body)
      setDone(`알림이 등록되었습니다. ${push.status === 'ok' ? '' : push.message}`)
      onDone?.()
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="modal-back" role="dialog" aria-modal="true" aria-label="알림 등록" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h2>🔔 {station.name}</h2>
        <p className="small muted">현재 {station.price?.toLocaleString()}원/L · 이 가격 이하가 되면 알려드려요.</p>
        {done ? (
          <>
            <p className="ok">{done}</p>
            <div className="actions">
              <a className="btn" href="#/alerts">내 알림 보기</a>
              <button className="btn primary" onClick={onClose}>닫기</button>
            </div>
          </>
        ) : (
          <>
            {error && <p className="error" role="alert">{error}</p>}
            <AlertForm initial={initial} suggestedPrice={null} onSubmit={submit} onCancel={onClose} busy={busy} />
          </>
        )}
      </div>
    </div>
  )
}
