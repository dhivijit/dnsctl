"""Theme management for dnsctl-g — dark/light mode using qt-material."""

import json
import logging
from pathlib import Path

from PyQt6.QtWidgets import QApplication

logger = logging.getLogger(__name__)

_SETTINGS_FILE: Path | None = None  # lazy-loaded to avoid side effects at import time


def _settings_file() -> Path:
    global _SETTINGS_FILE
    if _SETTINGS_FILE is None:
        from dnsctl.config import STATE_DIR
        _SETTINGS_FILE = STATE_DIR / "gui_settings.json"
    return _SETTINGS_FILE


# qt-material theme file for each mode
_THEME_MAP: dict[str, str] = {
    "dark":  "dark_teal.xml",
    "light": "light_teal.xml",
}

# Extra qt-material customisation — slightly more compact density
_EXTRA: dict[str, str] = {
    "density_scale": "-1",
}

# Primary accent color per mode — used for hover glow animations.
ACCENT_COLOR: dict[str, str] = {
    "dark":  "#00BCD4",   # teal 500 — reads well on dark backgrounds
    "light": "#00796B",   # teal 700 — reads well on light backgrounds
}

# Semantic color tokens used throughout controllers for programmatic styling.
# Dark-mode values are "light" variants so they read well on dark backgrounds;
# light-mode values are "dark" variants so they read well on light backgrounds.
SEMANTIC_COLORS: dict[str, dict[str, str]] = {
    "dark": {
        "error":   "#EF9A9A",   # light red
        "warning": "#FFCC80",   # light amber
        "success": "#A5D6A7",   # light green
        "muted":   "#90A4AE",   # blue-gray
        "danger":  "#EF9A9A",   # same as error (used for destructive actions)
        "info":    "#80DEEA",   # light teal/cyan
    },
    "light": {
        "error":   "#C62828",   # dark red
        "warning": "#E65100",   # dark orange
        "success": "#2E7D32",   # dark green
        "muted":   "#546E7A",   # dark blue-gray
        "danger":  "#B71C1C",   # deep red
        "info":    "#00695C",   # dark teal
    },
}


def load_theme_pref() -> str:
    """Return ``"dark"`` or ``"light"`` from persisted settings (default ``"dark"``)."""
    try:
        data = json.loads(_settings_file().read_text(encoding="utf-8"))
        mode = data.get("theme", "dark")
        return mode if mode in ("dark", "light") else "dark"
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return "dark"


def save_theme_pref(mode: str) -> None:
    """Persist the theme preference alongside other GUI settings."""
    try:
        path = _settings_file()
        existing: dict = {}
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            pass
        existing["theme"] = mode
        path.write_text(json.dumps(existing, indent=2), encoding="utf-8")
    except OSError:
        logger.warning("Could not save theme preference.")


def apply_theme(app: QApplication, mode: str) -> None:
    """Apply the qt-material stylesheet for *mode* to *app*.

    If qt-material is not installed the application falls back to the default
    OS style silently — no crash.
    """
    try:
        from qt_material import apply_stylesheet
        apply_stylesheet(app, theme=_THEME_MAP[mode], extra=_EXTRA)
    except Exception:
        logger.warning("qt-material not available; using default platform style.")


def toggle_theme(app: QApplication, current_mode: str) -> str:
    """Switch to the opposite theme, persist the choice, and return the new mode."""
    new_mode = "light" if current_mode == "dark" else "dark"
    apply_theme(app, new_mode)
    save_theme_pref(new_mode)
    return new_mode
