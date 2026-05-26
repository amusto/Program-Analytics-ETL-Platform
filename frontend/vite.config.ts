import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // Proxy API requests during dev so the dashboard can use relative URLs.
      "/analytics": "http://localhost:8000",
      "/projects": "http://localhost:8000",
      "/etl": "http://localhost:8000",
      "/health": "http://localhost:8000",
    },
  },
});
