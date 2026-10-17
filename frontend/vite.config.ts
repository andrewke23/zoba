import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: {
    rollupOptions: {
      output: { manualChunks: { maplibre: ['maplibre-gl'] } },
    },
    chunkSizeWarningLimit: 1100, // maplibre-gl alone is ~1 MB
  },
  server: {
    // The real backend serves /api/v1/* itself, so requests are forwarded
    // unmodified. Override the target with ZOBA_API_ORIGIN when the API runs
    // somewhere else.
    proxy: {
      '/api': {
        target: process.env.ZOBA_API_ORIGIN ?? 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
