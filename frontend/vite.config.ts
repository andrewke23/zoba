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
    // When VITE_USE_MOCK=false, /api calls go to the FastAPI dev server.
    proxy: {
      '/api': {
        target: process.env.ZOBA_API_ORIGIN ?? 'http://localhost:8000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
})
