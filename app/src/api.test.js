import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  api,
  testHubConnection,
  createWebSocket,
  getStoredHubAddress,
  storeHubAddress,
} from "./api";

beforeEach(() => {
  localStorage.clear();
  vi.restoreAllMocks();
});

describe("getStoredHubAddress", () => {
  it("returns default hub address when nothing has been stored", () => {
    expect(getStoredHubAddress()).toBe("10.0.0.175:8265");
  });

  it("returns the stored address", () => {
    storeHubAddress("192.168.1.50:8265");
    expect(getStoredHubAddress()).toBe("192.168.1.50:8265");
  });

  it("returns empty string when proxy mode was stored", () => {
    storeHubAddress("");
    expect(getStoredHubAddress()).toBe("");
  });
});

describe("proxy mode — empty hub address", () => {
  beforeEach(() => {
    storeHubAddress("");
  });

  it("api.getDevice fetches a relative URL", async () => {
    const spy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      text: () => Promise.resolve('{"connected":true}'),
    });

    await api.getDevice();

    expect(spy.mock.calls[0][0]).toBe("/api/device");
  });

  it("api.setMode fetches a relative URL", async () => {
    const spy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      text: () => Promise.resolve('{"ok":true}'),
    });

    await api.setMode("heat");

    expect(spy.mock.calls[0][0]).toBe("/api/device/mode");
  });

  it("testHubConnection with empty string fetches a relative URL", async () => {
    const spy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ connected: true }),
    });

    await testHubConnection("");

    expect(spy.mock.calls[0][0]).toBe("/api/device");
  });

  it("createWebSocket with empty string uses current host", () => {
    const urls = [];
    vi.stubGlobal(
      "WebSocket",
      class {
        constructor(url) {
          urls.push(url);
        }
        close() {}
      },
    );

    createWebSocket("", vi.fn(), vi.fn(), vi.fn());

    expect(urls[0]).toMatch(/^ws:\/\/localhost(:\d+)?\/ws$/);
  });
});

describe("direct mode — explicit hub address", () => {
  beforeEach(() => {
    storeHubAddress("192.168.1.50:8265");
  });

  it("api.getDevice uses absolute URL", async () => {
    const spy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      text: () => Promise.resolve('{"connected":true}'),
    });

    await api.getDevice();

    expect(spy.mock.calls[0][0]).toBe(
      "http://192.168.1.50:8265/api/device",
    );
  });

  it("testHubConnection uses absolute URL", async () => {
    const spy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ connected: true }),
    });

    await testHubConnection("10.0.0.5:8265");

    expect(spy.mock.calls[0][0]).toBe("http://10.0.0.5:8265/api/device");
  });

  it("createWebSocket with explicit address connects directly", () => {
    const urls = [];
    vi.stubGlobal(
      "WebSocket",
      class {
        constructor(url) {
          urls.push(url);
        }
        close() {}
      },
    );

    createWebSocket("192.168.1.50:8265", vi.fn(), vi.fn(), vi.fn());

    expect(urls[0]).toBe("ws://192.168.1.50:8265/ws");
  });
});
