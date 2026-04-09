import { describe, it, expect } from "vitest";
import {
  timeToMinutes,
  minutesToTime,
  computeDurationMinutes,
  computeStepTimes,
  endTimesToDurations,
  earliestEndTime,
  validateStepTimes,
} from "./timeUtils";

describe("timeToMinutes", () => {
  it("converts midnight", () => {
    expect(timeToMinutes("00:00")).toBe(0);
  });

  it("converts noon", () => {
    expect(timeToMinutes("12:00")).toBe(720);
  });

  it("converts 22:30", () => {
    expect(timeToMinutes("22:30")).toBe(1350);
  });

  it("converts 23:59", () => {
    expect(timeToMinutes("23:59")).toBe(1439);
  });
});

describe("minutesToTime", () => {
  it("formats midnight", () => {
    expect(minutesToTime(0)).toBe("00:00");
  });

  it("formats noon", () => {
    expect(minutesToTime(720)).toBe("12:00");
  });

  it("formats 22:30", () => {
    expect(minutesToTime(1350)).toBe("22:30");
  });

  it("wraps past 24h", () => {
    expect(minutesToTime(1500)).toBe("01:00");
  });

  it("handles negative values", () => {
    expect(minutesToTime(-60)).toBe("23:00");
  });
});

describe("computeDurationMinutes", () => {
  it("computes simple forward duration", () => {
    expect(computeDurationMinutes(1320, 1350)).toBe(30);
  });

  it("computes duration crossing midnight", () => {
    expect(computeDurationMinutes(1410, 60)).toBe(90);
  });

  it("computes full day when start equals end", () => {
    expect(computeDurationMinutes(720, 720)).toBe(1440);
  });

  it("computes 23:00 to 07:00 as 8 hours", () => {
    expect(computeDurationMinutes(1380, 420)).toBe(480);
  });
});

describe("computeStepTimes", () => {
  it("computes times for a simple evening program", () => {
    const steps = [
      { mode: "heat", durationMinutes: 30 },
      { mode: "cool", durationMinutes: 120 },
      { mode: "standby", durationMinutes: 0 },
    ];
    const result = computeStepTimes("22:00", steps);
    expect(result[0].startTime).toBe("22:00");
    expect(result[0].endTime).toBe("22:30");
    expect(result[1].startTime).toBe("22:30");
    expect(result[1].endTime).toBe("00:30");
    expect(result[2].startTime).toBe("00:30");
    expect(result[2].endTime).toBe("00:30");
  });

  it("handles midnight crossing", () => {
    const steps = [{ mode: "heat", durationMinutes: 120 }];
    const result = computeStepTimes("23:00", steps);
    expect(result[0].startTime).toBe("23:00");
    expect(result[0].endTime).toBe("01:00");
  });
});

describe("endTimesToDurations", () => {
  it("converts end times to durations for simple case", () => {
    const durations = endTimesToDurations("22:00", ["22:30", "00:30"]);
    expect(durations).toEqual([30, 120]);
  });

  it("handles midnight crossing", () => {
    const durations = endTimesToDurations("23:00", ["01:00"]);
    expect(durations).toEqual([120]);
  });

  it("handles full overnight program", () => {
    const durations = endTimesToDurations("22:00", ["23:00", "02:00", "07:00"]);
    expect(durations).toEqual([60, 180, 300]);
  });
});

describe("earliestEndTime", () => {
  it("returns start + 1 minute", () => {
    expect(earliestEndTime("22:30")).toBe("22:31");
  });

  it("wraps past midnight", () => {
    expect(earliestEndTime("23:59")).toBe("00:00");
  });
});

describe("validateStepTimes", () => {
  it("returns no errors for a valid program", () => {
    const steps = [
      { mode: "heat", durationMinutes: 30 },
      { mode: "cool", durationMinutes: 120 },
    ];
    expect(validateStepTimes("22:00", steps)).toEqual([]);
  });

  it("returns error for zero-duration step", () => {
    const steps = [{ mode: "heat", durationMinutes: 0 }];
    const errors = validateStepTimes("22:00", steps);
    expect(errors.length).toBe(1);
    expect(errors[0]).toMatch(/step 1/i);
  });

  it("returns error when total exceeds 24 hours", () => {
    const steps = [
      { mode: "heat", durationMinutes: 800 },
      { mode: "cool", durationMinutes: 800 },
    ];
    const errors = validateStepTimes("22:00", steps);
    expect(errors.some((e) => /24 hours/i.test(e))).toBe(true);
  });
});
