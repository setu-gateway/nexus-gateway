import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    host: true, // bind 0.0.0.0, not just localhost - required to be reachable from
    // outside the container when run via docker-compose (or from other devices on
    // the LAN during local dev)
    port: process.env.PORT ? Number(process.env.PORT) : 3000,
    proxy: {
      "/api": {
        // Server-side only (no VITE_ prefix, so this never leaks into the client
        // bundle) - GATEWAY_URL is the gateway's address as seen by *this container*
        // (e.g. the docker-compose service name), which is usually different from
        // VITE_GATEWAY_URL, the address the *browser* would use if api.ts talks to
        // the gateway directly instead of through this proxy.
        target: process.env.GATEWAY_URL || "http://localhost:8000",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
});
