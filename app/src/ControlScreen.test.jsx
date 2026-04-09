import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import ControlScreen from "./ControlScreen";

const mockSetPreferences = vi.fn();
let hubState;

vi.mock("./hub", () => ({
  useHub: () => hubState,
}));

vi.mock("./api", () => ({
  api: {
    setMode: vi.fn(() => Promise.resolve()),
    setFanSpeed: vi.fn(() => Promise.resolve()),
    setTemperature: vi.fn(() => Promise.resolve()),
    setRuntime: vi.fn(() => Promise.resolve()),
    stopProgram: vi.fn(() => Promise.resolve()),
    updatePreferences: vi.fn(() =>
      Promise.resolve({ temperatureUnit: "celsius" }),
    ),
  },
}));

beforeEach(() => {
  vi.clearAllMocks();
  hubState = {
    deviceState: null,
    activeProgram: null,
    unit: "fahrenheit",
    preferences: { temperatureUnit: "fahrenheit" },
    setPreferences: mockSetPreferences,
  };
});

/** Helper to get the api mock inside tests. */
async function getApi() {
  return (await import("./api")).api;
}

describe("ControlScreen", () => {
  it("renders without crashing when deviceState is null (skipped setup)", () => {
    const { container } = render(<ControlScreen />);
    expect(container).toBeInTheDocument();
  });

  it("displays the temperature readout", () => {
    render(<ControlScreen />);
    expect(screen.getByText("°F")).toBeInTheDocument();
  });

  it("displays the mode selector with all 5 modes", () => {
    const { container } = render(<ControlScreen />);
    const modeButtons = container.querySelectorAll(".mode-btn");
    expect(modeButtons.length).toBe(5);
    const labels = Array.from(modeButtons).map((b) => b.textContent.trim());
    expect(labels.some((l) => l.includes("Heat"))).toBe(true);
    expect(labels.some((l) => l.includes("Cool"))).toBe(true);
    expect(labels.some((l) => l.includes("Dry"))).toBe(true);
    expect(labels.some((l) => l.includes("Turbo"))).toBe(true);
  });

  it("displays the fan speed section", () => {
    render(<ControlScreen />);
    expect(screen.getByText("Fan Speed")).toBeInTheDocument();
  });

  it("displays the status strip", () => {
    render(<ControlScreen />);
    expect(screen.getByText("Runtime")).toBeInTheDocument();
    expect(screen.getByText("Ambient")).toBeInTheDocument();
    const modeLabels = screen.getAllByText("Mode");
    expect(modeLabels.length).toBeGreaterThanOrEqual(1);
  });

  it("unit label is a clickable button", () => {
    render(<ControlScreen />);
    const unitBtn = screen.getByRole("button", { name: /°F/i });
    expect(unitBtn).toBeInTheDocument();
  });

  it("clicking unit label calls updatePreferences to toggle unit", async () => {
    const { api } = await import("./api");
    render(<ControlScreen />);
    const unitBtn = screen.getByRole("button", { name: /°F/i });
    fireEvent.click(unitBtn);
    expect(api.updatePreferences).toHaveBeenCalledWith({
      temperatureUnit: "celsius",
    });
  });

  it("runtime card is clickable when device has runtime data", () => {
    hubState.deviceState = { runtimeRemainingSeconds: 3600 };
    render(<ControlScreen />);
    const runtimeCard = screen.getByText("Runtime").closest("[role='button']");
    expect(runtimeCard).toBeInTheDocument();
  });

  it("clicking runtime card shows the runtime editor with select dropdowns", () => {
    hubState.deviceState = { runtimeRemainingSeconds: 3600 };
    render(<ControlScreen />);
    const runtimeCard = screen.getByText("Runtime").closest("[role='button']");
    fireEvent.click(runtimeCard);
    const hoursSelect = screen.getByLabelText("Hours");
    const minutesSelect = screen.getByLabelText("Minutes");
    expect(hoursSelect.tagName).toBe("SELECT");
    expect(minutesSelect.tagName).toBe("SELECT");
    expect(hoursSelect.options.length).toBe(13);
    expect(minutesSelect.options.length).toBe(60);
  });

  it("runtime editor calls api.setRuntime on save", async () => {
    const api = await getApi();
    hubState.deviceState = { runtimeRemainingSeconds: 3600 };
    render(<ControlScreen />);
    const runtimeCard = screen.getByText("Runtime").closest("[role='button']");
    fireEvent.click(runtimeCard);
    fireEvent.change(screen.getByLabelText("Hours"), { target: { value: "2" } });
    fireEvent.change(screen.getByLabelText("Minutes"), { target: { value: "30" } });
    fireEvent.click(screen.getByText("Set"));
    expect(api.setRuntime).toHaveBeenCalledWith(2, 30);
  });

  it("mode button shows loading state while command is in flight", async () => {
    let resolveMode;
    const api = await getApi();
    api.setMode.mockImplementation(
      () => new Promise((r) => (resolveMode = r)),
    );
    const { container, rerender } = render(<ControlScreen />);
    const heatBtn = Array.from(container.querySelectorAll(".mode-btn")).find(
      (b) => b.textContent.includes("Heat"),
    );
    fireEvent.click(heatBtn);
    expect(heatBtn.classList.contains("loading")).toBe(true);
    resolveMode();
    hubState.deviceState = { mode: "heat" };
    rerender(<ControlScreen />);
    await vi.waitFor(() =>
      expect(heatBtn.classList.contains("loading")).toBe(false),
    );
  });

  it("temperature stays at user-set value until WebSocket confirms", async () => {
    vi.useFakeTimers();
    let resolveTemp;
    const api = await getApi();
    api.setTemperature.mockImplementation(
      () => new Promise((r) => (resolveTemp = r)),
    );
    hubState.deviceState = {
      targetTemperatureC: 22,
      minTemperatureC: 10,
      maxTemperatureC: 40,
    };
    const { rerender } = render(<ControlScreen />);

    // Click the 90°F quick preset (triggers onTempChange(90))
    const btn90 = screen.getByRole("button", { name: /90\s*°/ });
    fireEvent.click(btn90);

    // Debounce fires
    vi.advanceTimersByTime(350);

    // API is in flight — localTemp should still hold.
    // Simulate a WebSocket push with the OLD value.
    hubState.deviceState = {
      ...hubState.deviceState,
      targetTemperatureC: 22,
    };
    rerender(<ControlScreen />);

    // The displayed temp should NOT snap back to 72°F (22°C);
    // it should remain at the user-set value (90°F).
    expect(screen.queryByText("72")).toBeNull();

    vi.useRealTimers();
  });

  it("fan speed stays at user-set value until WebSocket confirms", async () => {
    vi.useFakeTimers();
    let resolveFan;
    const api = await getApi();
    api.setFanSpeed.mockImplementation(
      () => new Promise((r) => (resolveFan = r)),
    );
    hubState.deviceState = { fanSpeedPercent: 30 };
    const { rerender } = render(<ControlScreen />);

    const slider = screen.getByRole("slider");
    fireEvent.change(slider, { target: { value: 75 } });

    // Debounce fires
    vi.advanceTimersByTime(350);

    // Simulate stale WebSocket push
    hubState.deviceState = { ...hubState.deviceState, fanSpeedPercent: 30 };
    rerender(<ControlScreen />);

    // Should still show user-set 75, not snap back to 30
    expect(screen.getByText("75")).toBeInTheDocument();

    vi.useRealTimers();
  });
});
