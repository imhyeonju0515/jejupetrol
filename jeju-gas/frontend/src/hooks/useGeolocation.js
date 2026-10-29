import { useCallback, useState } from 'react'

/** "내 위치 사용" 버튼에서만 호출한다. */
export function useGeolocation() {
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const locate = useCallback(
    () =>
      new Promise((resolve) => {
        setError('')
        if (!navigator.geolocation) {
          setError('이 브라우저는 위치 기능을 지원하지 않습니다.')
          return resolve(null)
        }
        setLoading(true)
        navigator.geolocation.getCurrentPosition(
          (pos) => {
            setLoading(false)
            resolve({ lat: pos.coords.latitude, lng: pos.coords.longitude, label: '내 위치' })
          },
          (err) => {
            setLoading(false)
            setError(
              err.code === 1
                ? '위치 권한이 거부되었습니다. 브라우저 설정에서 허용하거나 권역 버튼을 사용해 주세요.'
                : err.code === 3
                  ? '위치 확인 시간이 초과되었습니다. 다시 시도해 주세요.'
                  : '현재 위치를 확인할 수 없습니다.',
            )
            resolve(null)
          },
          { enableHighAccuracy: false, timeout: 10000, maximumAge: 60000 },
        )
      }),
    [],
  )
  return { locate, loading, error }
}
