# SPDX-FileCopyrightText: Allpaper | Copyright (c) 2022 Travis L. Seymour, PhD <nogard@ucsc.edu>
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import configparser
import json
import os
import re
import shutil
import subprocess
import sys
from enum import Enum
from pathlib import Path
from typing import Annotated

import cyclopts
from PIL import Image
from rich import print as rprint

CONFIG_DIR = Path.home() / ".config" / "wallpaper"
STATE_FILE = CONFIG_DIR / "state.json"
SPANNED_FILE = CONFIG_DIR / "spanned.png"
SLICK_GREETER_CONF = Path("/etc/lightdm/slick-greeter.conf")

GSETTINGS_SCHEMA = "org.cinnamon.desktop.background"


class Mode(str, Enum):
    fill = "fill"  # scale to cover the monitor, cropping overflow (default)
    stretch = "stretch"  # scale to exact size, ignoring aspect ratio
    center = "center"  # original size, centered, cropped/padded as needed
    tile = "tile"  # repeat the image to fill the monitor


app = cyclopts.App(help="Set the wallpaper for MONITOR to FILENAME, or rebuild with --regenerate, or launch GUI.")


# --------------------------------------------------------------------------
# Monitor geometry
# --------------------------------------------------------------------------


def get_monitors() -> list[dict]:
    """Return monitors in the order `xrandr --listmonitors` reports them.

    Each entry: {"name": str, "width": int, "height": int, "x": int, "y": int}
    """
    try:
        out = subprocess.run(["xrandr", "--listmonitors"], capture_output=True, text=True, check=True).stdout
    except FileNotFoundError:
        rprint("[red]Error: xrandr not found. This tool requires X11.[/red]")
        sys.exit(1)
    except subprocess.CalledProcessError as e:
        rprint(f"[red]Error running xrandr: {e.stderr}[/red]")
        sys.exit(1)

    monitors = []
    # Example line: " 0: +*DP-1 1920/531x1080/299+0+0  DP-1"
    line_re = re.compile(r"^\s*\d+:\s+\S*\s+(\d+)/\d+x(\d+)/\d+\+(\d+)\+(\d+)\s+(\S+)")
    for line in out.splitlines():
        m = line_re.match(line)
        if not m:
            continue
        width, height, x, y, name = m.groups()
        monitors.append(
            {
                "name": name,
                "width": int(width),
                "height": int(height),
                "x": int(x),
                "y": int(y),
            }
        )
    if not monitors:
        rprint("[red]Error: could not parse any monitors from xrandr.[/red]")
        sys.exit(1)
    return monitors


# --------------------------------------------------------------------------
# State
# --------------------------------------------------------------------------


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2))


# --------------------------------------------------------------------------
# Image handling
# --------------------------------------------------------------------------


