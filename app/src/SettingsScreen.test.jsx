import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import SettingsScreen from "./SettingsScreen";

const mockSetPreferences = vi.fn();
const mockSetHubAddr = vi.fn();
let hubState;

vi.mock("./hub", () => ({
  useHub: () => hubState,
}));

vi.mock("./api", () => ({
  api: {
    setLed: vi.fn(() => Promise.resolve()),
    setMute: vi.fn(() => Promise.resolve()),
    syncClock: vi.fn(() => Promise.resolve()),
    activateMemory: vi.fn(() => Promise.resolve()),
    activateDeviceBiorhythm: vi.fn(() => Promise.resolve()),
    updatePreferences: vi.fn(() =>
      Promise.resolve({ temperatureUnit: "celsius", autoSyncClock: false }),
    ),
  },
}));

beforeEach(() => {
  vi.clearAllMocks();
  hubState = {
    bleConnected: false,
    wsConnected: false,
    deviceState: null,
    metadata: null,
    preferences: {
      temperatureUnit: "fahrenheit",
      defaultFanSpeedPercent: 50,
      autoSyncClock: true,
    },
    setPreferences: mockSetPreferences,
    hubAddr: "",
    setHubAddr: mockSetHubAddr,
    unit: "fahrenheit",
  };
});

describe("SettingsScreen", () => {
  it("renders without crashing", () => {
    const { container } = render(<SettingsScreen />);
    expect(container).toBeInTheDocument();
  });

  it("shows connection status", () => {
    render(<SettingsScreen />);
    expect(screen.getByText("Hub")).toBeInTheDocument();
    expect(screen.getByText("BLE Device")).toBeInTheDocument();
  });

  it("shows temperature unit toggle", () => {
    render(<SettingsScreen />);
    expect(screen.getByText("Temperature Unit")).toBeInTheDocument();
  });

  it("shows auto sync clock toggle", () => {
    render(<SettingsScreen />);
    expect(screen.getByText("Auto Sync Clock")).toBeInTheDocument();
  });

  it("auto sync clock toggle calls updatePreferences", async () => {
    const { api } = await import("./api");
    render(<SettingsScreen />);
    const label = screen.getByText("Auto Sync Clock");
    const toggle = label
      .closest("div")
      .querySelector(".toggle-track");
    fireEvent.click(toggle);
    expect(api.updatePreferences).toHaveBeenCalledWith({
      autoSyncClock: false,
    });
  });
});
