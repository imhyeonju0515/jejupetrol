import { useEffect, useState } from 'react'
import AlertModal from '../components/AlertModal'
import StationList from '../components/StationList'
import StationMap from '../components/StationMap'
import { DEFAULT_CENTER, FUELS, RADII, ZONES } from '../constants'
import { useGeolocation } from '../hooks/useGeolocation'
import { useStations } from '../hooks/useStations'

export default function HomePage({ focus }) {
  const [center, setCenter] = useState(DEFAULT_CENTER)
  const [fuel, setFuel] = useState('B027')
  const [radiusKm, setRadiusKm] = useState(3)
  const [dest, setDest] = useState(null)
  const [nearReturn, setNearReturn] = useState(false)
  const [pickMode, setPickMode] = useState(null)
  const [selectedId, setSelectedId] = useState(null)
  const [alertFor, setAlertFor] = useState(null)
  const [liters, setLiters] = useState(30)
  const { locate, loading: locating, error: geoError } = useGeolocation()

  // 푸시 클릭으로 들어오면 해당 주유소 위치로 이동
  useEffect(() => {
    if (focus?.lat && focus?.lng) {
      setCenter({ lat: focus.lat, lng: focus.lng, label: '알림 주유소' })
      setRadiusKm((r) => Math.min(r, 3))
    }
    if (focus?.station) setSelectedId(focus.station)
  }, [focus?.station, focus?.lat, focus?.lng]) // eslint-disable-line react-hooks/exhaustive-deps

  const { data, loading, error } = useStations({
    lat: center.lat,
    lng: center.lng,
    radius: radiusKm * 1000,
    fuel_type: fuel,
    liters,
    dest_lat: dest?.lat,
    dest_lng: dest?.lng,
    near_return: dest && nearReturn ? 'true' : undefined,
  })

  const useMyLocation = async () => {
    const p = await locate()
    if (p) setCenter(p)
  }
  const onPick = (mode, pt) => {
    if (mode === 'dest') setDest({ ...pt, label: '지도에서 선택' })
    else setCenter({ ...pt, label: '지도에서 선택' })
    setPickMode(null)
  }
  const pickDestZone = (key) => {
    const z = ZONES.find((x) => x.key === key)
    setDest(z ? { lat: z.lat, lng: z.lng, label: z.label } : null)
  }

  const recs = data?.recommendations || []
  const best = recs[0]
  const alertContext = { center, radiusKm, fuel, dest }

  return (
    <div className="home">
      <section className="controls" aria-label="검색 조건">
        <div className="chips" role="group" aria-label="권역 바로가기">
          {ZONES.map((z) => (
            <button key={z.key} type="button" className={`chip ${center.label === z.label ? 'active' : ''}`} onClick={() => setCenter({ lat: z.lat, lng: z.lng, label: z.label })}>
              {z.label}
            </button>
          ))}
          <button type="button" className="chip" onClick={useMyLocation} disabled={locating}>
            {locating ? '확인 중…' : '📍 내 위치 사용'}
          </button>
          <button type="button" className={`chip ${pickMode === 'center' ? 'active' : ''}`} onClick={() => setPickMode(pickMode === 'center' ? null : 'center')}>
            🗺 지도에서 선택
          </button>
        </div>
        {geoError && <p className="error small" role="alert">{geoError}</p>}

        <div className="row">
          <label>
            유종
            <select value={fuel} onChange={(e) => setFuel(e.target.value)}>
              {FUELS.map((f) => (
                <option key={f.code} value={f.code}>{f.name}</option>
              ))}
            </select>
          </label>
          <label>
            반경
            <select value={radiusKm} onChange={(e) => setRadiusKm(+e.target.value)}>
              {RADII.map((r) => (
                <option key={r} value={r}>{r}km</option>
              ))}
            </select>
          </label>
          <label>
            주유량(L)
            <input type="number" min="5" max="100" value={liters} onChange={(e) => setLiters(Math.max(1, +e.target.value || 30))} />
          </label>
        </div>

        <div className="row">
          <label>
            반납 장소
            <select value={ZONES.find((z) => dest && z.lat === dest.lat)?.key || (dest ? 'custom' : '')} onChange={(e) => e.target.value !== 'custom' && pickDestZone(e.target.value)}>
              <option value="">지정 안 함</option>
              {dest && !ZONES.some((z) => z.lat === dest.lat) && <option value="custom">지도에서 선택한 위치</option>}
              {ZONES.map((z) => (
                <option key={z.key} value={z.key}>{z.label}</option>
              ))}
            </select>
          </label>
          <button type="button" className={`btn small-btn ${pickMode === 'dest' ? 'primary' : ''}`} onClick={() => setPickMode(pickMode === 'dest' ? null : 'dest')}>
            🏁 지도에서 반납 장소
          </button>
        </div>
        {dest && (
          <label className="check">
            <input type="checkbox" checked={nearReturn} onChange={(e) => setNearReturn(e.target.checked)} />
            반납 장소 3km 이내 주유소 우선
          </label>
        )}
      </section>

      <StationMap
        center={center}
        dest={dest}
        stations={data?.stations || []}
        radiusKm={radiusKm}
        selectedId={selectedId}
        bestId={best?.station.id}
        pickMode={pickMode}
        onPick={onPick}
        onSelect={setSelectedId}
      />

      <section aria-live="polite">
        {loading && <p className="muted">주유소를 찾는 중…</p>}
        {error && <p className="error" role="alert">{error}</p>}
        {data?.notices?.map((n) => (
          <p key={n} className="notice small">ℹ️ {n}</p>
        ))}
        {data?.rank_differs && <p className="explain">💡 {data.explanation}</p>}
        {!loading && data && !recs.length && !error && <p className="muted">추천할 주유소가 없습니다.</p>}
        <StationList items={recs} fuel={fuel} hasDest={!!dest} selectedId={selectedId} onSelect={setSelectedId} onAlert={setAlertFor} />
        {data && <p className="small muted">반경 내 {data.total_found}곳 · 총비용 = 주유금액 + 시간가치(10,000원/시간) + 이동 연료비</p>}
      </section>

      {alertFor && <AlertModal station={alertFor} context={alertContext} onClose={() => setAlertFor(null)} />}
    </div>
  )
}
