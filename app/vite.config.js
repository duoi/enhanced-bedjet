import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');

  // Both the dev server and the preview server forward API and WebSocket
  // traffic to the hub. When the hub requires a bearer token, attach it here so
  // that the browser never handles the secret: the client keeps talking to this
  // same-origin proxy, and the header is added server-side.
  //
  // Leave HUB_API_TOKEN unset when the hub is unauthenticated, or when browser
  // traffic is authenticated in front of the hub (Cloudflare Access, for
  // example) — in that case the end user is already authenticated upstream.
  const hubAuthHeaders = env.HUB_API_TOKEN
    ? { Authorization: `Bearer ${env.HUB_API_TOKEN}` }
    : {};

  // Built per call rather than shared, so the two servers never mutate each
  // other's proxy options.
  const hubProxy = () => ({
    "/api": {
      target: "http://localhost:8265",
      changeOrigin: true,
      headers: hubAuthHeaders,
    },
    "/ws": {
      target: "ws://localhost:8265",
      ws: true,
      headers: hubAuthHeaders,
    },
  });

  return {
    plugins: [react()],
    server: {
      host: true,
      port: 3000,
      proxy: hubProxy(),
    },
    preview: {
      allowedHosts: env.ALLOWED_HOSTS ? env.ALLOWED_HOSTS.split(',') : [],
      proxy: hubProxy(),
    },
    test: {
      environment: "jsdom",
      globals: true,
      setupFiles: "./src/test-setup.js",
    },
  };
});
