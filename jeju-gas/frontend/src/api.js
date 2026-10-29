import { getDeviceToken } from './hooks/useDeviceToken'

const BASE = import.meta.env.VITE_API_BASE || ''

export class ApiError extends Error {
  constructor(message, status) {
    super(message)
    this.status = status
  }
}

async function request(path, { method = 'GET', body } = {}) {
  let res
  try {
    res = await fetch(BASE + path, {
      method,
      headers: { 'Content-Type': 'application/json', 'X-Device-Token': getDeviceToken() },
      body: body ? JSON.stringify(body) : undefined,
    })
  } catch {
    throw new ApiError('네트워크 오류로 서버에 연결하지 못했습니다. 인터넷 연결을 확인하고 다시 시도해 주세요.', 0)
  }
  if (res.status === 204) return null
  let data = null
  try {
    data = await res.json()
  } catch {
    /* 본문 없음 */
  }
  if (!res.ok) {
    const detail = typeof data?.detail === 'string' ? data.detail : null
    throw new ApiError(detail || `요청에 실패했습니다. (오류 ${res.status})`, res.status)
  }
  return data
}

const qs = (o) =>
  new URLSearchParams(Object.entries(o).filter(([, v]) => v !== undefined && v !== null && v !== '')).toString()

export const api = {
  meta: () => request('/meta'),
  stations: (p) => request('/stations?' + qs(p)),
  priceHistory: (id, fuel, days = 7) => request(`/stations/${encodeURIComponent(id)}/price-history?${qs({ fuel_type: fuel, days })}`),
  listAlerts: () => request('/alerts'),
  createAlert: (body) => request('/alerts', { method: 'POST', body }),
  updateAlert: (id, body) => request(`/alerts/${id}`, { method: 'PATCH', body }),
  deleteAlert: (id) => request(`/alerts/${id}`, { method: 'DELETE' }),
  alertEvents: (id) => request(`/alerts/${id}/events`),
  testAlert: (id) => request(`/alerts/${id}/test`, { method: 'POST' }),
  subscribePush: (sub) => request('/push/subscribe', { method: 'POST', body: sub }),
  unsubscribePush: () => request('/push/subscribe', { method: 'DELETE' }),
}
