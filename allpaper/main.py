"""
scriptable per-monitor wallpaper setter for Linux Mint / Cinnamon (X11) with both GUI and CLI interfaces
Copyright (C) 2026  Travis L. Seymour, PhD

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""

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
from typing import Optional

import typer
from PIL import Image

"""
wallpaper - a simple, scriptable per-monitor wallpaper setter for Linux Mint /
Cinnamon (X11) with LightDM (slick-greeter) login-screen support.

Usage:
    wallpaper FILENAME MONITOR [--mode stretch|center|tile|fill]

    FILENAME   path to an image file
    MONITOR    integer: 1, 2, 3, ... for real monitors (as ordered by
               `xrandr --listmonitors`), or 0 for the LightDM login screen.

How it works
------------
Cinnamon does not support different wallpapers per monitor out of the box.
To work around this (the same trick nitrogen/hydrapaper use), this script:

  1. Copies your chosen image to ~/.config/wallpaper/wallpaper_<N> so it
     survives the source file being moved/deleted.
  2. Remembers the mode + image for each monitor, keyed by its xrandr
     *output name* (e.g. "DP-1", "HDMI-1") rather than its positional
     index - so a saved wallpaper stays attached to the correct physical
     screen even if plugging/unplugging displays changes xrandr's
     numbering later. The MONITOR number you type on the command line is
     just resolved to "whichever output is currently in that position",
     at the moment you run the command.
  3. Re-reads your current monitor layout via `xrandr --listmonitors` and
     stitches a single combined image the size of your whole virtual
     screen, placing each monitor's wallpaper in its correct region.
  4. Sets that combined image as the desktop background via gsettings with
     picture-options=spanned (Cinnamon's multi-monitor mode).

Monitor 0 is treated specially: instead of touching your desktop
background, it updates /etc/lightdm/slick-greeter.conf so the LightDM
greeter uses that image. This requires root - run that specific command
with sudo.

Because this script uses a `uv run` shebang, and `sudo` resets PATH to a
fixed list that usually doesn't include wherever `uv` is installed (e.g.
~/.local/bin), plain `sudo wallpaper ...` will often fail with something
like `/usr/bin/env: 'uv': No such file or directory`. Carry your PATH
through explicitly instead:

    sudo env "PATH=$PATH" /path/to/wallpaper --mode stretch FILENAME 0

(Alternatively, symlink `uv` into a directory root already trusts, e.g.
`sudo ln -s "$(which uv)" /usr/local/bin/uv`, and plain `sudo wallpaper ...`
will work from then on.)

Re-applying at login
---------------------
gsettings values persist across reboots on their own, so you don't need to
re-run anything just to keep your wallpaper. But if your monitor geometry
changes between boots (e.g. a laptop dock, or a display reconnecting at a
different resolution), the saved spanned canvas can go stale. Add this to
Cinnamon's Startup Applications to rebuild and reapply it from your saved
per-output state on every login (no filename/monitor needed, no sudo):

    wallpaper --regenerate
"""

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


app = typer.Typer(add_completion=False)


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
        typer.secho("Error: xrandr not found. This tool requires X11.", fg="red")
        raise typer.Exit(1)
    except subprocess.CalledProcessError as e:
        typer.secho(f"Error running xrandr: {e.stderr}", fg="red")
        raise typer.Exit(1)

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
        typer.secho("Error: could not parse any monitors from xrandr.", fg="red")
        raise typer.Exit(1)
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
        typer.secho(
            "Setting the login screen background requires root.\n"
            "Re-run this command with sudo, carrying your PATH through so "
            "`uv` can still be found, e.g.:\n"
            f'  sudo env "PATH=$PATH" {sys.argv[0]} {img_path} 0',
            fg="red",
        )
        raise typer.Exit(1)

    if not SLICK_GREETER_CONF.parent.exists():
        typer.secho(
            f"Error: {SLICK_GREETER_CONF.parent} does not exist. Is LightDM installed?",
            fg="red",
        )
        raise typer.Exit(1)

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

    typer.secho(f"Updated {SLICK_GREETER_CONF} for the login screen.", fg="green")


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


@app.command()
def main(
    filename: Optional[Path] = typer.Argument(None, exists=True, readable=True, help="Image file to use."),
    monitor: Optional[int] = typer.Argument(None, help="Monitor number (1,2,3,...) or 0 for the login screen."),
    mode: Mode = typer.Option(Mode.fill, "--mode", help="How to fit the image to the screen."),
    regenerate: bool = typer.Option(
        False,
        "--regenerate",
        help=(
            "Rebuild and reapply the spanned wallpaper from saved per-output "
            "state, without changing any monitor's image. Takes no FILENAME "
            "or MONITOR. Intended for use in a startup script."
        ),
    ),
    gui: bool = typer.Option(False, "--gui", help="Launch the graphical user interface."),
):
    """Set the wallpaper for MONITOR to FILENAME, or rebuild with --regenerate, or launch GUI."""
    # Launch GUI if --gui flag or no arguments provided
    if gui or (filename is None and monitor is None and not regenerate):
        try:
            from allpaper.gui import launch_gui

            launch_gui()
        except ImportError as e:
            typer.secho(f"Error: GUI dependencies not available: {e}\nMake sure PySide6 is installed.", fg="red")
            raise typer.Exit(1)
        return

    if regenerate:
        if filename is not None or monitor is not None:
            typer.secho("--regenerate takes no FILENAME or MONITOR argument.", fg="red")
            raise typer.Exit(1)
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        regenerate_spanned()
        apply_spanned_via_gsettings()
        typer.secho("Reapplied wallpaper from saved state.", fg="green")
        return

    if filename is None or monitor is None:
        typer.secho("Usage: wallpaper FILENAME MONITOR [--mode ...]", fg="red")
        raise typer.Exit(1)

    if monitor < 0:
        typer.secho("MONITOR must be 0 or a positive integer.", fg="red")
        raise typer.Exit(1)

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
        typer.secho(
            f"Monitor {monitor} not found. xrandr currently reports {len(monitors)} monitor(s) (1-{len(monitors)}).",
            fg="red",
        )
        raise typer.Exit(1)
    output_name = monitors[monitor - 1]["name"]

    # Update state (keyed by output name) and rebuild the multi-monitor canvas.
    state = load_state()
    state[output_name] = {"file": dest_name, "mode": mode.value}
    save_state(state)

    regenerate_spanned()
    apply_spanned_via_gsettings()

    typer.secho(
        f"Set monitor {monitor} ({output_name}) wallpaper to {filename.name} (mode={mode.value}).",
        fg="green",
    )


if __name__ == "__main__":
    app()
