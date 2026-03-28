import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    proxy: {
      '/api/darwin': {
        target: 'http://localhost:9000',
        rewrite: (path) => path.replace(/^\/api\/darwin/, ''),
        changeOrigin: true,
      },
      '/api/locust': {
        target: 'http://localhost:8089',
        rewrite: (path) => path.replace(/^\/api\/locust/, ''),
        changeOrigin: true,
      },
    },
  },
})
