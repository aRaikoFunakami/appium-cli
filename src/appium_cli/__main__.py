"""Command-line entry point for appium-cli."""

from typing import Annotated

import typer

from appium_cli import __version__
from appium_cli.cli.devices import devices
from appium_cli.cli.doctor import doctor
from appium_cli.cli.install import install
from appium_cli.cli.server import app as server_app
from appium_cli.cli.session import app as session_app
from appium_cli.cli.tools import (
    activate_app,
    assert_visible,
    click_element,
    describe,
    double_tap,
    drag,
    find_by_text,
    find_element,
    find_container,
    fling,
    get_current_app,
    get_device_info,
    get_orientation,
    get_page_source,
    get_text,
    is_locked,
    long_press,
    list_apps,
    list_containers,
    pinch_close,
    pinch_open,
    press_key,
    press_keycode,
    restart_app,
    screenshot,
    scroll,
    scroll_element,
    scroll_to_element,
    set_orientation,
    send_keys,
    snapshot,
    swipe,
    tap,
    terminate_app,
    type_text,
    wait,
    wait_short_loading,
    within_container,
)


app = typer.Typer(
    help="CLI for Appium-based mobile automation by LLM agents.",
    no_args_is_help=True,
)
app.command(name="doctor")(doctor)
app.command(name="devices")(devices)
app.command(name="snapshot")(snapshot)
app.command(name="describe")(describe)
app.command(name="find_by_text")(find_by_text)
app.command(name="screenshot")(screenshot)
app.command(name="get_page_source")(get_page_source)
app.command(name="get_device_info")(get_device_info)
app.command(name="tap")(tap)
app.command(name="type_text")(type_text)
app.command(name="scroll")(scroll)
app.command(name="swipe")(swipe)
app.command(name="press_key")(press_key)
app.command(name="wait")(wait)
app.command(name="long_press")(long_press)
app.command(name="double_tap")(double_tap)
app.command(name="drag")(drag)
app.command(name="fling")(fling)
app.command(name="pinch_open")(pinch_open)
app.command(name="pinch_close")(pinch_close)
app.command(name="list_containers")(list_containers)
app.command(name="find_container")(find_container)
app.command(name="within_container")(within_container)
app.command(name="assert_visible")(assert_visible)
app.command(name="get_current_app")(get_current_app)
app.command(name="activate_app")(activate_app)
app.command(name="terminate_app")(terminate_app)
app.command(name="list_apps")(list_apps)
app.command(name="restart_app")(restart_app)
app.command(name="is_locked")(is_locked)
app.command(name="get_orientation")(get_orientation)
app.command(name="set_orientation")(set_orientation)
app.command(name="find_element")(find_element)
app.command(name="click_element")(click_element)
app.command(name="get_text")(get_text)
app.command(name="press_keycode")(press_keycode)
app.command(name="send_keys")(send_keys)
app.command(name="wait_short_loading")(wait_short_loading)
app.command(name="scroll_element")(scroll_element)
app.command(name="scroll_to_element")(scroll_to_element)
app.command(name="install")(install)
app.add_typer(server_app, name="server")
app.add_typer(session_app, name="session")


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit()


@app.callback()
def _main(
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            callback=_version_callback,
            is_eager=True,
            help="Show the appium-cli version and exit.",
        ),
    ] = False,
) -> None:
    """Run appium-cli."""


def main() -> None:
    app()


if __name__ == "__main__":
    main()
