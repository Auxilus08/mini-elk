import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    host: '0.0.0.0',
    // /api → search-api on the host. The browser-side default for
    // VITE_API_BASE_URL is still http://localhost:8000 (browser hits host's
    // exposed port), so this proxy is purely a dev-time convenience for
    // anyone wanting to relative-URL fetch.
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
  preview: {
    port: 3000,
    host: '0.0.0.0',
  },
})
