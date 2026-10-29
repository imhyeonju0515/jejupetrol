import { useEffect } from 'react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { Circle, MapContainer, Marker, TileLayer, useMap, useMapEvents } from 'react-leaflet'

function priceIcon(station, selected, best) {
  const cls = ['price-marker', selected ? 'selected' : '', best ? 'best' : ''].join(' ')
  const label = station.price ? station.price.toLocaleString('ko-KR') : '-'
  return L.divIcon({
    className: '',
    html: `<div class="${cls}">${label}</div>`,
    iconSize: [58, 26],
    iconAnchor: [29, 26],
  })
}

const pinIcon = (emoji) => L.divIcon({ className: '', html: `<div class="pin">${emoji}</div>`, iconSize: [30, 30], iconAnchor: [15, 28] })

function Fly({ center }) {
  const map = useMap()
  useEffect(() => {
    map.flyTo([center.lat, center.lng], map.getZoom(), { duration: 0.6 })
  }, [center.lat, center.lng]) // eslint-disable-line react-hooks/exhaustive-deps
  return null
}

function Picker({ mode, onPick }) {
  useMapEvents({
    click(e) {
      if (mode) onPick(mode, { lat: +e.latlng.lat.toFixed(5), lng: +e.latlng.lng.toFixed(5) })
    },
  })
  return null
}

/** 주유소 마커(가격 표시) + 기준 위치/반납 장소 + 지도 클릭으로 위치 선택. */
export default function StationMap({ center, dest, stations, radiusKm, selectedId, bestId, pickMode, onPick, onSelect }) {
  return (
    <div className={`map-wrap ${pickMode ? 'picking' : ''}`}>
      <MapContainer center={[center.lat, center.lng]} zoom={12} scrollWheelZoom style={{ height: '100%', width: '100%' }}>
        <TileLayer attribution="&copy; OpenStreetMap" url="https://tile.openstreetmap.org/{z}/{x}/{y}.png" />
        <Fly center={center} />
        <Picker mode={pickMode} onPick={onPick} />
        <Circle center={[center.lat, center.lng]} radius={radiusKm * 1000} pathOptions={{ color: '#0b7a75', weight: 1, fillOpacity: 0.05 }} />
        <Marker position={[center.lat, center.lng]} icon={pinIcon('📍')} interactive={false} />
        {dest && <Marker position={[dest.lat, dest.lng]} icon={pinIcon('🏁')} interactive={false} />}
        {stations.map((s) => (
          <Marker
            key={s.id}
            position={[s.lat, s.lng]}
            icon={priceIcon(s, s.id === selectedId, s.id === bestId)}
            zIndexOffset={s.id === selectedId ? 1000 : s.id === bestId ? 500 : 0}
            eventHandlers={{ click: () => onSelect(s.id) }}
          />
        ))}
      </MapContainer>
      {pickMode && <div className="pick-hint">지도를 눌러 {pickMode === 'dest' ? '반납 장소' : '기준 위치'}를 지정하세요</div>}
    </div>
  )
}
