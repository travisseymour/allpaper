# AllPaper

A simple, scriptable per-monitor wallpaper setter for Linux Mint / Cinnamon (X11) with both GUI and CLI interfaces. Supports LightDM (slick-greeter) login screen backgrounds.

---

> <b>AI NOTICE</b>: 

>This project was almost entirely coded by Claude based on this prompt:

> main.py is taken from a my terminal script that works perfectly as written. However, I want to turn this into a app that I will deploy via `uv tool install` from github. It should be able to continue to be used as a command-line tool as it currently is using the name allpaper. However, if allpaper is run (no arguments supported) or perhaps allpaper-gui is called, then a pyside gui should be launched. the gui should resemble the mockup in allpaper_gui_idea.png. On startup, show the current configuration. The number of displays along the bottom will obviously depend on the displays available on the system. if one of the images is double clicked, a file-open dialog should be opened limited to standard image types. the user can also drag and drop images onto each display box. if the APPLY button is clicked, then these choices are added to the system.

> This tool was written for my own use (after being annoyed at how inconsistently hydraper and nitrogen worked on my system), and it works as intended for me. Your mileage may vary. Like any code, I would recommend you read it carefully before running it on your system.

---

## Overview

### What is AllPaper

AllPaper solves a common problem in Linux Mint / Cinnamon: the inability to set different wallpapers for different monitors out of the box. It provides:

- **Graphical Interface**: Easy-to-use dark-themed GUI for visual wallpaper management
- **Command-Line Interface**: Scriptable CLI for automation and advanced users
- **Per-Monitor Wallpapers**: Set different wallpapers for each connected display
- **Login Screen Support**: Update the LightDM greeter background
- **Persistent Configuration**: Wallpapers survive reboots and monitor reconnections
- **Multiple Display Modes**: Fill, Stretch, Center, or Tile modes for each monitor

### How It Works

Cinnamon doesn't support different wallpapers per monitor natively. AllPaper works around this by:

1. Saving your chosen images to `~/.config/wallpaper/` so they persist even if source files are moved/deleted
2. Remembering each monitor's wallpaper by its xrandr output name (e.g., "DP-1", "HDMI-1"), not position - so wallpapers stay with the correct physical screen even if displays are plugged/unplugged
3. Stitching a single combined image sized to your entire virtual screen, placing each monitor's wallpaper in its correct region
4. Setting that combined image as the desktop background via `gsettings` with `picture-options=spanned`

For the login screen (monitor 0), it directly updates `/etc/lightdm/slick-greeter.conf`, which requires root privileges.

### Features

- **Dual Interface**: Choose between GUI (drag-and-drop) or CLI (scriptable)
- **Auto-Detection**: Automatically detects all connected monitors
- **Drag and Drop**: Simply drag images onto monitor boxes in the GUI
- **File Picker**: Double-click any monitor to browse for images
- **Mode Selection**: Fill, Stretch, Center, or Tile per monitor
- **Login Screen**: Set the LightDM greeter background (with automatic sudo handling)
- **State Persistence**: Wallpapers survive monitor reconnection and resolution changes
- **Startup Integration**: Can regenerate wallpapers on login via startup applications

---

## Getting Started

### Requirements

- Linux Mint / Cinnamon (X11)
- Python 3.11 or higher
- xrandr (typically pre-installed)
- LightDM with slick-greeter (for login screen support)

### Installing AllPaper

The recommended installation method uses `uv`, a fast Python package manager:

1. Install uv (if not already installed):

   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

2. Install AllPaper as a tool:

   ```bash
   uv tool install git+https://github.com/travisseymour/allpaper.git
   ```

**Note for Linux users**: If you encounter an xcb plugin error when running the GUI, install the required library:

```bash
sudo apt install libxcb-cursor0
```

### Uninstalling AllPaper

```bash
uv tool uninstall allpaper
```

---

## Usage

### GUI Mode

Launch the graphical interface using any of these methods:

```bash
allpaper              # No arguments - launches GUI
allpaper --gui        # Explicit GUI flag
allpaper-gui          # Dedicated GUI command
```

**Using the GUI:**

1. **Login Screen Section**: The top section shows the current login screen wallpaper
   - Double-click to select a new image
   - Or drag and drop an image onto the box
   - Choose a display mode (Fill, Stretch, Center, Tile)

2. **Monitor Sections**: Each connected display gets its own section
   - Double-click any monitor box to open a file picker
   - Or drag and drop images directly onto the box
   - Select the desired display mode for each monitor