def fit_to_box(img: Image.Image, mode: Mode, box_w: int, box_h: int) -> Image.Image:
    """Return an RGB image exactly box_w x box_h, per the requested mode."""
    img = img.convert("RGB")

    if mode == Mode.stretch:
        return img.resize((box_w, box_h), Image.LANCZOS)

    if mode == Mode.center:
        canvas = Image.new("RGB", (box_w, box_h), "black")
        iw, ih = img.size
        # If the image is larger than the box, crop the center; otherwise
        # paste it centered on a black background.
        if iw > box_w or ih > box_h:
            left = max(0, (iw - box_w) // 2)
            top = max(0, (ih - box_h) // 2)
            img = img.crop((left, top, left + min(iw, box_w), top + min(ih, box_h)))
            iw, ih = img.size
        paste_x = (box_w - iw) // 2
        paste_y = (box_h - ih) // 2
        canvas.paste(img, (paste_x, paste_y))
        return canvas

    if mode == Mode.tile:
        canvas = Image.new("RGB", (box_w, box_h), "black")
        iw, ih = img.size
        for y in range(0, box_h, ih):
            for x in range(0, box_w, iw):
                canvas.paste(img, (x, y))
        return canvas

    # mode == Mode.fill (default): scale to cover, then center-crop
    iw, ih = img.size
    scale = max(box_w / iw, box_h / ih)
    new_w, new_h = round(iw * scale), round(ih * scale)
    img = img.resize((new_w, new_h), Image.LANCZOS)
    left = (new_w - box_w) // 2
    top = (new_h - box_h) // 2
    return img.crop((left, top, left + box_w, top + box_h))


def regenerate_spanned() -> None:
    """Rebuild the combined multi-monitor canvas from current state."""
    monitors = get_monitors()
    state = load_state()

    total_w = max(m["x"] + m["width"] for m in monitors)
    total_h = max(m["y"] + m["height"] for m in monitors)
    canvas = Image.new("RGB", (total_w, total_h), "black")

    for mon in monitors:
        entry = state.get(mon["name"])
        if not entry:
            continue
        img_path = CONFIG_DIR / entry["file"]
        if not img_path.exists():
            continue
        img = Image.open(img_path)
        tile = fit_to_box(img, Mode(entry["mode"]), mon["width"], mon["height"])
        canvas.paste(tile, (mon["x"], mon["y"]))

    canvas.save(SPANNED_FILE)


def apply_spanned_via_gsettings() -> None:
    uri = f"file://{SPANNED_FILE}"
    subprocess.run(["gsettings", "set", GSETTINGS_SCHEMA, "picture-uri", uri], check=True)
    subprocess.run(
        ["gsettings", "set", GSETTINGS_SCHEMA, "picture-options", "spanned"],
        check=True,
    )


# --------------------------------------------------------------------------
# Login screen (LightDM / slick-greeter)
# --------------------------------------------------------------------------


def set_login_screen_background(img_path: Path) -> None:
    if os.geteuid() != 0:
        rprint(
            "[red]Setting the login screen background requires root.\n"
            "Re-run this command with sudo, carrying your PATH through so "
            "`uv` can still be found, e.g.:\n"
            f'  sudo env "PATH=$PATH" {sys.argv[0]} {img_path} 0[/red]'
        )
        sys.exit(1)

    if not SLICK_GREETER_CONF.parent.exists():
        rprint(f"[red]Error: {SLICK_GREETER_CONF.parent} does not exist. Is LightDM installed?[/red]")
        sys.exit(1)

    config = configparser.ConfigParser()
    # slick-greeter.conf may not exist yet; ConfigParser handles missing files fine.
    if SLICK_GREETER_CONF.exists():
        config.read(SLICK_GREETER_CONF)

    if "Greeter" not in config:
        config["Greeter"] = {}

    config["Greeter"]["background"] = str(img_path)
    config["Greeter"]["draw-user-backgrounds"] = "false"

    with SLICK_GREETER_CONF.open("w") as f:
        config.write(f)

    rprint(f"[green]Updated {SLICK_GREETER_CONF} for the login screen.[/green]")


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


@app.default
def main(
    filename: Annotated[Path | None, cyclopts.Parameter(help="Image file to use.")] = None,
    monitor: Annotated[
        int | None, cyclopts.Parameter(help="Monitor number (1,2,3,...) or 0 for the login screen.")
    ] = None,
    *,
    mode: Annotated[Mode, cyclopts.Parameter(name="--mode", help="How to fit the image to the screen.")] = Mode.fill,
    regenerate: Annotated[
        bool,
        cyclopts.Parameter(
            name="--regenerate",
            help=(
                "Rebuild and reapply the spanned wallpaper from saved per-output "
                "state, without changing any monitor's image. Takes no FILENAME "
                "or MONITOR. Intended for use in a startup script."
            ),
        ),
    ] = False,
    gui: Annotated[bool, cyclopts.Parameter(name="--gui", help="Launch the graphical user interface.")] = False,
):
    # Launch GUI if --gui flag or no arguments provided
    if gui or (filename is None and monitor is None and not regenerate):
        try:
            from allpaper.gui import launch_gui

            launch_gui()
        except ImportError as e:
            rprint(f"[red]Error: GUI dependencies not available: {e}\nMake sure PySide6 is installed.[/red]")
            sys.exit(1)
        return

    if regenerate:
        if filename is not None or monitor is not None:
            rprint("[red]--regenerate takes no FILENAME or MONITOR argument.[/red]")
            sys.exit(1)
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        regenerate_spanned()
        apply_spanned_via_gsettings()
        rprint("[green]Reapplied wallpaper from saved state.[/green]")
        return

    if filename is None or monitor is None:
        rprint("[red]Usage: wallpaper FILENAME MONITOR [--mode ...][/red]")
        sys.exit(1)

    if monitor < 0:
        rprint("[red]MONITOR must be 0 or a positive integer.[/red]")
        sys.exit(1)

    # Validate file exists and is readable (previously handled by typer)
    if not filename.exists():
        rprint(f"[red]Error: File '{filename}' does not exist.[/red]")
        sys.exit(1)
    if not filename.is_file():
        rprint(f"[red]Error: '{filename}' is not a file.[/red]")
        sys.exit(1)

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    # Copy the source image into our persistent store, preserving extension.
    suffix = filename.suffix.lower() or ".png"
    dest_name = f"wallpaper_{monitor}{suffix}"
    dest_path = CONFIG_DIR / dest_name

    # Remove any stale copy with a different extension for this monitor.
    for old in CONFIG_DIR.glob(f"wallpaper_{monitor}.*"):
        if old.name != dest_name:
            old.unlink()

    # Only copy if source and destination are different files
    if not dest_path.exists() or not os.path.samefile(filename, dest_path):
        shutil.copy2(filename, dest_path)

    if monitor == 0:
        set_login_screen_background(dest_path)
        return

    # Resolve MONITOR (a position, e.g. "2") to the output name currently in
    # that position (e.g. "HDMI-1"), so the saved state stays tied to the
    # physical output rather than to a position that can shift later.
    monitors = get_monitors()
    if monitor < 1 or monitor > len(monitors):
        rprint(
            f"[red]Monitor {monitor} not found. xrandr currently reports {len(monitors)} monitor(s) (1-{len(monitors)}).[/red]"
        )
        sys.exit(1)
    output_name = monitors[monitor - 1]["name"]

    # Update state (keyed by output name) and rebuild the multi-monitor canvas.
    state = load_state()
    state[output_name] = {"file": dest_name, "mode": mode.value}
    save_state(state)

    regenerate_spanned()
    apply_spanned_via_gsettings()

    rprint(f"[green]Set monitor {monitor} ({output_name}) wallpaper to {filename.name} (mode={mode.value}).[/green]")


def cli():
    """Entry point for the CLI."""
    app()


if __name__ == "__main__":
    cli()
