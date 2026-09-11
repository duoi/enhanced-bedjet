// @vitest-environment node
// Config-level test: vite.config.js pulls in vite/esbuild, which cannot run
// under jsdom.

import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import { afterEach, describe, expect, it } from "vitest";

import config from "../vite.config.js";

const TOKEN = "test-token-abc123";

/**
 * vite.config.js resolves its env with `loadEnv(mode, process.cwd(), '')`, which
 * also reads .env files from the current directory. Evaluate it from an empty
 * temporary directory so the test only ever sees variables it sets itself and
 * never the developer's local .env.
 */
function resolveConfig(mode = "production") {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "bedjet-vite-config-"));
  const previous = process.cwd();
  try {
    process.chdir(dir);
    return config({ mode });
  } finally {
    process.chdir(previous);
    fs.rmSync(dir, { recursive: true, force: true });
  }
}

describe("hub authentication through the proxy", () => {
  const originalToken = process.env.HUB_API_TOKEN;

  afterEach(() => {
    if (originalToken === undefined) delete process.env.HUB_API_TOKEN;
    else process.env.HUB_API_TOKEN = originalToken;
    delete process.env.ALLOWED_HOSTS;
  });

  it("adds no Authorization header when HUB_API_TOKEN is unset", () => {
    delete process.env.HUB_API_TOKEN;
    const { server, preview } = resolveConfig();

    expect(server.proxy["/api"].headers.Authorization).toBeUndefined();
    expect(server.proxy["/ws"].headers.Authorization).toBeUndefined();
    expect(preview.proxy["/api"].headers.Authorization).toBeUndefined();
    expect(preview.proxy["/ws"].headers.Authorization).toBeUndefined();
  });

  it("attaches the bearer token to preview proxy requests", () => {
    process.env.HUB_API_TOKEN = TOKEN;
    const { preview } = resolveConfig();

    expect(preview.proxy["/api"].headers.Authorization).toBe(`Bearer ${TOKEN}`);
    expect(preview.proxy["/ws"].headers.Authorization).toBe(`Bearer ${TOKEN}`);
  });

  it("attaches the bearer token to dev server proxy requests", () => {
    process.env.HUB_API_TOKEN = TOKEN;
    const { server } = resolveConfig("development");

    expect(server.proxy["/api"].headers.Authorization).toBe(`Bearer ${TOKEN}`);
    expect(server.proxy["/ws"].headers.Authorization).toBe(`Bearer ${TOKEN}`);
  });

  it("keeps the hub targets, origin rewrite and websocket upgrade intact", () => {
    process.env.HUB_API_TOKEN = TOKEN;
    const { server, preview } = resolveConfig();

    for (const proxy of [server.proxy, preview.proxy]) {
      expect(proxy["/api"].target).toBe("http://localhost:8265");
      expect(proxy["/api"].changeOrigin).toBe(true);
      expect(proxy["/ws"].target).toBe("ws://localhost:8265");
      expect(proxy["/ws"].ws).toBe(true);
    }
  });

  it("gives each server its own proxy options object", () => {
    const { server, preview } = resolveConfig();
    expect(server.proxy).not.toBe(preview.proxy);
  });

  it("still honours ALLOWED_HOSTS for the preview server", () => {
    process.env.ALLOWED_HOSTS = "hub.example.com,other.example.com";
    const { preview } = resolveConfig();

    expect(preview.allowedHosts).toEqual(["hub.example.com", "other.example.com"]);
  });
});
