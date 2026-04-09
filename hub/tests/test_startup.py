import logging
from unittest.mock import AsyncMock

import bedjet_hub.__main__ as startup_mod


async def test_startup_connect_logs_errors(caplog):
    """The startup connection loop must log each failed BLE attempt."""
    mock_ble = AsyncMock()
    mock_ble.connect = AsyncMock(side_effect=OSError("Device not found"))

    with caplog.at_level(logging.WARNING, logger="bedjet_hub.__main__"):
        result = await startup_mod.try_initial_connect(mock_ble, max_attempts=3)

    assert result is False
    assert any("Device not found" in r.message for r in caplog.records)


async def test_startup_connect_succeeds_on_retry(caplog):
    """The startup loop should return True on the first successful attempt."""
    call_count = 0

    async def flaky():
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise OSError("busy")

    mock_ble = AsyncMock()
    mock_ble.connect = flaky

    result = await startup_mod.try_initial_connect(mock_ble, max_attempts=5)

    assert result is True
    assert call_count == 3
