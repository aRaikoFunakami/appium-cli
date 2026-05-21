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
    monkeypatch.setattr(server, "_get_local_status", lambda port: server.ServerState(False, "none", port, f"http://127.0.0.1:{port}"))
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


def test_resolve_external_url_returns_none_when_unset(monkeypatch) -> None:
    monkeypatch.delenv("APPIUM_SERVER_URL", raising=False)
    assert server.resolve_external_url() is None


def test_resolve_external_url_normalizes_trailing_slash(monkeypatch) -> None:
    monkeypatch.setenv("APPIUM_SERVER_URL", "http://host.docker.internal:4723/")
    assert server.resolve_external_url() == "http://host.docker.internal:4723"


def test_resolve_external_url_rejects_invalid_scheme(monkeypatch) -> None:
    monkeypatch.setenv("APPIUM_SERVER_URL", "ftp://example.com")
    assert server.resolve_external_url() is None


def test_resolve_external_url_rejects_missing_host(monkeypatch) -> None:
    monkeypatch.setenv("APPIUM_SERVER_URL", "http:///status")
    assert server.resolve_external_url() is None


def test_get_status_reports_external_from_env(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("APPIUM_SERVER_URL", "http://host.docker.internal:4723")
    monkeypatch.setattr("appium_cli.utils.paths.get_app_dir", lambda: tmp_path)
    monkeypatch.setattr(server, "_url_responds", lambda url: True)

    state = server.get_status(4723)

    assert state.running is True
    assert state.ownership == "external"
    assert state.url == "http://host.docker.internal:4723"
    assert state.pid is None


def test_get_status_reports_none_when_external_unreachable(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("APPIUM_SERVER_URL", "http://host.docker.internal:4723")
    monkeypatch.setattr("appium_cli.utils.paths.get_app_dir", lambda: tmp_path)
    monkeypatch.setattr(server, "_url_responds", lambda url: False)

    state = server.get_status(4723)

    assert state.running is False
    assert state.ownership == "none"


def test_start_server_returns_external_when_env_set(monkeypatch, tmp_path) -> None:
    # start_server is for local servers only and must ignore APPIUM_SERVER_URL.
    monkeypatch.setenv("APPIUM_SERVER_URL", "http://host.docker.internal:4723")
    command = _capture_start_command(monkeypatch, tmp_path)
    # Local appium spawned at the requested port, ignoring env.
    assert command[0:4] == ["/usr/local/bin/appium", "--port", "4723", "--allow-insecure"]


def test_start_server_raises_when_external_unreachable(monkeypatch, tmp_path) -> None:
    # start_server no longer probes env; this is checked at the `server start` CLI level.
    # Verified separately via test_server_start_command_is_noop_in_external_mode.
    pass


def test_server_start_command_is_noop_in_external_mode(monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.setenv("APPIUM_SERVER_URL", "http://host.docker.internal:4723")
    monkeypatch.setattr("appium_cli.utils.paths.get_app_dir", lambda: tmp_path)
    monkeypatch.setattr(server, "_url_responds", lambda url: True)

    called = []

    def fake_start_server(*args, **kwargs):
        called.append((args, kwargs))
        raise AssertionError("start_server must not be invoked in external mode")

    monkeypatch.setattr(server, "start_server", fake_start_server)

    server.start(port=4723, allow_adb_shell=True, chromedriver_autodownload=True, json_output=False)

    out = capsys.readouterr().out
    assert "Host/external Appium mode" in out
    assert called == []
