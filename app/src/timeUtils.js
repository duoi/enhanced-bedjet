/**
 * Time-of-day scheduling utilities for biorhythm program steps.
 * All "time" values are HH:MM strings; internally converted to
 * minutes-since-midnight for arithmetic. Midnight crossing is
 * handled by treating times that appear to go backwards as
 * wrapping into the next day.
 */

/** Parse "HH:MM" → minutes since midnight. */
export function timeToMinutes(hhmm) {
  const [h, m] = hhmm.split(":").map(Number);
  return h * 60 + m;
}

/** Format minutes since midnight → "HH:MM". Wraps past 24h. */
export function minutesToTime(totalMinutes) {
  const wrapped = ((totalMinutes % 1440) + 1440) % 1440;
  const h = Math.floor(wrapped / 60);
  const m = wrapped % 60;
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`;
}

/**
 * Compute duration in minutes from a start time to an end time,
 * accounting for midnight crossing. If end <= start, assumes
 * the end is the next day.
 */
export function computeDurationMinutes(startMinutes, endMinutes) {
  if (endMinutes > startMinutes) return endMinutes - startMinutes;
  return 1440 - startMinutes + endMinutes;
}

/**
 * Given a program start time and an array of steps (with durationMinutes),
 * compute the derived start/end times for each step.
 * Returns a new array with { ...step, startTime, endTime }.
 */
export function computeStepTimes(programStartTime, steps) {
  let cursor = timeToMinutes(programStartTime);
  return steps.map((step) => {
    const startTime = minutesToTime(cursor);
    cursor = (cursor + (step.durationMinutes || 0)) % 1440;
    const endTime = minutesToTime(cursor);
    return { ...step, startTime, endTime };
  });
}

/**
 * Given a program start time and an array of step end times,
 * compute the durationMinutes for each step.
 * Returns a new array of durationMinutes values.
 */
export function endTimesToDurations(programStartTime, endTimes) {
  let cursor = timeToMinutes(programStartTime);
  return endTimes.map((endTime) => {
    const endMin = timeToMinutes(endTime);
    const duration = computeDurationMinutes(cursor, endMin);
    cursor = endMin;
    return duration;
  });
}

/**
 * Compute the earliest allowed end time for a step, given its
 * computed start time. This is start + 1 minute.
 */
export function earliestEndTime(startTime) {
  return minutesToTime(timeToMinutes(startTime) + 1);
}

/**
 * Validate step timing. Returns an array of error strings (empty = valid).
 * Checks:
 * - Each step must have a positive duration (end > start after wrapping)
 * - Total program duration must not exceed 24 hours
 */
export function validateStepTimes(programStartTime, steps) {
  const errors = [];
  const timed = computeStepTimes(programStartTime, steps);
  let totalMinutes = 0;

  for (let i = 0; i < timed.length; i++) {
    const dur = steps[i].durationMinutes || 0;
    if (dur <= 0) {
      errors.push(`Step ${i + 1} must have a positive duration.`);
    }
    totalMinutes += dur;
  }

  if (totalMinutes > 1440) {
    errors.push("Total program duration exceeds 24 hours.");
  }

  return errors;
}
