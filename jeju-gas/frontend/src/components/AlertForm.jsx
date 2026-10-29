import { useState } from 'react'
import { ALERT_TYPE_LABEL, FUELS, RADII, ZONES } from '../constants'

const todayStr = () => new Date().toISOString().slice(0, 10)

// 서버가 돌려준 null 을 입력창용 빈 문자열로 (좌표 필드는 null 유지)
const KEEP_NULL = ['return_lat', 'return_lng']
const withoutNulls = (o) =>
  Object.fromEntries(Object.entries(o).map(([k, v]) => [k, v === null && !KEEP_NULL.includes(k) ? '' : v]))

/**
 * 알림 등록/수정 폼. initial 로 현재 조건을 미리 채우고,
 * suggestedPrice(현재 최저가 - 20원)를 목표가 기본값으로 제안한다.
 */
export default function AlertForm({ initial, suggestedPrice, currentMin, onSubmit, onCancel, busy, submitLabel = '🔔 알림 등록' }) {
  const [f, setF] = useState(() => withoutNulls({
    label: '',
    radius_km: 3,
    fuel_type: 'B027',
    alert_types: ['target_price'],
    target_price: suggestedPrice || '',
    drop_amount: 20,
    total_cost_limit: '',
    self_only: false,
    alttle_only: false,
    rental_start: '',
    rental_end: '',
    return_lat: null,
    return_lng: null,
    return_label: '',
    exclude_far_detour: false,
    max_detour_minutes: 10,
    liters: 30,
    ...initial,
  }))
  const [error, setError] = useState('')
  const set = (k, v) => setF((p) => ({ ...p, [k]: v }))
  const toggleType = (t) =>
    set('alert_types', f.alert_types.includes(t) ? f.alert_types.filter((x) => x !== t) : [...f.alert_types, t])

  const submit = (e) => {
    e.preventDefault()
    setError('')
    if (!f.alert_types.length) return setError('알림 유형을 하나 이상 선택해 주세요.')
    if (f.alert_types.includes('target_price') && !(+f.target_price > 0)) return setError('목표가(원/L)를 입력해 주세요.')
    if (f.alert_types.includes('drop') && !(+f.drop_amount > 0)) return setError('하락폭(원)을 입력해 주세요.')
    if (f.alert_types.includes('total_cost') && !(+f.total_cost_limit > 0)) return setError('총비용 기준(원)을 입력해 주세요.')
    if (f.rental_start && f.rental_end && f.rental_end < f.rental_start) return setError('대여 종료일이 시작일보다 빠릅니다.')
    if (f.exclude_far_detour && f.return_lat == null) return setError('우회 시간 제외 옵션은 반납 장소를 먼저 선택해야 합니다.')
    const num = (v) => (v === '' || v == null ? null : +v)
    onSubmit({
      label: f.label,
      lat: f.lat,
      lng: f.lng,
      radius_km: +f.radius_km,
      fuel_type: f.fuel_type,
      alert_types: f.alert_types,
      target_price: f.alert_types.includes('target_price') ? num(f.target_price) : null,
      drop_amount: f.alert_types.includes('drop') ? num(f.drop_amount) : null,
      total_cost_limit: f.alert_types.includes('total_cost') ? num(f.total_cost_limit) : null,
      self_only: f.self_only,
      alttle_only: f.alttle_only,
      rental_start: f.rental_start || null,
      rental_end: f.rental_end || null,
      return_lat: f.return_lat,
      return_lng: f.return_lng,
      return_label: f.return_label,
      exclude_far_detour: f.exclude_far_detour,
      max_detour_minutes: +f.max_detour_minutes || 10,
      liters: +f.liters || 30,
    })
  }

  const pickZone = (key, kind) => {
    const z = ZONES.find((x) => x.key === key)
    if (kind === 'center') setF((p) => ({ ...p, lat: z.lat, lng: z.lng, label: z.label }))
    else setF((p) => (z ? { ...p, return_lat: z.lat, return_lng: z.lng, return_label: z.label } : { ...p, return_lat: null, return_lng: null, return_label: '', exclude_far_detour: false }))
  }

  return (
    <form className="alert-form" onSubmit={submit}>
      <fieldset>
        <legend>기준 위치</legend>
        <p className="small">
          📍 {f.label || '선택한 위치'} <span className="muted">({f.lat?.toFixed(3)}, {f.lng?.toFixed(3)})</span>
        </p>
        <div className="chips">
          {ZONES.map((z) => (
            <button key={z.key} type="button" className="chip" onClick={() => pickZone(z.key, 'center')}>
              {z.label}
            </button>
          ))}
        </div>
      </fieldset>

      <div className="row">
        <label>
          유종
          <select value={f.fuel_type} onChange={(e) => set('fuel_type', e.target.value)}>
            {FUELS.map((x) => (
              <option key={x.code} value={x.code}>{x.name}</option>
            ))}
          </select>
        </label>
        <label>
          반경
          <select value={f.radius_km} onChange={(e) => set('radius_km', +e.target.value)}>
            {RADII.map((r) => (
              <option key={r} value={r}>{r}km</option>
            ))}
          </select>
        </label>
      </div>

      <fieldset>
        <legend>알림 유형 (복수 선택)</legend>
        <label className="check">
          <input type="checkbox" checked={f.alert_types.includes('target_price')} onChange={() => toggleType('target_price')} />
          {ALERT_TYPE_LABEL.target_price}: 리터당
          <input className="num" type="number" inputMode="numeric" value={f.target_price} onChange={(e) => set('target_price', e.target.value)} disabled={!f.alert_types.includes('target_price')} />
          원 이하
        </label>
        {suggestedPrice ? (
          <p className="small muted hint">
            현재 최저가 {currentMin?.toLocaleString()}원 → 제안 목표가 <button type="button" className="link" onClick={() => set('target_price', suggestedPrice)}>{suggestedPrice.toLocaleString()}원 (-20원)</button>
          </p>
        ) : null}
        <label className="check">
          <input type="checkbox" checked={f.alert_types.includes('drop')} onChange={() => toggleType('drop')} />
          {ALERT_TYPE_LABEL.drop}: 반경 내 최저가가
          <input className="num" type="number" inputMode="numeric" value={f.drop_amount} onChange={(e) => set('drop_amount', e.target.value)} disabled={!f.alert_types.includes('drop')} />
          원 이상 하락
        </label>
        <label className="check">
          <input type="checkbox" checked={f.alert_types.includes('total_cost')} onChange={() => toggleType('total_cost')} />
          {ALERT_TYPE_LABEL.total_cost}: 실질 총비용
          <input className="num wide" type="number" inputMode="numeric" value={f.total_cost_limit} onChange={(e) => set('total_cost_limit', e.target.value)} disabled={!f.alert_types.includes('total_cost')} />
          원 이하 ({f.liters}L 기준)
        </label>
      </fieldset>

      <fieldset>
        <legend>필터</legend>
        <label className="check"><input type="checkbox" checked={f.self_only} onChange={(e) => set('self_only', e.target.checked)} /> 셀프 주유소만</label>
        <label className="check"><input type="checkbox" checked={f.alttle_only} onChange={(e) => set('alttle_only', e.target.checked)} /> 알뜰주유소만</label>
      </fieldset>

      <fieldset>
        <legend>렌터카 (선택)</legend>
        <div className="row">
          <label>
            대여 시작일
            <input type="date" value={f.rental_start} min={todayStr()} onChange={(e) => set('rental_start', e.target.value)} />
          </label>
          <label>
            반납일(종료일)
            <input type="date" value={f.rental_end} min={f.rental_start || todayStr()} onChange={(e) => set('rental_end', e.target.value)} />
          </label>
        </div>
        <p className="small muted">종료일이 지나면 알림이 자동으로 꺼지고 푸시 구독도 정리됩니다. 반납 전날/당일 아침 요약 알림도 받습니다.</p>
        <label>
          반납 장소
          <select value={ZONES.find((z) => z.lat === f.return_lat)?.key || ''} onChange={(e) => pickZone(e.target.value, 'dest')}>
            <option value="">지정 안 함</option>
            {ZONES.map((z) => (
              <option key={z.key} value={z.key}>{z.label}</option>
            ))}
          </select>
        </label>
        {f.return_lat != null && !ZONES.some((z) => z.lat === f.return_lat) && <p className="small muted">🏁 지도에서 고른 반납 장소 사용 중</p>}
        <label className="check">
          <input type="checkbox" checked={f.exclude_far_detour} disabled={f.return_lat == null} onChange={(e) => set('exclude_far_detour', e.target.checked)} />
          우회 시간이
          <input className="num" type="number" inputMode="numeric" value={f.max_detour_minutes} onChange={(e) => set('max_detour_minutes', e.target.value)} disabled={!f.exclude_far_detour} />
          분을 넘는 주유소 제외
        </label>
      </fieldset>

      {error && <p className="error" role="alert">{error}</p>}
      <div className="actions">
        {onCancel && <button type="button" className="btn" onClick={onCancel}>취소</button>}
        <button type="submit" className="btn primary" disabled={busy}>{busy ? '저장 중…' : submitLabel}</button>
      </div>
    </form>
  )
}
