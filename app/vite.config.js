import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');
  return {
    plugins: [react()],
    server: {
      host: true,
      port: 3000,
      proxy: {
        "/api": {
          target: "http://localhost:8265",
          changeOrigin: true,
        },
        "/ws": {
          target: "ws://localhost:8265",
          ws: true,
        },
      },
    },
        preview: {
      allowedHosts: env.ALLOWED_HOSTS ? env.ALLOWED_HOSTS.split(',') : [],
      proxy: {
        "/api": {
          target: "http://localhost:8265",
          changeOrigin: true,
        },
        "/ws": {
          target: "ws://localhost:8265",
          ws: true,
        },
      },
    },
    test: {
      environment: "jsdom",
      globals: true,
      setupFiles: "./src/test-setup.js",
    },
  };
});