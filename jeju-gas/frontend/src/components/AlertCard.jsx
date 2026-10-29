import { useState } from 'react'
import { api } from '../api'
import { ALERT_TYPE_LABEL, FUEL_NAME, won } from '../constants'

const STATUS = { sent: '발송', failed: '실패', test: '테스트', summary: '반납 요약' }

function condText(r) {
  return r.alert_types
    .map((t) => {
      if (t === 'target_price') return `${r.target_price?.toLocaleString()}원/L 이하`
      if (t === 'drop') return `최저가 ${r.drop_amount}원↓`
      return `총비용 ${won(r.total_cost_limit)} 이하`
    })
    .join(' · ')
}

export default function AlertCard({ rule, onToggle, onEdit, onDelete }) {
  const [msg, setMsg] = useState('')
  const [events, setEvents] = useState(null)

  const test = async () => {
    setMsg('테스트 알림 보내는 중…')
    try {
      await api.testAlert(rule.id)
      setMsg('테스트 알림을 보냈습니다.')
    } catch (e) {
      setMsg(e.message)
    }
  }
  const toggleEvents = async () => {
    if (events) return setEvents(null)
    try {
      setEvents(await api.alertEvents(rule.id))
    } catch (e) {
      setMsg(e.message)
    }
  }

  return (
    <article className={`card ${rule.is_active ? '' : 'off'}`}>
      <header>
        <div>
          <strong>{rule.label || '내 위치'} {rule.radius_km}km · {FUEL_NAME[rule.fuel_type]}</strong>
          <p className="small muted">{condText(rule)}</p>
        </div>
        <label className="switch" aria-label={rule.is_active ? '알림 끄기' : '알림 켜기'}>
          <input type="checkbox" checked={rule.is_active} onChange={() => onToggle(rule)} />
          <span />
        </label>
      </header>
      <p className="small">
        {rule.alert_types.map((t) => ALERT_TYPE_LABEL[t]).join(', ')}
        {rule.self_only && ' · 셀프만'}
        {rule.alttle_only && ' · 알뜰만'}
        {rule.exclude_far_detour && ` · 우회 ${rule.max_detour_minutes}분 초과 제외`}
      </p>
      {rule.rental_end && (
        <p className="small muted">
          대여 {rule.rental_start || '?'} ~ {rule.rental_end}{rule.return_label && ` · 반납 ${rule.return_label}`}
          {!rule.is_active && new Date(rule.expires_at + 'Z') < new Date() && ' · 기간 종료로 자동 비활성화됨'}
        </p>
      )}
      {rule.last_sent_at && <p className="small muted">마지막 발송 {new Date(rule.last_sent_at + 'Z').toLocaleString('ko-KR')}</p>}
      {msg && <p className="small" role="status">{msg}</p>}
      <div className="actions">
        <button className="btn" onClick={test}>테스트</button>
        <button className="btn" onClick={toggleEvents}>{events ? '이력 닫기' : '발송 이력'}</button>
        <button className="btn" onClick={() => onEdit(rule)}>수정</button>
        <button className="btn danger" onClick={() => window.confirm('이 알림을 삭제할까요?') && onDelete(rule)}>삭제</button>
      </div>
      {events && (
        <ul className="events small">
          {events.length === 0 && <li className="muted">아직 발송 이력이 없습니다.</li>}
          {events.map((e) => (
            <li key={e.id}>
              <span className={`tag ${e.status}`}>{STATUS[e.status] || e.status}</span>{' '}
              {new Date(e.created_at + 'Z').toLocaleString('ko-KR')} — {e.message}
              {e.error && <em className="error"> ({e.error})</em>}
            </li>
          ))}
        </ul>
      )}
    </article>
  )
}
