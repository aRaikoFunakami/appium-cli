from appium_cli.cli import server


def test_get_status_reports_external_when_port_responds_without_self_state(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(server, "SERVER_STATE_PATH", tmp_path / "server.json")
    monkeypatch.setattr(server, "_server_responds", lambda port: True)

    state = server.get_status(4723)

    assert state.running is True
    assert state.ownership == "external"
    assert state.port == 4723


def test_get_status_reports_self_when_saved_pid_is_running(monkeypatch, tmp_path) -> None:
    state_path = tmp_path / "server.json"
    state_path.write_text(
        '{"running": true, "ownership": "self", "port": 4723, "url": "http://127.0.0.1:4723", "pid": 123, "shell_capable": true}',
        encoding="utf-8",
    )
    monkeypatch.setattr(server, "SERVER_STATE_PATH", state_path)
    monkeypatch.setattr(server, "_server_responds", lambda port: True)
    monkeypatch.setattr(server, "_pid_running", lambda pid: True)

    state = server.get_status(4723)

    assert state.running is True
    assert state.ownership == "self"
    assert state.pid == 123
    assert state.shell_capable is True
