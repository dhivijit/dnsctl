"""Smooth hover glow animation for QPushButton widgets.

Installs a :class:`QGraphicsDropShadowEffect` on any button and animates its
``blurRadius`` from 0 → ``blur_end`` on mouse-enter and back on mouse-leave.
The glow color is taken from the active theme's accent color so it
integrates naturally with both dark and light qt-material themes.

Usage::

    from dnsctl.gui.hover_anim import install_hover_animation
    install_hover_animation(button, color="#00BCD4")

Safe to call repeatedly (e.g. after a theme toggle) — subsequent calls on the
same button just update the glow color without duplicating effects or filters.
"""

from __future__ import annotations

from PyQt6.QtCore import QEasingCurve, QEvent, QObject, QPropertyAnimation
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QAbstractButton, QGraphicsDropShadowEffect


class _HoverFilter(QObject):
    """Event filter that starts in/out glow animations on Enter/Leave."""

    def __init__(
        self,
        parent: QAbstractButton,
        anim_in: QPropertyAnimation,
        anim_out: QPropertyAnimation,
    ) -> None:
        super().__init__(parent)
        self._anim_in = anim_in
        self._anim_out = anim_out

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # noqa: N802
        if event.type() == QEvent.Type.Enter:
            self._anim_out.stop()
            self._anim_in.start()
        elif event.type() == QEvent.Type.Leave:
            self._anim_in.stop()
            self._anim_out.start()
        return False  # let the event propagate normally


def install_hover_animation(
    btn: QAbstractButton,
    color: str = "#00BCD4",
    blur_end: int = 16,
    duration: int = 180,
) -> None:
    """Attach a smooth drop-shadow glow to *btn*.

    Parameters
    ----------
    btn:
        Any :class:`QPushButton` or :class:`QToolButton`.
    color:
        CSS hex color string for the glow (should match the theme accent).
    blur_end:
        Maximum blur radius (pixels) at full hover intensity.
    duration:
        Animation duration in milliseconds.
    """
    existing = btn.graphicsEffect()
    if isinstance(existing, QGraphicsDropShadowEffect):
        # Already installed — just update the color for the new theme
        existing.setColor(QColor(color))
        return

    effect = QGraphicsDropShadowEffect(btn)
    effect.setBlurRadius(0)
    effect.setXOffset(0)
    effect.setYOffset(0)
    effect.setColor(QColor(color))
    btn.setGraphicsEffect(effect)

    anim_in = QPropertyAnimation(effect, b"blurRadius", btn)
    anim_in.setDuration(duration)
    anim_in.setStartValue(0)
    anim_in.setEndValue(blur_end)
    anim_in.setEasingCurve(QEasingCurve.Type.OutCubic)

    anim_out = QPropertyAnimation(effect, b"blurRadius", btn)
    anim_out.setDuration(duration)
    anim_out.setStartValue(blur_end)
    anim_out.setEndValue(0)
    anim_out.setEasingCurve(QEasingCurve.Type.InCubic)

    f = _HoverFilter(btn, anim_in, anim_out)
    btn.installEventFilter(f)
    # Keep a reference on the button so the filter isn't garbage-collected
    btn._hover_filter = f  # type: ignore[attr-defined]
