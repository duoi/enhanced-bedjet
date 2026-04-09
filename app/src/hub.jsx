/**
 * Hub context provider. Manages WebSocket connection, device state,
 * metadata, and user preferences. All child components access hub
 * state through the useHub() hook.
 */
import {
  createContext,
  useContext,
  useState,
  useEffect,
  useCallback,
  useMemo,
  useRef,
} from "react";
import {
  getStoredHubAddress,
  storeHubAddress,
  createWebSocket,
  api,
} from "./api";

const HubContext = createContext(null);

const DEFAULT_PREFS = {
  temperatureUnit: "fahrenheit",
  defaultFanSpeedPercent: 50,
  autoSyncClock: true,
};

function shallowEqual(a, b) {
  if (a === b) return true;
  if (!a || !b) return false;
  const keysA = Object.keys(a);
  if (keysA.length !== Object.keys(b).length) return false;
  return keysA.every((k) => a[k] === b[k]);
}

export function HubProvider({ children }) {
  const [hubAddr, setHubAddrRaw] = useState(getStoredHubAddress);
  const [wsConnected, setWsConnected] = useState(false);
  const [bleConnected, setBleConnected] = useState(false);
  const [deviceState, setDeviceState] = useState(null);
  const [metadata, setMetadata] = useState(null);
  const [activeProgram, setActiveProgram] = useState(null);
  const [preferences, setPreferences] = useState(DEFAULT_PREFS);

  const wsRef = useRef(null);
  const reconnectRef = useRef(null);

  const setHubAddr = useCallback((addr) => {
    storeHubAddress(addr);
    setHubAddrRaw(addr);
  }, []);

  const connect = useCallback(() => {
    clearTimeout(reconnectRef.current);
    const oldWs = wsRef.current;
    if (oldWs) {
      oldWs.onclose = null;
      oldWs.onmessage = null;
      oldWs.onerror = null;
      oldWs.close();
      wsRef.current = null;
    }
    if (hubAddr == null) return;

    const ws = createWebSocket(
      hubAddr,
      (msg) => {
        if (msg.type === "state") {
          setBleConnected((prev) => (prev === msg.connected ? prev : msg.connected));
          setDeviceState((prev) => (shallowEqual(prev, msg.state) ? prev : msg.state));
          setActiveProgram((prev) => (shallowEqual(prev, msg.activeProgram) ? prev : msg.activeProgram));
        } else if (msg.type === "connection") {
          setBleConnected((prev) => (prev === msg.connected ? prev : msg.connected));
        }
      },
      () => {
        setWsConnected(true);
        api.getDevice().then((d) => {
          setMetadata((prev) => (shallowEqual(prev, d.metadata) ? prev : d.metadata));
        }).catch(() => {});
        api.getPreferences().then((p) => {
          setPreferences((prev) => (shallowEqual(prev, p) ? prev : p));
        }).catch(() => {});
      },
      () => {
        setWsConnected(false);
        reconnectRef.current = setTimeout(connect, 3000);
      },
    );
    wsRef.current = ws;
  }, [hubAddr]);

  useEffect(() => {
    connect();
    return () => {
      clearTimeout(reconnectRef.current);
      const ws = wsRef.current;
      if (ws) {
        ws.onclose = null;
        ws.onmessage = null;
        ws.onerror = null;
        ws.close();
        wsRef.current = null;
      }
    };
  }, [connect]);

  const unit = preferences?.temperatureUnit || "fahrenheit";

  const value = useMemo(
    () => ({
      hubAddr,
      setHubAddr,
      wsConnected,
      bleConnected,
      deviceState,
      metadata,
      activeProgram,
      preferences,
      setPreferences,
      unit,
      reconnect: connect,
    }),
    [hubAddr, setHubAddr, wsConnected, bleConnected, deviceState, metadata, activeProgram, preferences, unit, connect],
  );

  return (
    <HubContext.Provider value={value}>
      {children}
    </HubContext.Provider>
  );
}

export function useHub() {
  const ctx = useContext(HubContext);
  if (!ctx) throw new Error("useHub must be used within HubProvider");
  return ctx;
}
