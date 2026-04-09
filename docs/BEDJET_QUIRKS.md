# BedJet Device Quirks

## 1. Scope

This document captures known device-level quirks, edge cases, and workarounds that the app must handle. These are behaviors that fall outside the normal command/response protocol but directly affect user experience and correctness.

## 2. Biorhythm Sequence Start-Time Rejection

### 2.1 Background

A biorhythm sequence is a multi-step sleep program. Each step defines:

- An operating mode
- A target temperature
- A fan speed
- A duration (or an end time)

Steps run in order across the night. For example:

1. Heat at 38 C, 60% fan for 30 minutes
2. Cool at 22 C, 40% fan for 2 hours
3. Off

The device has an internal clock. When a biorhythm is activated, the device evaluates the full sequence against its clock to determine whether the sequence can complete within the allowed runtime constraints.

### 2.2 The Quirk

If the sequence's configured start time has already passed according to the device clock, the device rejects the sequence entirely. It does not skip elapsed steps or resume partway through. It fails with one of the following notification errors:

- `BIO_FAIL_CLOCK_NOT_SET` (`4`): the device clock has not been set
- `BIO_FAIL_TOO_LONG` (`5`): the sequence contains steps that would exceed the allowed runtime from the current time

This means a sequence configured for a 10:00 PM start cannot be activated at 10:15 PM, even if most of the program is still ahead.

### 2.3 Required App Behavior

The app must not rely on the device to handle late starts. When the user activates a biorhythm and the nominal start time is in the past, the app must compute the correct mid-sequence state and program the device accordingly.

#### Step 1: Determine the delta

1. Read the current device clock (or use the system clock if the device clock has been synced).
2. Compute the elapsed time since the sequence's configured start time.

#### Step 2: Seek into the sequence

Walk the sequence steps in order, subtracting each step's duration from the elapsed delta:

```text
remaining_delta = now - sequence_start_time

for each step in sequence:
    if remaining_delta < step.duration:
        // This is the active step.
        // The step has been running for `remaining_delta`.
        // The step has `step.duration - remaining_delta` left.
        break
    else:
        remaining_delta -= step.duration

if remaining_delta >= total_sequence_duration:
    // The entire sequence has already elapsed. Do nothing.
```

#### Step 3: Apply the computed state

Once the active step and its remaining duration are known:

1. Set the operating mode to the active step's mode.
2. Set the target temperature to the active step's temperature.
3. Set the fan speed to the active step's fan speed.
4. Set the runtime remaining to the active step's remaining duration (BedJet 3 only).
5. If the active step is the last step and its remaining time is zero or negative, do not activate anything.

#### Step 4: Schedule subsequent steps

After applying the active step, the app must schedule the remaining steps in the sequence. For each subsequent step:

1. Compute the wall-clock time at which it should start.
2. Set a timer to apply that step's mode, temperature, fan speed, and runtime when the time arrives.

If the app is backgrounded or killed, these timers will not fire. The app should persist the active sequence and re-evaluate on resume using the same delta logic.

### 2.4 Clock Sync Dependency

This workaround depends on knowing the correct device time. The app should:

- Sync the device clock on every connect using `syncClock()`.
- Use the system clock as the reference for all delta calculations after sync.
- If the device clock cannot be synced (e.g. on BedJet V2 where `syncClock` is not documented), fall back to the system clock and accept that drift may occur.

### 2.5 Edge Cases

#### Sequence has fully elapsed

If `now` is past the end of the last step, the app should not activate anything. Optionally notify the user that the sequence window has passed.

#### Sequence starts in the future

If the start time is in the future, the app should schedule activation for the start time rather than activating immediately. Alternatively, the app can send the activation command directly to the device since the device will accept future-start sequences.

#### Device clock drift

If the device clock drifts relative to the system clock between syncs, the computed delta will be slightly wrong. This is acceptable for sleep sequences where steps are typically 15+ minutes long. The app should re-sync the clock on each connect to minimize drift.

#### App is killed mid-sequence

If the app is terminated while a sequence is running, the device will continue executing whatever mode/temperature/runtime was last set. The remaining scheduled steps will not fire. On next app launch, the app should detect whether a sequence was active, recompute the delta, and resume from the correct step.

#### Step duration is zero

A step with zero duration should be skipped entirely during the seek calculation.

## 3. Single BLE Connection Limit

The device allows only one active Bluetooth connection at a time. If another client (the official BedJet app, Home Assistant, or another instance of this app) is connected, the connection attempt will fail.

The app should:

- Detect connection failure and present a clear message: another client may be connected.
- Advise the user to close other BedJet apps or integrations.
- Retry connection after a short delay in case the other client disconnects.

## 4. BedJet V2 Mode Toggle Semantics

On BedJet V2, mode buttons are toggles rather than explicit set commands. Sending the Heat button while already in Heat mode turns the device off instead of being a no-op.

The app must:

- Track the current mode from the latest notification.
- Before sending a mode button, check whether the device is already in the target mode.
- If the device is already in the target mode (and it is not Turbo), skip the command.
- For `STANDBY`, send the button corresponding to the currently active mode to toggle it off.
- Never send a mode button without knowing the current state, or the device may end up in the opposite state from what was intended.

## 5. BedJet V2 Fan Command State Embedding

On BedJet V2, the fan speed command carries the full device context: mode, temperature, mute state, and remaining runtime. If any of these fields are wrong, the device will apply the incorrect values from the command payload, silently overwriting the actual state.

The app must:

- Always read the current state before constructing a V2 fan command.
- Never cache stale state for use in fan command construction.
- Treat the V2 fan command as a full-state write, not a single-field update.

## 6. Temperature and End-Time Jitter

The device sends frequent notifications with small fluctuations in temperature and computed end time. Without suppression, these cause excessive UI updates and a flickering display.

The app must implement jitter suppression as specified in the protocol spec (section `10.8`). The key thresholds are:

- Temperature: suppress updates smaller than `1.0 C` unless `15 seconds` have passed.
- End time: suppress updates smaller than `5 seconds` of shift.
