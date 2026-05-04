from appium_cli.utils.adb import parse_adb_devices


def test_parse_adb_devices_l_output() -> None:
    output = """List of devices attached
emulator-5554 device product:sdk_gtablet_arm64 model:Pixel_Tablet device:emu64a transport_id:3
abc123 unauthorized usb:338690048X transport_id:4
"""

    devices = parse_adb_devices(output)

    assert len(devices) == 2
    assert devices[0].udid == "emulator-5554"
    assert devices[0].status == "device"
    assert devices[0].model == "Pixel_Tablet"
    assert devices[0].product == "sdk_gtablet_arm64"
    assert devices[1].status == "unauthorized"


def test_parse_adb_devices_empty() -> None:
    assert parse_adb_devices("List of devices attached\n\n") == []
