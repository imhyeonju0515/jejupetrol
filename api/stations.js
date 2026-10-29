// 오피넷(한국석유공사) 실시간 가격 프록시. 키는 Vercel 환경변수 OPINET_API_KEY 에만 둔다.
const proj4 = require('proj4');

proj4.defs(
  'KATEC',
  '+proj=tmerc +lat_0=38 +lon_0=128 +k=0.9999 +x_0=400000 +y_0=600000 +ellps=bessel +units=m +no_defs ' +
    '+towgs84=-115.80,474.99,674.11,1.16,-2.31,-1.63,6.43',
);

const BASE = 'https://www.opinet.co.kr/api';
const FUELS = ['B027', 'D047', 'B034', 'K015'];
const BRANDS = {
  SKE: 'SK에너지', GSC: 'GS칼텍스', HDO: '현대오일뱅크', SOL: 'S-OIL', RTE: '자영알뜰',
  RTX: '고속도로알뜰', NHO: '농협알뜰', E1G: 'E1', SKG: 'SK가스', ETC: '자가상표',
};
const ALT = ['RTE', 'RTX', 'NHO'];

const toKatec = (lat, lng) => proj4('EPSG:4326', 'KATEC', [lng, lat]);
const fromKatec = (x, y) => {
  const [lng, lat] = proj4('KATEC', 'EPSG:4326', [x, y]);
  return [lat, lng];
};
const rad = (d) => (d * Math.PI) / 180;
function distM(a, b) {
  const h = Math.sin(rad(b[0] - a[0]) / 2) ** 2 +
    Math.cos(rad(a[0])) * Math.cos(rad(b[0])) * Math.sin(rad(b[1] - a[1]) / 2) ** 2;
  return 2 * 6371008.8 * Math.asin(Math.sqrt(h));
}

async function getJson(url) {
  const ctl = new AbortController();
  const t = setTimeout(() => ctl.abort(), 6000);
  try {
    const r = await fetch(url, { signal: ctl.signal });
    if (!r.ok) throw new Error('오피넷 HTTP ' + r.status);
    return await r.json();
  } finally {
    clearTimeout(t);
  }
}

async function around(key, lat, lng, fuel) {
  const [x, y] = toKatec(lat, lng);
  const q = new URLSearchParams({ code: key, out: 'json', x: x.toFixed(1), y: y.toFixed(1), radius: '5000', prodcd: fuel, sort: '1' });
  const j = await getJson(`${BASE}/aroundAll.do?${q}`);
  const oil = j && j.RESULT && j.RESULT.OIL;
  return Array.isArray(oil) ? oil : [];
}

async function detail(key, id, fuel) {
  const q = new URLSearchParams({ code: key, out: 'json', id });
  const j = await getJson(`${BASE}/detailById.do?${q}`);
  const o = j && j.RESULT && j.RESULT.OIL && j.RESULT.OIL[0];
  if (!o) return null;
  const p = (o.OIL_PRICE || []).find((x) => x.PRODCD === fuel);
  let updated = '';
  if (p && p.TRADE_DT) {
    const d = String(p.TRADE_DT), t = String(p.TRADE_TM || '000000').padStart(6, '0');
    updated = `${d.slice(4, 6)}/${d.slice(6, 8)} ${t.slice(0, 2)}:${t.slice(2, 4)}`;
  }
  const flag = String(o.SELF_YN || o.SELF_DIV_CD || '').toUpperCase();
  return {
    addr: o.NEW_ADR || o.VAN_ADR || '',
    self: flag === 'Y' || flag === 'S' || String(o.OS_NM || '').includes('셀프'),
    updated,
  };
}

module.exports = async (req, res) => {
  const key = process.env.OPINET_API_KEY;
  if (!key) return res.status(503).json({ error: 'OPINET_API_KEY 가 설정되지 않았습니다.' });
  const lat = parseFloat(req.query.lat), lng = parseFloat(req.query.lng);
  const radius = Math.min(Math.max(parseInt(req.query.radius, 10) || 3000, 500), 10000);
  const fuel = String(req.query.fuel || 'B027');
  if (!FUELS.includes(fuel)) return res.status(422).json({ error: '지원하지 않는 유종입니다.' });
  if (!(lat >= 32.5 && lat <= 34.2 && lng >= 125.8 && lng <= 127.2)) return res.status(422).json({ error: '제주 범위를 벗어난 좌표입니다.' });

  try {
    // 오피넷 반경 상한 5km: 더 넓으면 중심 + 동서남북 5km 지점을 함께 조회
    const centers = [[lat, lng]];
    if (radius > 5000) {
      const dLat = 5000 / 111320, dLng = 5000 / (111320 * Math.cos(rad(lat)));
      centers.push([lat + dLat, lng], [lat - dLat, lng], [lat, lng + dLng], [lat, lng - dLng]);
    }
    const batches = await Promise.all(centers.map((c) => around(key, c[0], c[1], fuel)));
    const map = new Map();
    for (const o of batches.flat()) {
      const price = Math.round(Number(o.PRICE));
      if (!(price > 0) || !o.UNI_ID) continue;
      const [la, ln] = fromKatec(Number(o.GIS_X_COOR), Number(o.GIS_Y_COOR));
      if (distM([lat, lng], [la, ln]) > radius) continue;
      const brand = o.POLL_DIV_CD || o.POLL_DIV_CO || '';
      map.set(String(o.UNI_ID), {
        id: String(o.UNI_ID), name: String(o.OS_NM || '').trim(), brand: BRANDS[brand] || brand,
        lat: la, lng: ln, price, self: String(o.OS_NM || '').includes('셀프'), alt: ALT.includes(brand), addr: '', updated: '',
      });
    }
    const list = [...map.values()].sort((a, b) => a.price - b.price);
    // 상위 8곳은 상세 조회로 주소/셀프/갱신시각 보강 (실패해도 목록은 반환)
    const top = list.slice(0, 8);
    const ds = await Promise.allSettled(top.map((s) => detail(key, s.id, fuel)));
    ds.forEach((r, i) => { if (r.status === 'fulfilled' && r.value) Object.assign(top[i], r.value, { self: top[i].self || r.value.self }); });

    res.setHeader('Cache-Control', 's-maxage=300, stale-while-revalidate=600');
    res.status(200).json({ source: 'opinet', fuel, stations: list });
  } catch (e) {
    res.status(502).json({ error: '오피넷 조회에 실패했습니다. 잠시 후 다시 시도해 주세요.' });
  }
};
