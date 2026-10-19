import path from 'node:path'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
  ],
  resolve: {
    alias: {
      '@': path.resolve(import.meta.dirname, './src'),
    },
  },
  server: {
    port: 8081,
    host: true,
    // Bind-mounted sources on Windows/macOS Docker may not emit fs events
    watch: process.env.VITE_USE_POLLING === 'true' ? { usePolling: true, interval: 300 } : undefined,
    // Same-origin /api in dev, mirrors the nginx proxy in production (no CORS needed)
    proxy: {
      '/api': {
        target: process.env.VITE_API_PROXY_TARGET ?? 'http://localhost:8088',
        changeOrigin: true,
      },
    },
  },
  preview: {
    port: 8081,
  },
})
