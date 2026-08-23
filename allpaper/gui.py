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

import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QPixmap, QPalette, QColor
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
    QInputDialog,
    QLineEdit,
)

from allpaper.main import (
    CONFIG_DIR,
    Mode,
    get_monitors,
    load_state,
    set_login_screen_background,
    regenerate_spanned,
    apply_spanned_via_gsettings,
    save_state,
    SLICK_GREETER_CONF,
)


"""
PySide6 GUI for AllPaper wallpaper management.
"""


class ImageDropLabel(QLabel):
    """A QLabel that accepts image drops and double-clicks."""

    imageChanged = Signal(str)  # Emits the file path when image changes

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setMinimumSize(200, 150)
        self.setMaximumSize(400, 300)
        self.setScaledContents(True)
        self.setAlignment(Qt.AlignCenter)
        self._update_style()
        self.setText("Double-click or\ndrag image here")
        self._image_path: Optional[str] = None

    def _update_style(self):
        """Update stylesheet based on current palette (theme-aware)."""
        palette = self.palette()
        is_dark = palette.color(QPalette.Window).lightness() < 128

        if is_dark:
            border_color = "#555"
            hover_color = "#888"
            bg_color = "#2b2b2b"
            text_color = "#aaa"
        else:
            border_color = "#ccc"
            hover_color = "#999"
            bg_color = "#f5f5f5"
            text_color = "#666"

        self.setStyleSheet(f"""
            QLabel {{
                border: 2px solid {border_color};
                background-color: {bg_color};
                color: {text_color};
            }}
            QLabel:hover {{
                border: 2px solid {hover_color};
            }}
        """)

    def set_image(self, image_path: str | Path) -> None:
        """Set the displayed image."""
        self._image_path = str(image_path)
        if Path(image_path).exists():
            pixmap = QPixmap(str(image_path))
            if not pixmap.isNull():
                self.setPixmap(pixmap.scaled(self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
            else:
                self.setText("Invalid image")
        else:
            self.setText("Image not found")

    def get_image_path(self) -> Optional[str]:
        """Get the current image path."""
        return self._image_path

    def mouseDoubleClickEvent(self, event):
        """Open file dialog on double-click."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Wallpaper Image",
            str(Path.home()),
            "Images (*.png *.jpg *.jpeg *.bmp *.gif *.webp);;All Files (*)",
        )
        if file_path:
            self.set_image(file_path)
            self.imageChanged.emit(file_path)

    def dragEnterEvent(self, event: QDragEnterEvent):
        """Accept drag events with image files."""
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if len(urls) == 1:
                file_path = urls[0].toLocalFile()
                # Check if it's an image file
                valid_exts = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp"}
                if Path(file_path).suffix.lower() in valid_exts:
                    event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        """Handle dropped image files."""
        if event.mimeData().hasUrls():
            file_path = event.mimeData().urls()[0].toLocalFile()
            self.set_image(file_path)
            self.imageChanged.emit(file_path)


class MonitorSection(QWidget):
    """Widget for a single monitor or login screen configuration."""

    def __init__(self, title: str, monitor_number: int, parent=None):
        super().__init__(parent)
        self.monitor_number = monitor_number
        self._changed = False

        layout = QVBoxLayout(self)

        # Group box
        self.group = QGroupBox(title)
        self._update_group_style()
        group_layout = QVBoxLayout()

        # Image preview
        self.image_label = ImageDropLabel()
        self.image_label.imageChanged.connect(self._on_image_changed)
        group_layout.addWidget(self.image_label, alignment=Qt.AlignCenter)

        # Mode selector
        mode_layout = QHBoxLayout()
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["Fill", "Stretch", "Center", "Tile"])
        self.mode_combo.setCurrentText("Fill")
        self.mode_combo.currentTextChanged.connect(self._on_mode_changed)
        mode_layout.addStretch()
        mode_layout.addWidget(self.mode_combo)
        mode_layout.addStretch()
        group_layout.addLayout(mode_layout)

        self.group.setLayout(group_layout)
        layout.addWidget(self.group)

    def _update_group_style(self):
        """Update group box stylesheet based on current palette (theme-aware)."""
        palette = self.palette()
        is_dark = palette.color(QPalette.Window).lightness() < 128

        border_color = "#555" if is_dark else "#ccc"

        self.group.setStyleSheet(f"""
            QGroupBox {{
                font-weight: bold;
                border: 1px solid {border_color};
                margin-top: 10px;
                padding-top: 10px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }}
        """)

    def _on_image_changed(self, path: str):
        """Mark as changed when image is updated."""
        self._changed = True

    def _on_mode_changed(self, mode: str):
        """Mark as changed when mode is updated."""
        self._changed = True

    def has_changed(self) -> bool:
        """Check if this section has pending changes."""
        return self._changed

    def reset_changed(self):
        """Reset the changed flag."""
        self._changed = False

    def get_image_path(self) -> Optional[str]:
        """Get the selected image path."""
        return self.image_label.get_image_path()

    def get_mode(self) -> Mode:
        """Get the selected mode."""
        mode_map = {
            "Fill": Mode.fill,
            "Stretch": Mode.stretch,
            "Center": Mode.center,
            "Tile": Mode.tile,
        }
        return mode_map[self.mode_combo.currentText()]

    def set_current_wallpaper(self, image_path: str, mode: Mode):
        """Load the current wallpaper configuration."""
        self.image_label.set_image(image_path)
        mode_map = {
            Mode.fill: "Fill",
            Mode.stretch: "Stretch",
            Mode.center: "Center",
            Mode.tile: "Tile",
        }
        self.mode_combo.setCurrentText(mode_map[mode])
        self._changed = False


class AllPaperGUI(QMainWindow):
    """Main window for AllPaper GUI."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("All Paper v2026.10.1")
        self.setMinimumSize(800, 600)

        # Setup theme detection
        self._setup_theme()

        # Central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        # Login screen section
        self.login_section = MonitorSection("Login Screen", 0)
        main_layout.addWidget(self.login_section)

        # Monitor sections (dynamically created)
        self.monitor_sections: list[MonitorSection] = []
        monitors = get_monitors()

        # Create a horizontal layout for monitors
        monitors_layout = QHBoxLayout()
        for i, mon in enumerate(monitors, start=1):
            section = MonitorSection(f"Monitor {i}", i)
            section.monitor_number = i
            self.monitor_sections.append(section)
            monitors_layout.addWidget(section)

        main_layout.addLayout(monitors_layout)

        # Apply button
        apply_button = QPushButton("Apply")
        apply_button.setMinimumHeight(40)
        apply_button.setStyleSheet("""
            QPushButton {
                background-color: #0d7377;
                color: white;
                font-weight: bold;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #14afb8;
            }
            QPushButton:pressed {
                background-color: #0a5a5d;
            }
        """)
        apply_button.clicked.connect(self._on_apply_clicked)
        main_layout.addWidget(apply_button, alignment=Qt.AlignRight)

        # Load current configuration
        self._load_current_config()

    def _setup_theme(self):
        """Setup theme-aware styling based on system settings."""
        # Qt will automatically use system theme, we just need to detect if it's dark
        # to adjust our custom widget styles appropriately
        palette = self.palette()
        is_dark = palette.color(QPalette.Window).lightness() < 128

        # Store the theme state for custom widget styling
        self._is_dark_theme = is_dark

    def _load_current_config(self):
        """Load and display the current wallpaper configuration."""
        state = load_state()
        monitors = get_monitors()

        # Load login screen wallpaper (monitor 0)
        login_image = CONFIG_DIR / "wallpaper_0.png"
        for ext in [".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp"]:
            test_path = CONFIG_DIR / f"wallpaper_0{ext}"
            if test_path.exists():
                login_image = test_path
                break

        if login_image.exists():
            # Try to get mode from slick-greeter.conf or default to fill
            self.login_section.set_current_wallpaper(str(login_image), Mode.fill)

        # Load monitor wallpapers
        for i, (section, mon) in enumerate(zip(self.monitor_sections, monitors), start=1):
            output_name = mon["name"]
            if output_name in state:
                entry = state[output_name]
                img_path = CONFIG_DIR / entry["file"]
                if img_path.exists():
                    mode = Mode(entry["mode"])
                    section.set_current_wallpaper(str(img_path), mode)

    def _on_apply_clicked(self):
        """Apply the wallpaper changes."""
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)

            # Check if login screen needs to be updated
            login_needs_update = self.login_section.has_changed()
            login_image_path = self.login_section.get_image_path()

            if login_needs_update and login_image_path:
                # Check if we need sudo
                if os.geteuid() != 0:
                    password, ok = QInputDialog.getText(
                        self,
                        "Administrator Password Required",
                        "Setting the login screen requires administrator privileges.\nEnter your password:",
                        QLineEdit.Password,
                    )
                    if not ok or not password:
                        QMessageBox.warning(
                            self, "Cancelled", "Login screen update cancelled. Other changes will still be applied."
                        )
                        login_needs_update = False
                    else:
                        # Copy the image and update login screen with sudo
                        login_dest = CONFIG_DIR / "wallpaper_0.png"
                        import shutil

                        shutil.copy2(login_image_path, login_dest)

                        # Run sudo command to update slick-greeter.conf
                        cmd = [
                            "sudo",
                            "-S",
                            "python3",
                            "-c",
                            f"import configparser; "
                            f"from pathlib import Path; "
                            f"conf = Path('{SLICK_GREETER_CONF}'); "
                            f"config = configparser.ConfigParser(); "
                            f"conf.exists() and config.read(conf); "
                            f"'Greeter' not in config and config.add_section('Greeter'); "
                            f"config.set('Greeter', 'background', str('{login_dest}')); "
                            f"config.set('Greeter', 'draw-user-backgrounds', 'false'); "
                            f"config.write(conf.open('w'))",
                        ]

                        try:
                            proc = subprocess.Popen(
                                cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
                            )
                            stdout, stderr = proc.communicate(input=password + "\n", timeout=10)

                            if proc.returncode != 0:
                                raise Exception(f"Failed to update login screen: {stderr}")

                            self.login_section.reset_changed()
                        except subprocess.TimeoutExpired:
                            proc.kill()
                            raise Exception("Login screen update timed out")
                        except Exception as e:
                            QMessageBox.critical(self, "Error", f"Failed to update login screen: {str(e)}")
                            login_needs_update = False
                else:
                    # Already running as root
                    login_dest = CONFIG_DIR / "wallpaper_0.png"
                    import shutil

                    shutil.copy2(login_image_path, login_dest)
                    set_login_screen_background(login_dest)
                    self.login_section.reset_changed()

            # Update monitor wallpapers
            monitors = get_monitors()
            state = load_state()
            any_monitor_changed = False

            for section, mon in zip(self.monitor_sections, monitors):
                if section.has_changed():
                    image_path = section.get_image_path()
                    if image_path:
                        import shutil

                        # Copy image to config dir
                        suffix = Path(image_path).suffix.lower() or ".png"
                        dest_name = f"wallpaper_{section.monitor_number}{suffix}"
                        dest_path = CONFIG_DIR / dest_name

                        # Remove old copies with different extensions
                        for old in CONFIG_DIR.glob(f"wallpaper_{section.monitor_number}.*"):
                            if old.name != dest_name:
                                old.unlink()

                        shutil.copy2(image_path, dest_path)

                        # Update state
                        output_name = mon["name"]
                        state[output_name] = {"file": dest_name, "mode": section.get_mode().value}
                        section.reset_changed()
                        any_monitor_changed = True

            # Save state and regenerate if any monitor changed
            if any_monitor_changed:
                save_state(state)
                regenerate_spanned()
                apply_spanned_via_gsettings()

            QMessageBox.information(self, "Success", "Wallpapers applied successfully!")

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to apply wallpapers: {str(e)}")


def launch_gui():
    """Launch the AllPaper GUI application."""
    app = QApplication(sys.argv)
    app.setApplicationName("AllPaper")

    window = AllPaperGUI()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    launch_gui()
