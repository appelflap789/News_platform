import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// `npm run dev` serves the dashboard on :5173 and forwards API calls to the Python backend on :8765.
// `npm run build` writes frontend/dist, which the backend serves itself (no Node needed to run the app).
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { '/api': 'http://127.0.0.1:8765' } },
  build: { outDir: 'dist', emptyOutDir: true },
})
