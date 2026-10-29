import { useEffect, useState } from 'react'
import { api } from '../api'

/** 최근 7일 가격 추이 미니 차트 (SVG). */
export default function PriceChart({ stationId, fuel }) {
  const [points, setPoints] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    let cancelled = false
    setPoints(null)
    setError('')
    api
      .priceHistory(stationId, fuel, 7)
      .then((d) => !cancelled && setPoints(d.points))
      .catch((e) => !cancelled && setError(e.message))
    return () => {
      cancelled = true
    }
  }, [stationId, fuel])

  if (error) return <p className="muted small">{error}</p>
  if (!points) return <p className="muted small">가격 추이를 불러오는 중…</p>
  if (points.length < 2) return <p className="muted small">아직 가격 이력이 부족합니다. (조회할수록 쌓입니다)</p>

  const W = 300
  const H = 80
  const pad = 6
  const ts = points.map((p) => new Date(p.t).getTime())
  const ps = points.map((p) => p.price)
  const [t0, t1] = [Math.min(...ts), Math.max(...ts)]
  const [lo, hi] = [Math.min(...ps), Math.max(...ps)]
  const x = (t) => pad + ((t - t0) / Math.max(t1 - t0, 1)) * (W - pad * 2)
  const y = (p) => H - pad - ((p - lo) / Math.max(hi - lo, 1)) * (H - pad * 2)
  const d = points.map((p, i) => `${i ? 'L' : 'M'}${x(new Date(p.t).getTime()).toFixed(1)},${y(p.price).toFixed(1)}`).join(' ')
  const last = ps[ps.length - 1]

  return (
    <div className="chart">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`최근 7일 가격 추이, 최저 ${lo}원 최고 ${hi}원`}>
        <path d={d} fill="none" stroke="var(--brand)" strokeWidth="2" strokeLinejoin="round" />
        <circle cx={x(ts[ts.length - 1])} cy={y(last)} r="3.5" fill="var(--brand)" />
      </svg>
      <div className="chart-legend small muted">
        <span>7일 최저 {lo.toLocaleString()}원</span>
        <span>현재 {last.toLocaleString()}원</span>
        <span>최고 {hi.toLocaleString()}원</span>
      </div>
    </div>
  )
}
