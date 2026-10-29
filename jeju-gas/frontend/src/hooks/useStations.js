import { useEffect, useState } from 'react'
import { api } from '../api'

/** 조건이 바뀔 때마다 /stations 를 다시 조회한다. */
export function useStations(params, enabled = true) {
  const [state, setState] = useState({ data: null, loading: false, error: '' })
  const key = JSON.stringify(params)

  useEffect(() => {
    if (!enabled) return undefined
    let cancelled = false
    setState((s) => ({ ...s, loading: true, error: '' }))
    const timer = setTimeout(() => {
      api
        .stations(params)
        .then((data) => !cancelled && setState({ data, loading: false, error: '' }))
        .catch((e) => !cancelled && setState({ data: null, loading: false, error: e.message }))
    }, 250)
    return () => {
      cancelled = true
      clearTimeout(timer)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, enabled])

  return state
}
