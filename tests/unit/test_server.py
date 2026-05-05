from appium_cli.cli import server


def _capture_start_command(monkeypatch, tmp_path, *, allow_adb_shell: bool = True, chromedriver_autodownload: bool = True) -> list[str]:
    commands: list[list[str]] = []

    class FakeProcess:
        pid = 456
        returncode = None

        def __init__(self, command: list[str], **kwargs) -> None:
            commands.append(command)

        def poll(self) -> None:
            return None

    monkeypatch.setattr("appium_cli.utils.paths.get_app_dir", lambda: tmp_path)
    monkeypatch.setattr(server, "get_status", lambda port: server.ServerState(False, "none", port, f"http://127.0.0.1:{port}"))
    monkeypatch.setattr(server, "which", lambda executable: "/usr/local/bin/appium")
    monkeypatch.setattr(server.subprocess, "Popen", FakeProcess)
    monkeypatch.setattr(server, "_server_responds", lambda port: True)

    server.start_server(4723, allow_adb_shell=allow_adb_shell, chromedriver_autodownload=chromedriver_autodownload)

    assert len(commands) == 1
    return commands[0]


def test_get_status_reports_external_when_port_responds_without_self_state(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("appium_cli.utils.paths.get_app_dir", lambda: tmp_path)
    monkeypatch.setattr(server, "_server_responds", lambda port: True)

    state = server.get_status(4723)

    assert state.running is True
    assert state.ownership == "external"
    assert state.port == 4723


def test_get_status_reports_self_when_saved_pid_is_running(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("appium_cli.utils.paths.get_app_dir", lambda: tmp_path)
    state_path = tmp_path / "server.json"
    state_path.write_text(
        '{"running": true, "ownership": "self", "port": 4723, "url": "http://127.0.0.1:4723", "pid": 123, "shell_capable": true}',
        encoding="utf-8",
    )
    monkeypatch.setattr(server, "_server_responds", lambda port: True)
    monkeypatch.setattr(server, "_pid_running", lambda pid: True)

    state = server.get_status(4723)

    assert state.running is True
    assert state.ownership == "self"
    assert state.pid == 123
    assert state.shell_capable is True


def test_start_server_enables_adb_shell_and_chromedriver_autodownload_by_default(monkeypatch, tmp_path) -> None:
    command = _capture_start_command(monkeypatch, tmp_path)

    assert command == [
        "/usr/local/bin/appium",
        "--port",
        "4723",
        "--allow-insecure",
        "uiautomator2:adb_shell,uiautomator2:chromedriver_autodownload",
    ]


def test_start_server_can_disable_adb_shell_without_disabling_chromedriver_autodownload(monkeypatch, tmp_path) -> None:
    command = _capture_start_command(monkeypatch, tmp_path, allow_adb_shell=False)

    assert command == [
        "/usr/local/bin/appium",
        "--port",
        "4723",
        "--allow-insecure",
        "uiautomator2:chromedriver_autodownload",
    ]


def test_start_server_can_disable_chromedriver_autodownload(monkeypatch, tmp_path) -> None:
    command = _capture_start_command(monkeypatch, tmp_path, chromedriver_autodownload=False)

    assert command == [
        "/usr/local/bin/appium",
        "--port",
        "4723",
        "--allow-insecure",
        "uiautomator2:adb_shell",
    ]
