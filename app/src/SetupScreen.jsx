/**
 * Initial setup screen — probes for a local proxy first (Vite dev
 * server forwarding to the hub). If the probe succeeds, connects
 * immediately in proxy mode. Otherwise shows manual address entry.
 */
import { useState, useEffect, useCallback } from "react";
import { testHubConnection, DEFAULT_HUB_ADDRESS } from "./api";

export default function SetupScreen({ onConnect, onSkip }) {
  const [probing, setProbing] = useState(true);
  const [addr, setAddr] = useState(DEFAULT_HUB_ADDRESS);
  const [testing, setTesting] = useState(false);
  const [error, setError] = useState("");

  const stableOnConnect = useCallback(onConnect, [onConnect]);

  useEffect(() => {
    let cancelled = false;
    testHubConnection("")
      .then(() => {
        if (!cancelled) stableOnConnect("");
      })
      .catch(() => {
        if (!cancelled) setProbing(false);
      });
    return () => {
      cancelled = true;
    };
  }, [stableOnConnect]);

  const handleConnect = async () => {
    const trimmed = addr.trim();
    if (!trimmed) return;
    setTesting(true);
    setError("");
    try {
      await testHubConnection(trimmed);
      onConnect(trimmed);
    } catch {
      setError("Could not reach hub. Check the address and try again.");
    }
    setTesting(false);
  };

  if (probing) {
    return (
      <div className="setup-page">
        <div className="setup-logo">🌙</div>
        <div className="setup-subtitle">Detecting hub…</div>
      </div>
    );
  }

  return (
    <div className="setup-page">
      <div className="setup-branding">
        <div className="setup-logo">🌙</div>
        <div className="setup-title">BedJet</div>
        <div className="setup-subtitle">Sleep Climate Control</div>
      </div>

      <div className="setup-form">
        <div className="section-label">Hub Address</div>
        <input
          className="setup-input"
          value={addr}
          onChange={(e) => setAddr(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleConnect()}
          placeholder="192.168.1.x:8265"
          autoFocus
        />

        {error && <div className="setup-error">{error}</div>}

        <button
          onClick={handleConnect}
          disabled={testing || !addr.trim()}
          className="primary-btn"
          style={{ marginTop: "16px" }}
        >
          {testing ? "Connecting..." : "Connect"}
        </button>

        <button onClick={onSkip} className="skip-btn">
          Skip — browse without a hub
        </button>
      </div>
    </div>
  );
}