3. **Apply Changes**: Click the "Apply" button to apply all wallpapers
   - If updating the login screen, you'll be prompted for your password
   - Monitor wallpapers are applied immediately

### CLI Mode

Set wallpapers from the command line for scripting and automation.

#### Basic Usage

```bash
allpaper FILENAME MONITOR [--mode MODE]
```

- `FILENAME`: Path to an image file
- `MONITOR`: Integer (1, 2, 3, ... for monitors, or 0 for login screen)
- `--mode`: Optional display mode (fill, stretch, center, tile) - defaults to fill

#### Monitor Numbering

Monitors are numbered according to `xrandr --listmonitors` output:
- Monitor 1, 2, 3, ... are your actual displays
- Monitor 0 is the LightDM login screen

To see your monitor layout:
```bash
xrandr --listmonitors
```

### Command-Line Options

```bash
allpaper FILENAME MONITOR [OPTIONS]

Options:
  --mode [fill|stretch|center|tile]  How to fit the image (default: fill)
  --regenerate                       Rebuild wallpaper from saved state
  --gui                              Launch the graphical interface
  --help                             Show help message
```

### Examples

**GUI Examples:**
```bash
# Launch GUI (any of these)
allpaper
allpaper --gui
allpaper-gui
```

**CLI Examples:**
```bash
# Set monitor 1 wallpaper with fill mode (default)
allpaper ~/Pictures/wallpaper1.jpg 1

# Set monitor 2 wallpaper with stretch mode
allpaper ~/Pictures/wallpaper2.jpg 2 --mode stretch

# Set monitor 3 wallpaper with tile mode
allpaper ~/Pictures/pattern.png 3 --mode tile

# Set login screen wallpaper (requires sudo)
sudo env "PATH=$PATH" allpaper ~/Pictures/login.jpg 0 --mode fill

# Rebuild wallpaper from saved state (useful in startup scripts)
allpaper --regenerate
```

### Startup Integration

To automatically reapply wallpapers when your monitor configuration changes (e.g., laptop docking/undocking), add this to Cinnamon's Startup Applications:

**Name:** AllPaper Restore
**Command:** `allpaper --regenerate`
**Delay:** 5 seconds

This regenerates the spanned wallpaper from your saved per-monitor state without requiring any arguments.

### Login Screen and Sudo

Setting the login screen wallpaper (monitor 0) requires root privileges because it modifies `/etc/lightdm/slick-greeter.conf`.

**Using the GUI:** The application will automatically prompt for your password when applying login screen changes.

**Using the CLI:** You need to use sudo with your PATH preserved (so `uv` can be found):

```bash
sudo env "PATH=$PATH" allpaper ~/Pictures/login.jpg 0
```

Alternatively, symlink `uv` to a location root trusts:
```bash
sudo ln -s "$(which uv)" /usr/local/bin/uv
```

Then you can use plain `sudo`:
```bash
sudo allpaper ~/Pictures/login.jpg 0
```

---

## Configuration Files

AllPaper stores its configuration in `~/.config/wallpaper/`:

- `state.json`: Maps each monitor output name to its wallpaper and mode
- `wallpaper_0.*`: Login screen wallpaper
- `wallpaper_1.*`: Monitor 1 wallpaper
- `wallpaper_2.*`: Monitor 2 wallpaper
- (etc. for additional monitors)
- `spanned.png`: The combined multi-monitor wallpaper image

---

## Troubleshooting

### xcb plugin error on Linux

If you see an error about Qt platform plugin "xcb", install the required dependency:

```bash
sudo apt install libxcb-cursor0
```

### "xrandr not found" error

Install xrandr (should be pre-installed on most systems):

```bash
sudo apt install x11-xserver-utils
```

### Wallpaper doesn't apply

1. Make sure you're running Cinnamon on X11 (not Wayland)
2. Check that gsettings is available
3. Verify your images are in a supported format (PNG, JPG, etc.)

### Login screen not updating

1. Ensure you provided your password when prompted (GUI mode)
2. Ensure you're using sudo correctly (CLI mode)
3. Verify LightDM and slick-greeter are installed
4. Check that `/etc/lightdm/slick-greeter.conf` is writable by root

### Monitor numbering changed

If you plug/unplug monitors and the numbering changes, don't worry! AllPaper saves wallpapers by output name (e.g., "DP-1"), not position. Just use the new monitor number in your command, or use the GUI which shows all connected monitors automatically.

---

## License

GNU General Public License v3 (GPLv3)

## Contributing

Issues and pull requests are welcome at [github.com/travisseymour/allpaper](https://github.com/travisseymour/allpaper)

## Author

Travis L. Seymour, PhD
