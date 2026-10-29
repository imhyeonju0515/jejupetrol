import { won } from '../constants'
import PriceChart from './PriceChart'

/** 추천 순위 목록: 순위 / 상호 / 리터당 가격 / 이동 시간 / 총비용 / 셀프 뱃지 + 알림 버튼. */
export default function StationList({ items, fuel, hasDest, selectedId, onSelect, onAlert }) {
  if (!items.length) return null
  return (
    <ol className="station-list">
      {items.map((r) => {
        const s = r.station
        const open = s.id === selectedId
        return (
          <li key={s.id} className={`station ${open ? 'open' : ''}`}>
            <button type="button" className="station-main" onClick={() => onSelect(open ? null : s.id)} aria-expanded={open}>
              <span className="rank">{r.rank}</span>
              <span className="info">
                <strong>{s.name}</strong>
                <span className="badges">
                  {s.is_self && <span className="badge self">셀프</span>}
                  {s.is_alttle && <span className="badge alttle">알뜰</span>}
                  {s.brand_name && <span className="muted small">{s.brand_name}</span>}
                  {r.price_rank !== r.rank && <span className="muted small">가격순 {r.price_rank}위</span>}
                </span>
              </span>
              <span className="nums">
                <span className="price">{r.price.toLocaleString()}<small>원/L</small></span>
                <span className="muted small">
                  {hasDest ? '우회' : '왕복'} {Math.round(r.extra_minutes)}분{r.estimated ? '(추정)' : ''}
                </span>
                <span className="total">총 {won(r.total_cost)}</span>
              </span>
            </button>
            {open && (
              <div className="station-detail">
                <p className="small">{s.address || '주소 정보 없음'}</p>
                <p className="small muted">
                  주유 {won(r.fuel_cost)} + 시간 {won(r.time_cost)} + 이동연료 {won(r.travel_fuel_cost)}
                  {s.updated_at && ` · 가격 갱신 ${new Date(s.updated_at).toLocaleString('ko-KR', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })}`}
                </p>
                <PriceChart stationId={s.id} fuel={fuel} />
                <button type="button" className="btn primary" onClick={() => onAlert(s)}>
                  🔔 이 가격에 알림
                </button>
              </div>
            )}
          </li>
        )
      })}
    </ol>
  )
}
