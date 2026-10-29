const KEY = 'jeju-gas-device-token'

/** 회원가입 없이 쓰는 익명 기기 식별값. 브라우저에 한 번 만들어 저장한다. */
export function getDeviceToken() {
  try {
    let t = localStorage.getItem(KEY)
    if (!t) {
      t = (crypto.randomUUID ? crypto.randomUUID() : String(Math.random()).slice(2) + Date.now()) + '-jg'
      localStorage.setItem(KEY, t)
    }
    return t
  } catch {
    return 'volatile-token-' + String(Math.random()).slice(2, 14).padEnd(12, '0')
  }
}
