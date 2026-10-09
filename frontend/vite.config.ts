/// <reference types="vitest/config" />
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Inside Docker the backend is reached by its service name, outside Docker on localhost
const apiTarget = process.env.API_PROXY_TARGET ?? 'http://localhost:8000'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    // File change events do not reach containers from a Windows folder, so poll for changes there
    watch: process.env.WATCH_POLLING === 'true' ? { usePolling: true } : undefined,
    // Forward /api calls to the FastAPI backend during development
    proxy: {
      '/api': {
        target: apiTarget,
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: './src/test/setup.ts',
    unstubGlobals: true,
  },
})
