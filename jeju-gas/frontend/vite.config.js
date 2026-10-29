import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// 라우팅은 해시(#/)라서 /stations, /alerts, /push, /meta 는 전부 백엔드 API 로 프록시한다.
const target = process.env.VITE_BACKEND || 'http://localhost:8000'
const proxy = Object.fromEntries(
  ['/stations', '/alerts', '/push', '/meta'].map((p) => [p, { target, changeOrigin: true }]),
)

export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy },
})
