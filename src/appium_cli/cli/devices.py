"""Device listing command."""

from __future__ import annotations

import json
from typing import Annotated, Literal

import typer

from appium_cli.utils import exit_codes
from appium_cli.utils.adb import list_android_devices
from appium_cli.utils.xcrun import list_ios_devices


Platform = Literal["all", "android", "ios"]


def _print_human(devices_data: list[dict[str, str]]) -> None:
    if not devices_data:
        typer.echo("No devices found.")
        return

    for item in devices_data:
        platform_name = item.get("platform", "unknown")
        udid = item.get("udid", "")
        status = item.get("status", "")
        model = item.get("model", "") or item.get("name", "")
        typer.echo(f"{platform_name}\t{udid}\t{status}\t{model}")


def devices(
    platform: Annotated[
        Platform,
        typer.Option("--platform", help="Device platform to list."),
    ] = "all",
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Print structured JSON output."),
    ] = False,
) -> None:
    """List connected Android/iOS devices without modifying the environment."""

    devices_data: list[dict[str, str]] = []
    errors: list[str] = []

    if platform in ("all", "android"):
        try:
            devices_data.extend(device.to_dict() for device in list_android_devices())
        except Exception as exc:
            errors.append(f"android: {exc}")

    if platform in ("all", "ios"):
        try:
            devices_data.extend(device.to_dict() for device in list_ios_devices())
        except Exception as exc:
            errors.append(f"ios: {exc}")

    if json_output:
        typer.echo(json.dumps({"ok": not errors, "devices": devices_data, "errors": errors}, indent=2))
    else:
        _print_human(devices_data)
        for error in errors:
            typer.echo(f"WARN: {error}", err=True)

    if errors and not devices_data:
        raise typer.Exit(exit_codes.GENERAL_ERROR)
