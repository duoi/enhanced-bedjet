import logging
from unittest.mock import AsyncMock

import bedjet_hub.__main__ as startup_mod


async def test_startup_connect_success(caplog):
    """try_initial_connect returns True when connect() succeeds.

    With establish_connection handling internal retries, the startup
    function is a single-call wrapper.
    """
    mock_ble = AsyncMock()
    mock_ble.connect = AsyncMock()

    result = await startup_mod.try_initial_connect(mock_ble)

    assert result is True
    mock_ble.connect.assert_awaited_once()


async def test_startup_connect_logs_failure(caplog):
    """try_initial_connect returns False and logs when connect() raises."""
    mock_ble = AsyncMock()
    mock_ble.connect = AsyncMock(side_effect=OSError("Device not found"))

    with caplog.at_level(logging.WARNING, logger="bedjet_hub.__main__"):
        result = await startup_mod.try_initial_connect(mock_ble)

    assert result is False
    assert any("Device not found" in r.message for r in caplog.records)


async def test_startup_connect_handles_typed_exceptions(caplog):
    """try_initial_connect should handle bleak-retry-connector exceptions."""
    from bleak_retry_connector import BleakNotFoundError

    mock_ble = AsyncMock()
    mock_ble.connect = AsyncMock(side_effect=BleakNotFoundError())

    with caplog.at_level(logging.WARNING, logger="bedjet_hub.__main__"):
        result = await startup_mod.try_initial_connect(mock_ble)

    assert result is False
