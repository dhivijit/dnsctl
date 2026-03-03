"""Icon helpers for dnsctl-g using qtawesome (Font Awesome 5 Solid).

Usage::

    from dnsctl.gui.icons import get_icon
    button.setIcon(get_icon("sync"))
    delete_btn.setIcon(get_icon("delete", color="#EF9A9A"))

Falls back gracefully to an empty QIcon when qtawesome is not installed.
"""

from __future__ import annotations

from PyQt6.QtGui import QIcon

# Logical name → Font Awesome 5 Solid icon identifier
ICON_MAP: dict[str, str] = {
    "sync":        "fa5s.sync",
    "plan":        "fa5s.clipboard-list",
    "history":     "fa5s.history",
    "lock":        "fa5s.lock",
    "add":         "fa5s.plus-circle",
    "edit":        "fa5s.edit",
    "delete":      "fa5s.trash-alt",
    "import_":     "fa5s.file-import",
    "export":      "fa5s.file-export",
    "apply":       "fa5s.check-circle",
    "force_apply": "fa5s.exclamation-circle",
    "rollback":    "fa5s.undo",
    "theme_dark":  "fa5s.moon",
    "theme_light": "fa5s.sun",
    "close":       "fa5s.times",
    "save":        "fa5s.save",
    "cancel":      "fa5s.ban",
    "help":        "fa5s.question-circle",
}


def get_icon(name: str, color: str | None = None) -> QIcon:
    """Return a QIcon for the given logical icon name.

    Parameters
    ----------
    name:
        A key from :data:`ICON_MAP`.
    color:
        Explicit hex color string (e.g. ``"#EF9A9A"``).  When *None*,
        qtawesome infers the color from the current QPalette so icons
        automatically adapt to dark/light mode.

    Returns an empty QIcon if qtawesome is unavailable.
    """
    try:
        import qtawesome as qta
        fa_name = ICON_MAP.get(name, "fa5s.circle")
        kwargs: dict = {}
        if color:
            kwargs["color"] = color
        return qta.icon(fa_name, **kwargs)
    except Exception:
        return QIcon()
