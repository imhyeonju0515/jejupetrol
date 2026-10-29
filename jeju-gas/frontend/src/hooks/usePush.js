import { api } from '../api'

function urlBase64ToUint8Array(base64) {
  const padding = '='.repeat((4 - (base64.length % 4)) % 4)
  const raw = atob((base64 + padding).replace(/-/g, '+').replace(/_/g, '/'))
  return Uint8Array.from([...raw].map((c) => c.charCodeAt(0)))
}

/**
 * 웹 푸시를 켠다. 반드시 사용자가 "🔔 알림 등록" 버튼을 누른 핸들러 안에서만 호출할 것
 * (페이지 진입 시 자동으로 권한을 묻지 않는다).
 *
 * @returns {{status: 'ok'|'mock'|'no-key'|'denied'|'unsupported'|'error', message: string}}
 *  알림 규칙 등록 자체는 status 와 무관하게 진행할 수 있고, message 는 사용자 안내용이다.
 */
export async function enablePush() {
  if (!('serviceWorker' in navigator) || !('PushManager' in window) || !('Notification' in window)) {
    return { status: 'unsupported', message: '이 브라우저는 웹 푸시를 지원하지 않아 알림을 받을 수 없습니다. (iOS는 홈 화면에 추가 후 사용)' }
  }
  if (Notification.permission === 'denied') {
    return { status: 'denied', message: '알림 권한이 차단되어 있습니다. 브라우저 설정에서 이 사이트의 알림을 허용해 주세요.' }
  }
  try {
    const meta = await api.meta()
    if (meta.mock && !meta.vapid_public_key) {
      return { status: 'mock', message: 'MOCK 모드입니다. 푸시 대신 서버 콘솔로 알림이 출력됩니다.' }
    }
    if (!meta.vapid_public_key) {
      return { status: 'no-key', message: '서버에 푸시 키(VAPID)가 설정되지 않아 푸시 알림을 받을 수 없습니다.' }
    }
    const permission = await Notification.requestPermission()
    if (permission !== 'granted') {
      return { status: 'denied', message: '알림 권한이 허용되지 않아 푸시를 받을 수 없습니다. 브라우저 설정에서 허용해 주세요.' }
    }
    const reg = await navigator.serviceWorker.ready
    let sub = await reg.pushManager.getSubscription()
    if (!sub) {
      sub = await reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(meta.vapid_public_key),
      })
    }
    await api.subscribePush(sub.toJSON())
    return { status: 'ok', message: '푸시 알림이 켜졌습니다.' }
  } catch (e) {
    if (e?.name === 'AbortError' || e?.name === 'InvalidStateError') {
      return { status: 'error', message: '푸시 구독이 만료되었거나 실패했습니다. 잠시 후 다시 시도해 주세요.' }
    }
    return { status: 'error', message: e?.message || '푸시 설정 중 오류가 발생했습니다.' }
  }
}
