from bedjet_hub.ble.const import (
    BEDJET3_SERVICE_UUID,
    STATUS_NOTIFICATION_LENGTH_V2,
    STATUS_NOTIFICATION_LENGTH_V3,
    STATUS_READ_LENGTH_V3,
    V2_WAKE_PACKET,
    ButtonCode,
    NotificationType,
    OperatingMode,
)


def test_modes():
    assert OperatingMode.STANDBY == 0
    assert OperatingMode.HEAT == 1
    assert OperatingMode.COOL == 4


def test_notifications():
    assert NotificationType.NONE == 0
    assert NotificationType.CLEAN_FILTER == 1


def test_buttons():
    assert ButtonCode.OFF == 0x01
    assert ButtonCode.HEAT == 0x03
    assert ButtonCode.LED_ON == 0x46


def test_uuids():
    assert BEDJET3_SERVICE_UUID == "00001000-bed0-0080-aa55-4265644a6574"


def test_lengths():
    assert STATUS_NOTIFICATION_LENGTH_V3 == 20
    assert STATUS_READ_LENGTH_V3 == 11
    assert STATUS_NOTIFICATION_LENGTH_V2 == 14


def test_wake():
    assert bytes([0x58, 0x01, 0x0B, 0x9B]) == V2_WAKE_PACKET
