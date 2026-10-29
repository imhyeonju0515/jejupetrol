export const FUELS = [
  { code: 'B027', name: '휘발유' },
  { code: 'D047', name: '경유' },
  { code: 'B034', name: '고급휘발유' },
  { code: 'K015', name: 'LPG' },
]
export const FUEL_NAME = Object.fromEntries(FUELS.map((f) => [f.code, f.name]))

export const RADII = [1, 3, 5, 10]

export const ZONES = [
  { key: 'airport', label: '제주공항', lat: 33.5113, lng: 126.493 },
  { key: 'jeju', label: '제주시', lat: 33.4996, lng: 126.5312 },
  { key: 'seogwipo', label: '서귀포', lat: 33.2541, lng: 126.5601 },
  { key: 'seongsan', label: '성산', lat: 33.458, lng: 126.9425 },
  { key: 'aewol', label: '애월', lat: 33.4636, lng: 126.3311 },
]

export const DEFAULT_CENTER = { lat: ZONES[0].lat, lng: ZONES[0].lng, label: ZONES[0].label }

export const ALERT_TYPE_LABEL = {
  target_price: '목표가 도달',
  drop: '최저가 하락',
  total_cost: '총비용 기준',
}

export const won = (n) => (n == null ? '-' : `${Math.round(n).toLocaleString('ko-KR')}원`)
