import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

let hubState;

vi.mock("./hub", () => ({
  useHub: () => hubState,
}));

vi.mock("./api", () => ({
  api: {
    getPrograms: vi.fn(() => Promise.resolve([])),
    createProgram: vi.fn(() => Promise.resolve()),
    updateProgram: vi.fn(() => Promise.resolve()),
    deleteProgram: vi.fn(() => Promise.resolve()),
    activateProgram: vi.fn(() => Promise.resolve()),
    stopProgram: vi.fn(() => Promise.resolve()),
  },
}));

beforeEach(() => {
  vi.clearAllMocks();
  hubState = { activeProgram: null, unit: "fahrenheit" };
});

async function openEditor() {
  const mod = await import("./ProgramsScreen");
  const ProgramsScreen = mod.default;
  render(<ProgramsScreen />);
  await vi.waitFor(() =>
    expect(screen.getByText("+ Create Program")).toBeInTheDocument(),
  );
  fireEvent.click(screen.getByText("+ Create Program"));
}

async function enableSchedule() {
  fireEvent.click(screen.getByRole("button", { name: /schedule/i }));
}

describe("ProgramEditor", () => {
  it("start time is not shown by default (optional)", async () => {
    await openEditor();
    expect(screen.queryByLabelText("Start Time")).not.toBeInTheDocument();
  });

  it("clicking schedule toggle reveals start time selects (h / m / am-pm)", async () => {
    await openEditor();
    await enableSchedule();
    const hourSel = screen.getByLabelText("Hour");
    const minSel = screen.getByLabelText("Minute");
    const ampmSel = screen.getByLabelText("AM/PM");
    expect(hourSel.tagName).toBe("SELECT");
    expect(minSel.tagName).toBe("SELECT");
    expect(ampmSel.tagName).toBe("SELECT");
    expect(hourSel.options.length).toBe(12);
    expect(minSel.options.length).toBe(60);
    expect(ampmSel.options.length).toBe(2);
  });

  it("displays day-of-week buttons when schedule is enabled", async () => {
    await openEditor();
    await enableSchedule();
    for (const day of ["M", "T", "W", "T", "F", "S", "S"]) {
      expect(
        screen.getAllByRole("button", { name: day }).length,
      ).toBeGreaterThanOrEqual(1);
    }
  });

  it("day-of-week buttons are toggleable", async () => {
    await openEditor();
    await enableSchedule();
    const monButtons = screen.getAllByRole("button", { name: "M" });
    const monBtn = monButtons[0];
    fireEvent.click(monBtn);
    expect(monBtn.getAttribute("aria-pressed")).toBe("true");
    fireEvent.click(monBtn);
    expect(monBtn.getAttribute("aria-pressed")).toBe("false");
  });

  it("step does not have a mode picker", async () => {
    await openEditor();
    fireEvent.click(screen.getByText("+ Add Step"));
    expect(screen.queryAllByRole("button", { name: /Heat/i })).toHaveLength(0);
    expect(screen.queryAllByRole("button", { name: /Cool/i })).toHaveLength(0);
    expect(screen.queryAllByRole("button", { name: /Dry/i })).toHaveLength(0);
  });

  it("step temperature and fan speed are select dropdowns", async () => {
    await openEditor();
    fireEvent.click(screen.getByText("+ Add Step"));
    const tempSel = screen.getByLabelText(/TEMP/);
    const fanSel = screen.getByLabelText(/FAN/);
    expect(tempSel.tagName).toBe("SELECT");
    expect(fanSel.tagName).toBe("SELECT");
  });

  it("new step defaults to duration mode with a select dropdown", async () => {
    await openEditor();
    fireEvent.click(screen.getByText("+ Add Step"));
    const durSelect = screen.getByLabelText("Duration (mins)");
    expect(durSelect.tagName).toBe("SELECT");
    expect(screen.queryByLabelText("End Time")).not.toBeInTheDocument();
  });

  it("step has a timing mode toggle with 'for' and 'until' options", async () => {
    await openEditor();
    fireEvent.click(screen.getByText("+ Add Step"));
    expect(screen.getByRole("button", { name: "for" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "until" })).toBeInTheDocument();
  });

  it("switching to 'until' mode shows end time selects instead of duration", async () => {
    await openEditor();
    fireEvent.click(screen.getByText("+ Add Step"));
    fireEvent.click(screen.getByRole("button", { name: "until" }));
    expect(screen.getByLabelText("End Hour")).toBeInTheDocument();
    expect(screen.getByLabelText("End Minute")).toBeInTheDocument();
    expect(screen.getByLabelText("End AM/PM")).toBeInTheDocument();
    expect(screen.queryByLabelText("Duration (mins)")).not.toBeInTheDocument();
  });

  it("switching back to 'for' mode shows duration select", async () => {
    await openEditor();
    fireEvent.click(screen.getByText("+ Add Step"));
    fireEvent.click(screen.getByRole("button", { name: "until" }));
    fireEvent.click(screen.getByRole("button", { name: "for" }));
    const durSelect = screen.getByLabelText("Duration (mins)");
    expect(durSelect.tagName).toBe("SELECT");
    expect(screen.queryByLabelText("End Hour")).not.toBeInTheDocument();
  });

  it("duration step shows derived start time in header when scheduled", async () => {
    await openEditor();
    await enableSchedule();
    fireEvent.click(screen.getByText("+ Add Step"));
    expect(screen.getByText("10:00 PM →")).toBeInTheDocument();
  });

  it("second step start time derives from first step end", async () => {
    await openEditor();
    await enableSchedule();
    fireEvent.click(screen.getByText("+ Add Step"));
    fireEvent.change(screen.getByLabelText("Duration (mins)"), { target: { value: "60" } });
    fireEvent.click(screen.getByText("+ Add Step"));
    expect(screen.getByText("11:00 PM →")).toBeInTheDocument();
  });

  it("'until' step computes duration from start time to end time", async () => {
    await openEditor();
    await enableSchedule();
    fireEvent.click(screen.getByText("+ Add Step"));
    fireEvent.click(screen.getByRole("button", { name: "until" }));
    fireEvent.change(screen.getByLabelText("End Hour"), { target: { value: "11" } });
    fireEvent.change(screen.getByLabelText("End Minute"), { target: { value: "30" } });
    fireEvent.change(screen.getByLabelText("End AM/PM"), { target: { value: "PM" } });
    expect(screen.getByText("1h 30m")).toBeInTheDocument();
  });
});
