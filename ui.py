import sys
import os
import math
import array
import shutil
import tempfile
import subprocess
import threading
from pathlib import Path
from typing import Optional

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QFrame, QLabel, QPushButton,
    QHBoxLayout, QVBoxLayout, QGridLayout, QScrollArea, QSlider,
    QRadioButton, QCheckBox, QComboBox, QLineEdit, QProgressBar,
    QTabWidget, QFileDialog, QMessageBox, QButtonGroup, QSizePolicy,
)
from PyQt6.QtCore import Qt, QTimer, QObject, QEvent, pyqtSignal, QPoint, QRect
from PyQt6.QtGui import (
    QPainter, QColor, QBrush, QPalette, QFont, QPen, QKeySequence, QShortcut,
    QPixmap, QPolygon,
)

try:
    import mpv
    MPV_AVAILABLE = True
except Exception:
    MPV_AVAILABLE = False

from video import VideoInfo, probe_video
from encoder import Encoder, ffmpeg_available, calculate_video_bitrate
from ff_paths import FFMPEG

VIDEO_EXT = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".flv", ".wmv", ".m4v", ".ts"}
DISCORD_PRESETS = [("8 MB", 8), ("50 MB", 50), ("100 MB", 100)]
STATUS_COLORS = {
    "Reading":     "#f59e0b",
    "Ready":       "#4ade80",
    "Compressing": "#3b82f6",
    "Done":        "#22c55e",
    "Error":       "#ef4444",
    "Cancelled":   "#f97316",
}


def _fmt_time(t: float) -> str:
    t = max(0.0, t)
    return f"{int(t // 60)}:{t % 60:04.1f}"


# ---------------------------------------------------------------------------
# Theme
# ---------------------------------------------------------------------------

STYLESHEET = """
QPushButton {
    background: #3a3a3a; border: none; border-radius: 4px;
    color: #e0e0e0; padding: 4px 12px;
}
QPushButton:hover  { background: #4a4a4a; }
QPushButton:disabled { background: #2a2a2a; color: #555; }
QLineEdit {
    background: #1e1e1e; border: 1px solid #555; border-radius: 4px;
    padding: 4px 8px; color: #e0e0e0;
}
QComboBox {
    background: #3a3a3a; border: 1px solid #555; border-radius: 4px;
    padding: 4px 8px; color: #e0e0e0;
}
QComboBox QAbstractItemView {
    background: #3a3a3a; border: 1px solid #555;
    selection-background-color: #3b82f6; color: #e0e0e0;
}
QComboBox::drop-down { border: none; }
QRadioButton { color: #e0e0e0; spacing: 6px; }
QRadioButton::indicator {
    width: 14px; height: 14px; border-radius: 7px;
    border: 2px solid #666; background: transparent;
}
QRadioButton::indicator:checked {
    border: 2px solid #3b82f6; background: #3b82f6;
}
QCheckBox { color: #e0e0e0; spacing: 6px; }
QCheckBox::indicator {
    width: 14px; height: 14px; border-radius: 3px;
    border: 2px solid #666; background: transparent;
}
QCheckBox::indicator:checked {
    border: 2px solid #3b82f6; background: #3b82f6;
}
QSlider::groove:horizontal {
    background: #3a3a3a; height: 6px; border-radius: 3px;
}
QSlider::handle:horizontal {
    background: #3b82f6; width: 14px; height: 14px;
    border-radius: 7px; margin: -4px 0;
}
QSlider::sub-page:horizontal { background: #3b82f6; border-radius: 3px; }
QScrollBar:vertical {
    background: transparent; width: 8px; margin: 0;
}
QScrollBar::handle:vertical {
    background: #555; border-radius: 4px; min-height: 20px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }
QTabWidget::pane {
    border: none; background: #333333;
    border-bottom-left-radius: 8px; border-bottom-right-radius: 8px;
}
QTabBar::tab {
    background: #2b2b2b; color: #888;
    padding: 8px 18px; border: none;
    border-top-left-radius: 6px; border-top-right-radius: 6px;
    margin-right: 2px;
}
QTabBar::tab:selected { background: #333333; color: #e0e0e0; }
QTabBar::tab:hover    { color: #e0e0e0; }
QProgressBar {
    background: #2b2b2b; border-radius: 4px;
    border: none; text-align: center; color: transparent;
}
QProgressBar::chunk { background: #3b82f6; border-radius: 4px; }
"""


def apply_dark_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    pal = QPalette()
    dark    = QColor("#2b2b2b")
    darker  = QColor("#1e1e1e")
    text    = QColor("#e0e0e0")
    button  = QColor("#3a3a3a")
    hl      = QColor("#3b82f6")
    pal.setColor(QPalette.ColorRole.Window,          dark)
    pal.setColor(QPalette.ColorRole.WindowText,      text)
    pal.setColor(QPalette.ColorRole.Base,            darker)
    pal.setColor(QPalette.ColorRole.AlternateBase,   dark)
    pal.setColor(QPalette.ColorRole.ToolTipBase,     dark)
    pal.setColor(QPalette.ColorRole.ToolTipText,     text)
    pal.setColor(QPalette.ColorRole.Text,            text)
    pal.setColor(QPalette.ColorRole.Button,          button)
    pal.setColor(QPalette.ColorRole.ButtonText,      text)
    pal.setColor(QPalette.ColorRole.BrightText,      QColor("#ff4444"))
    pal.setColor(QPalette.ColorRole.Link,            hl)
    pal.setColor(QPalette.ColorRole.Highlight,       hl)
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text,       QColor("#555"))
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor("#555"))
    app.setPalette(pal)


# ---------------------------------------------------------------------------
# Card widget (rounded dark panel, no stylesheet cascade issues)
# ---------------------------------------------------------------------------

class Card(QFrame):
    def __init__(self, parent=None, color="#333333", radius=8):
        super().__init__(parent)
        self._color  = QColor(color)
        self._radius = radius
        self.setAutoFillBackground(False)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(QBrush(self._color))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(self.rect(), self._radius, self._radius)


# ---------------------------------------------------------------------------
# Number entry — QLineEdit that redirects Space to the window shortcut
# ---------------------------------------------------------------------------

class NumberEdit(QLineEdit):
    spacePressed = pyqtSignal()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Space:
            self.clearFocus()
            self.spacePressed.emit()
        elif event.key() == Qt.Key.Key_Escape:
            self.clearFocus()
        else:
            super().keyPressEvent(event)


# ---------------------------------------------------------------------------
# Icon button
# ---------------------------------------------------------------------------

class IconButton(QPushButton):
    """Flat button that paints a named vector icon via QPainter."""

    def __init__(self, icon_name: str, parent=None):
        super().__init__(parent)
        self._icon = icon_name
        self.setText("")
        self.setFixedSize(36, 28)
        self.setStyleSheet(
            "QPushButton { background: #2c2c2c; border: 1px solid #505050;"
            " border-radius: 5px; }"
            "QPushButton:hover { background: #3d3d3d; border-color: #707070; }"
            "QPushButton:pressed { background: #222; }"
        )

    def set_icon(self, name: str):
        self._icon = name
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cx, cy = self.width() // 2, self.height() // 2
        ic = QColor("#e0e0e0")

        if self._icon == "play":
            p.setBrush(QBrush(ic))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawPolygon(QPolygon([
                QPoint(cx - 5, cy - 7),
                QPoint(cx - 5, cy + 7),
                QPoint(cx + 7, cy),
            ]))

        elif self._icon == "pause":
            p.setBrush(QBrush(ic))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(cx - 6, cy - 6, 4, 12, 1.5, 1.5)
            p.drawRoundedRect(cx + 2, cy - 6, 4, 12, 1.5, 1.5)

        elif self._icon == "vol_on":
            p.setBrush(QBrush(ic))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawPolygon(QPolygon([
                QPoint(5,  cy - 3), QPoint(10, cy - 3),
                QPoint(15, cy - 7), QPoint(15, cy + 7),
                QPoint(10, cy + 3), QPoint(5,  cy + 3),
            ]))
            pen = QPen(ic, 2)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawArc(QRect(17, cy - 5,  8, 10), -60 * 16, 120 * 16)
            p.drawArc(QRect(19, cy - 8, 12, 16), -55 * 16, 110 * 16)

        elif self._icon == "vol_off":
            p.setBrush(QBrush(ic))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawPolygon(QPolygon([
                QPoint(4,  cy - 3), QPoint(9,  cy - 3),
                QPoint(14, cy - 7), QPoint(14, cy + 7),
                QPoint(9,  cy + 3), QPoint(4,  cy + 3),
            ]))
            pen = QPen(ic, 2)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.drawLine(QPoint(19, cy - 5), QPoint(27, cy + 5))
            p.drawLine(QPoint(19, cy + 5), QPoint(27, cy - 5))


# ---------------------------------------------------------------------------
# Trim bar
# ---------------------------------------------------------------------------

class OverviewBar(QWidget):
    """Compact full-clip strip: trim handles + moving playhead."""
    trimChanged = pyqtSignal(float, float)
    seeked      = pyqtSignal(float)

    H    = 32
    GRAB = 12

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(self.H)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.duration   = 0.0
        self.start_time = 0.0
        self.end_time   = 0.0
        self._playhead  = 0.0
        self._drag: Optional[str] = None

    def set_clip(self, duration: float, start: float = 0.0,
                 end: Optional[float] = None):
        self.duration   = duration
        self.start_time = start
        self.end_time   = end if end is not None else duration
        self._playhead  = start
        self.update()

    def set_playhead(self, t: float):
        self._playhead = t
        self.update()

    def reset(self):
        self.duration = self.start_time = self.end_time = self._playhead = 0.0
        self.update()

    def _tx(self, t: float) -> int:
        return int(t / max(self.duration, 0.001) * self.width())

    def _xt(self, x: float) -> float:
        return max(0.0, min(self.duration, x / max(self.width(), 1) * self.duration))

    def paintEvent(self, _event):
        p = QPainter(self)
        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, QColor("#252525"))
        if self.duration <= 0:
            return
        lx = self._tx(self.start_time)
        rx = self._tx(self.end_time)
        hw = 7  # half-width of each handle (total = 14px)
        hc = QColor("#f59e0b")  # amber

        # Dim regions outside the handles
        if lx - hw > 0:
            p.fillRect(0, 0, lx - hw, h, QColor(0, 0, 0, 150))
        if rx + hw < w:
            p.fillRect(rx + hw, 0, w - (rx + hw), h, QColor(0, 0, 0, 150))

        # Top/bottom bars connecting the two handles
        bar_h = 3
        bar_start = lx + hw
        bar_end   = rx - hw
        if bar_end > bar_start:
            p.fillRect(bar_start, 0,          bar_end - bar_start, bar_h, hc)
            p.fillRect(bar_start, h - bar_h,  bar_end - bar_start, bar_h, hc)

        # Thick amber handles
        p.fillRect(lx - hw, 0, hw * 2, h, hc)
        p.fillRect(rx - hw, 0, hw * 2, h, hc)

        # Grip lines: 3 short white horizontal bars centered on each handle
        gc = QColor(255, 255, 255, 200)
        mid_y = h // 2
        for dy in (-4, 0, 4):
            gy = mid_y + dy
            p.fillRect(lx - 3, gy, 6, 2, gc)
            p.fillRect(rx - 3, gy, 6, 2, gc)

        # Playhead (drawn last so it overlaps everything)
        px = self._tx(self._playhead)
        p.fillRect(px - 1, 0, 2, h, QColor("#ef4444"))

    def mousePressEvent(self, event):
        if self.duration <= 0 or event.button() != Qt.MouseButton.LeftButton:
            return
        x  = event.position().x()
        lx = self._tx(self.start_time)
        rx = self._tx(self.end_time)
        if abs(x - lx) <= self.GRAB:
            self._drag = "left"
        elif abs(x - rx) <= self.GRAB:
            self._drag = "right"
        else:
            self._drag = "seek"
            t = self._xt(x)
            self._playhead = t
            self.update()
            self.seeked.emit(t)
        self.setCursor(Qt.CursorShape.SizeHorCursor)

    def mouseMoveEvent(self, event):
        if not self._drag or self.duration <= 0:
            return
        t = self._xt(event.position().x())
        if self._drag == "left":
            self.start_time = max(0.0, min(t, self.end_time - 0.25))
            self.update()
            self.trimChanged.emit(self.start_time, self.end_time)
        elif self._drag == "right":
            self.end_time = min(self.duration, max(t, self.start_time + 0.25))
            self.update()
            self.trimChanged.emit(self.start_time, self.end_time)
        else:
            self._playhead = max(0.0, min(self.duration, t))
            self.update()
            self.seeked.emit(self._playhead)

    def mouseReleaseEvent(self, event):
        if self._drag == "left":
            self.seeked.emit(self.start_time)
        elif self._drag == "right":
            self.seeked.emit(self.end_time)
        self._drag = None
        self.setCursor(Qt.CursorShape.ArrowCursor)


# ---------------------------------------------------------------------------

class FilmstripTimeline(QWidget):
    """Scrolling filmstrip: playhead fixed at 30%, thumbnails scroll under it."""
    seeked        = pyqtSignal(float)
    _thumbs_ready = pyqtSignal(object)  # internal: list[str] of file paths

    RULER_H      = 22
    PLAYHEAD_FRAC = 0.30

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(80)
        sp = self.sizePolicy()
        sp.setVerticalPolicy(QSizePolicy.Policy.Expanding)
        self.setSizePolicy(sp)
        self.setCursor(Qt.CursorShape.ArrowCursor)

        self.duration   = 0.0
        self.start_time = 0.0
        self.end_time   = 0.0
        self._playhead  = 0.0
        self._seeking   = False
        self._drag_t0   = 0.0
        self._drag_x0   = 0.0
        self._thumbnails: list = []
        self._thumb_cancel = threading.Event()
        self._tempdir: Optional[str] = None
        self._thumbs_ready.connect(self._on_thumbs_ready)

    def set_clip(self, path: str, duration: float, start: float = 0.0,
                 end: Optional[float] = None):
        self.duration   = duration
        self.start_time = start
        self.end_time   = end if end is not None else duration
        self._playhead  = start
        self._thumbnails.clear()

        self._thumb_cancel.set()
        self._thumb_cancel = threading.Event()

        if self._tempdir:
            old = self._tempdir
            self._tempdir = None
            threading.Thread(target=shutil.rmtree, args=(old,),
                             kwargs={"ignore_errors": True}, daemon=True).start()

        self.update()

        self._tempdir = tempfile.mkdtemp(prefix="vcthumb_")
        threading.Thread(
            target=self._extract_thumbs,
            args=(path, duration, self._tempdir, self._thumb_cancel),
            daemon=True,
        ).start()

    def _extract_thumbs(self, path: str, duration: float,
                        tempdir: str, cancel: threading.Event):
        count    = 30
        interval = max(0.1, duration / count)
        pattern  = os.path.join(tempdir, "t%04d.jpg")
        cmd = [
            FFMPEG, "-i", path,
            "-vf", (f"fps=1/{interval:.4f},"
                    "scale=320:180:force_original_aspect_ratio=decrease,"
                    "pad=320:180:(ow-iw)/2:(oh-ih)/2,setsar=1"),
            "-frames:v", str(count), "-f", "image2", pattern, "-y",
        ]
        try:
            subprocess.run(cmd, capture_output=True, timeout=60,
                           creationflags=subprocess.CREATE_NO_WINDOW)
        except Exception:
            return
        if cancel.is_set():
            return
        paths = []
        for i in range(1, count + 1):
            if cancel.is_set():
                return
            f = os.path.join(tempdir, f"t{i:04d}.jpg")
            if os.path.exists(f):
                paths.append(f)
        if paths and not cancel.is_set():
            self._thumbs_ready.emit(paths)

    def _on_thumbs_ready(self, paths: list):
        pixmaps = []
        for path in paths:
            pm = QPixmap(path)
            if not pm.isNull():
                pixmaps.append(pm)
        self._thumbnails = pixmaps
        self.update()

    def set_playhead(self, t: float):
        self._playhead = t
        self.update()

    def set_trim(self, start: float, end: float):
        self.start_time = start
        self.end_time   = end
        self.update()

    def reset(self):
        self._thumb_cancel.set()
        self._thumbnails.clear()
        self.duration = self.start_time = self.end_time = self._playhead = 0.0
        self.update()

    def _tile_w(self) -> float:
        """Natural tile width: 16:9 based on current filmstrip height."""
        return max(1.0, (self.height() - self.RULER_H) * 16.0 / 9.0)

    def _total_w(self) -> float:
        """Total filmstrip pixel width at natural scale."""
        n = len(self._thumbnails) if self._thumbnails else 30
        return self._tile_w() * n

    def _offset(self) -> float:
        """Screen x where t=0 sits, accounting for current scroll position."""
        ph_x = self.width() * self.PLAYHEAD_FRAC
        if self.duration <= 0:
            return ph_x
        return ph_x - self._playhead / self.duration * self._total_w()

    def _tx(self, t: float) -> int:
        return int(self._offset() + t / max(self.duration, 0.001) * self._total_w())

    def _xt(self, x: float) -> float:
        off = self._offset()
        t   = (x - off) / max(self._total_w(), 1) * self.duration
        return max(0.0, min(self.duration, t))

    def _nice_interval(self, total_w: float) -> float:
        # Base tick density on how much time is visible across the widget width
        visible_dur = self.duration * self.width() / max(total_w, 1)
        target      = max(4, self.width() // 120)
        raw         = visible_dur / target
        for n in [0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600]:
            if n >= raw:
                return n
        return 600.0

    def paintEvent(self, _event):
        p = QPainter(self)
        w, h = self.width(), self.height()
        rh = self.RULER_H
        sy = rh
        sh = h - rh

        tile_w  = self._tile_w()
        total_w = self._total_w()
        off     = self._offset()
        clip_x0 = int(off)
        clip_x1 = int(off + total_w)
        ph_x    = int(w * self.PLAYHEAD_FRAC)

        # Background
        p.fillRect(0, sy, w, sh, QColor("#111111"))

        # Thumbnails — drawn at natural tile width, clipped to widget
        if self._thumbnails and self.duration > 0:
            p.save()
            p.setClipRect(0, sy, w, sh)
            draw_w = math.ceil(tile_w) + 1
            for i, pm in enumerate(self._thumbnails):
                x = int(off + i * tile_w)
                if x + draw_w > 0 and x < w:
                    p.drawPixmap(QRect(x, sy, draw_w, sh), pm)
            p.restore()

        # Dark fill outside clip bounds
        if clip_x0 > 0:
            p.fillRect(0, sy, min(clip_x0, w), sh, QColor("#111111"))
        if clip_x1 < w:
            p.fillRect(max(clip_x1, 0), sy, w - max(clip_x1, 0), sh, QColor("#111111"))

        # Dim outside trim region
        if self.duration > 0:
            lx      = self._tx(self.start_time)
            rx      = self._tx(self.end_time)
            dim     = QColor(0, 0, 0, 150)
            inner_l = max(0, clip_x0)
            inner_r = min(w, clip_x1)
            if lx > inner_l:
                p.fillRect(inner_l, sy, lx - inner_l, sh, dim)
            if rx < inner_r:
                p.fillRect(rx, sy, inner_r - rx, sh, dim)

        # Ruler
        p.fillRect(0, 0, w, rh, QColor("#252525"))
        p.setPen(QColor("#444"))
        p.drawLine(0, rh - 1, w, rh - 1)

        if self.duration > 0:
            interval = self._nice_interval(total_w)
            p.setFont(QFont("Segoe UI", 7))
            t = 0.0
            while t <= self.duration + 0.001:
                tx = self._tx(t)
                if 0 <= tx <= w:
                    p.setPen(QColor("#555"))
                    p.drawLine(tx, rh - 6, tx, rh - 1)
                    p.setPen(QColor("#aaa"))
                    p.drawText(tx + 3, rh - 7, _fmt_time(t))
                t += interval

        # Fixed playhead
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor("#ef4444")))
        p.drawPolygon(QPolygon([QPoint(ph_x - 6, 0),
                                QPoint(ph_x + 6, 0),
                                QPoint(ph_x, rh - 1)]))
        p.fillRect(ph_x - 1, sy, 2, sh, QColor("#ef4444"))

    def mousePressEvent(self, event):
        if self.duration <= 0 or event.button() != Qt.MouseButton.LeftButton:
            return
        self._seeking    = True
        self._drag_t0    = self._playhead
        self._drag_x0    = event.position().x()
        t = self._xt(event.position().x())
        self._playhead = t
        self.update()
        self.seeked.emit(t)
        self.setCursor(Qt.CursorShape.SizeHorCursor)

    def mouseMoveEvent(self, event):
        if not self._seeking or self.duration <= 0:
            return
        # Compute seek as delta from the original click, using natural scale
        dx = event.position().x() - self._drag_x0
        t  = max(0.0, min(self.duration,
                          self._drag_t0 - dx / self._total_w() * self.duration))
        self._playhead = t
        self.update()
        self.seeked.emit(t)

    def mouseReleaseEvent(self, event):
        self._seeking = False
        self.setCursor(Qt.CursorShape.ArrowCursor)


# ---------------------------------------------------------------------------
# Audio meter
# ---------------------------------------------------------------------------

class AudioMeter(QWidget):
    DB_MAX    =   0.0
    DB_RED    =  -9.0
    DB_ORANGE = -18.0
    DB_MIN    = -60.0

    COL_RED        = QColor("#ff2020")
    COL_ORANGE     = QColor("#ffaa00")
    COL_GREEN      = QColor("#22cc55")
    COL_RED_DIM    = QColor("#3d0808")
    COL_ORANGE_DIM = QColor("#3d2800")
    COL_GREEN_DIM  = QColor("#0a2d14")

    CH_W  = 14; CH_GAP = 4; PAD_L = 4; PAD_R = 26
    PAD_T =  6; PAD_B  = 14; SEG_H = 4; SEG_GAP = 1
    DB_MARKS = [0, -6, -12, -18, -24, -36, -48]

    def __init__(self, channels: int = 2, parent=None):
        super().__init__(parent)
        self._ch = channels
        w = self.PAD_L + channels * self.CH_W + (channels - 1) * self.CH_GAP + self.PAD_R
        self.setFixedWidth(w)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self._level = [0.0] * channels
        self._peak  = [0.0] * channels
        self._hold  = [0]   * channels

    def update_levels(self, levels: list[float]):
        for i, lv in enumerate(levels[:self._ch]):
            lv = max(0.0, min(1.0, float(lv)))
            self._level[i] = lv if lv >= self._level[i] else max(0.0, self._level[i] * 0.72)
            if lv >= self._peak[i]:
                self._peak[i] = lv; self._hold[i] = 22
            elif self._hold[i] > 0:
                self._hold[i] -= 1
            else:
                self._peak[i] = max(0.0, self._peak[i] - 0.018)
        self.update()

    def silence(self):
        self._level = [0.0] * self._ch
        self._peak  = [0.0] * self._ch
        self._hold  = [0]   * self._ch
        self.update()

    def _to_db(self, level: float) -> float:
        return self.DB_MIN + level * (self.DB_MAX - self.DB_MIN)

    def _db_to_y(self, db: float, bar_top: int, bar_h: int) -> float:
        return bar_top + (db - self.DB_MAX) / (self.DB_MIN - self.DB_MAX) * bar_h

    def _col(self, db: float, lit: bool) -> QColor:
        if db >= self.DB_RED:
            return self.COL_RED    if lit else self.COL_RED_DIM
        elif db >= self.DB_ORANGE:
            return self.COL_ORANGE if lit else self.COL_ORANGE_DIM
        else:
            return self.COL_GREEN  if lit else self.COL_GREEN_DIM

    def paintEvent(self, _event):
        p = QPainter(self)
        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, QColor("#1a1a1a"))

        bar_top = self.PAD_T
        bar_bot = h - self.PAD_B
        bar_h   = bar_bot - bar_top
        if bar_h <= 4:
            return

        seg_step = self.SEG_H + self.SEG_GAP
        for ch in range(self._ch):
            cx       = self.PAD_L + ch * (self.CH_W + self.CH_GAP)
            level_db = self._to_db(self._level[ch])
            peak_db  = self._to_db(self._peak[ch])
            seg_y    = bar_top
            while seg_y + self.SEG_H <= bar_bot:
                seg_db = self.DB_MAX + (seg_y - bar_top) / bar_h * (self.DB_MIN - self.DB_MAX)
                p.fillRect(cx, seg_y, self.CH_W, self.SEG_H, self._col(seg_db, seg_db <= level_db))
                seg_y += seg_step
            if self._peak[ch] > 0.01:
                py = int(self._db_to_y(peak_db, bar_top, bar_h))
                if bar_top <= py <= bar_bot - self.SEG_H:
                    p.fillRect(cx, py, self.CH_W, self.SEG_H, self._col(peak_db, True))

        lx = self.PAD_L + self._ch * self.CH_W + (self._ch - 1) * self.CH_GAP + 3
        f  = QFont("Segoe UI", 7)
        p.setFont(f)
        for db in self.DB_MARKS:
            y = int(self._db_to_y(db, bar_top, bar_h))
            if bar_top <= y <= bar_bot:
                p.setPen(QColor("#444444"))
                p.drawLine(lx, y, lx + 4, y)
                p.setPen(QColor("#777777"))
                p.drawText(lx + 6, y + 4, str(abs(db)))

        x_end = self.PAD_L + self._ch * self.CH_W + (self._ch - 1) * self.CH_GAP
        for db_line in (self.DB_RED, self.DB_ORANGE):
            y_cont = self._db_to_y(db_line, bar_top, bar_h)
            n      = int((y_cont - bar_top) / seg_step)
            snap_y = bar_top + n * seg_step + self.SEG_H
            if bar_top < snap_y < bar_bot:
                p.setPen(QColor("#000000"))
                p.drawLine(self.PAD_L, snap_y, x_end, snap_y)

        p.setFont(QFont("Segoe UI", 8))
        p.setPen(QColor("#666666"))
        for ch in range(self._ch):
            cx = self.PAD_L + ch * (self.CH_W + self.CH_GAP)
            p.drawText(cx + self.CH_W // 2 - 4, h - 2, "L" if ch == 0 else "R")


# ---------------------------------------------------------------------------
# Waveform view
# ---------------------------------------------------------------------------

class WaveformView(QWidget):
    """L channel above center-line, R below; trim shading + draggable playhead."""
    seeked = pyqtSignal(float)

    _BAR_COLOR   = QColor("#22c55e")
    _CLIP_COLOR  = QColor("#ef4444")
    _DIM         = QColor(0, 0, 0, 130)
    _PH_COLOR    = QColor("#ef4444")
    _CENTER_LINE = QColor("#404040")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(70)
        sp = self.sizePolicy()
        sp.setVerticalPolicy(QSizePolicy.Policy.Expanding)
        self.setSizePolicy(sp)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self._levels:     list[tuple[float, float]] = []
        self._fps:        float                     = 30.0
        self._duration:   float                     = 0.0
        self._trim_start: float                     = 0.0
        self._trim_end:   float                     = 0.0
        self._playhead:   float                     = 0.0
        self._volume_db:  float                     = 0.0
        self._normalize:  bool                      = False
        self._dragging:   bool                      = False
        self._cache:      Optional[QPixmap]         = None

    def set_clip(self, levels, fps, duration, trim_start, trim_end):
        self._levels     = levels
        self._fps        = fps
        self._duration   = duration
        self._trim_start = trim_start
        self._trim_end   = trim_end if trim_end is not None else duration
        self._playhead   = 0.0
        self._cache      = None
        self.update()

    def set_playhead(self, t: float):
        self._playhead = t
        self.update()

    def set_volume_db(self, db: float):
        self._volume_db = db
        self._cache     = None
        self.update()

    def set_normalize(self, enabled: bool):
        self._normalize = enabled
        self._cache     = None
        self.update()

    def set_trim(self, start: float, end: float):
        self._trim_start = start
        self._trim_end   = end
        self.update()

    def reset(self):
        self._levels    = []
        self._duration  = 0.0
        self._playhead  = 0.0
        self._volume_db = 0.0
        self._normalize = False
        self._cache     = None
        self.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._cache = None

    def _rebuild_cache(self):
        w, h = self.width(), self.height()
        if w <= 0 or h <= 0:
            return
        px = QPixmap(w, h)
        px.fill(QColor("#1a1a1a"))
        p = QPainter(px)
        cy     = h // 2
        half_h = max(1, cy - 2)
        vol    = 10.0 ** (self._volume_db / 20.0)
        # When normalized, simulate loudnorm: scale RMS to a fixed reference level.
        # RMS better reflects perceived loudness than peak.
        # Loud clips shrink noticeably; quiet clips grow significantly.
        if self._normalize and self._levels:
            amps = [max(la, ra) for la, ra in self._levels]
            rms  = math.sqrt(sum(a * a for a in amps) / len(amps)) if amps else 0.0
            if rms > 0.0:
                vol *= min(0.25 / rms, 4.0)  # target RMS ~25%, cap 4× boost
        for x in range(w):
            t   = x / w * self._duration
            idx = int(t * self._fps)
            if not (0 <= idx < len(self._levels)):
                continue
            la, ra = self._levels[idx]
            clipping = la * vol > 1.0 or ra * vol > 1.0
            color = self._CLIP_COLOR if clipping else self._BAR_COLOR
            lh = max(1, int(min(la * vol, 1.0) * half_h))
            rh = max(1, int(min(ra * vol, 1.0) * half_h))
            p.fillRect(x, cy - lh, 1, lh, color)
            p.fillRect(x, cy,      1, rh, color)
        p.fillRect(0, cy, w, 1, self._CENTER_LINE)
        p.end()
        self._cache = px

    def paintEvent(self, _event):
        p = QPainter(self)
        w, h = self.width(), self.height()
        if not self._levels or self._duration <= 0:
            p.fillRect(0, 0, w, h, QColor("#1a1a1a"))
            p.setPen(QColor("#555"))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                       "Select a clip to view waveform")
            return
        if self._cache is None:
            self._rebuild_cache()
        p.drawPixmap(0, 0, self._cache)
        # Trim dim
        if self._trim_start > 0:
            lx = int(self._trim_start / self._duration * w)
            p.fillRect(0, 0, lx, h, self._DIM)
        if self._trim_end < self._duration:
            rx = int(self._trim_end / self._duration * w)
            p.fillRect(rx, 0, w - rx, h, self._DIM)
        # Playhead
        phx = int(self._playhead / self._duration * w)
        p.fillRect(phx - 1, 0, 2, h, self._PH_COLOR)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._duration > 0:
            self._dragging = True
            self._seek_to(event.position().x())

    def mouseMoveEvent(self, event):
        if self._dragging:
            self._seek_to(event.position().x())

    def mouseReleaseEvent(self, event):
        self._dragging = False

    def _seek_to(self, x: float):
        t = max(0.0, min(self._duration, x / max(self.width(), 1) * self._duration))
        self._playhead = t
        self.update()
        self.seeked.emit(t)


# ---------------------------------------------------------------------------
# Video container — holds the mpv render widget, handles 16:9 fitting
# ---------------------------------------------------------------------------

class VideoContainer(QWidget):
    videoResized = pyqtSignal(int, int)   # (video_y, video_h) within this widget

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_NativeWindow)
        self.setAttribute(Qt.WidgetAttribute.WA_DontCreateNativeAncestors)
        p = self.palette()
        p.setColor(QPalette.ColorRole.Window, QColor("black"))
        self.setPalette(p)
        self.setAutoFillBackground(True)

        self.render_widget = QWidget(self)
        self.render_widget.setAttribute(Qt.WidgetAttribute.WA_NativeWindow)
        rp = self.render_widget.palette()
        rp.setColor(QPalette.ColorRole.Window, QColor("black"))
        self.render_widget.setAutoFillBackground(True)
        self.render_widget.setPalette(rp)

        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(50)
        self._resize_timer.timeout.connect(self._apply_resize)
        self._pending_w = 1
        self._pending_h = 1

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._pending_w = event.size().width()
        self._pending_h = event.size().height()
        self._resize_timer.start()

    def _apply_resize(self):
        w, h = self._pending_w, self._pending_h
        if w <= 0 or h <= 0:
            return
        vw = w
        vh = int(vw * 9 / 16)
        if vh > h:
            vh = h
            vw = int(vh * 16 / 9)
        x = (w - vw) // 2
        y = (h - vh) // 2
        self.render_widget.setGeometry(x, y, max(1, vw), max(1, vh))
        self.videoResized.emit(y, max(1, vh))


# ---------------------------------------------------------------------------
# Queue row
# ---------------------------------------------------------------------------

class QueueRow(QFrame):
    rowSelected = pyqtSignal(object)
    rowRemoved  = pyqtSignal(str)

    NORMAL_BG = "#2a2a2a"
    SEL_BG    = "#1e3a5f"

    def __init__(self, path: str, parent=None):
        super().__init__(parent)
        self.path          = path
        self.info: Optional[VideoInfo] = None
        self._status       = "Reading"
        self.trim_start    = 0.0
        self.trim_end: Optional[float] = None
        self.volume_db     = 0.0
        self.normalize     = False
        self.strip_audio   = False
        self.audio_levels: list[tuple[float, float]] = []
        self.analysis_fps  = 30.0

        self._apply_bg(self.NORMAL_BG)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 8, 8, 8)

        info_col = QVBoxLayout()
        info_col.setSpacing(2)
        name = Path(path).name
        self._name_lbl = QLabel(name if len(name) <= 36 else name[:35] + "…")
        self._name_lbl.setFont(QFont("Segoe UI", 11))
        self.meta_lbl = QLabel("Reading…")
        self.meta_lbl.setStyleSheet("color: #666;")
        self.meta_lbl.setFont(QFont("Segoe UI", 10))
        info_col.addWidget(self._name_lbl)
        info_col.addWidget(self.meta_lbl)
        lay.addLayout(info_col, 1)

        right_col = QVBoxLayout()
        right_col.setSpacing(4)
        right_col.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.status_lbl = QLabel("Reading")
        self.status_lbl.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self.status_lbl.setStyleSheet(f"color: {STATUS_COLORS['Reading']};")
        self.status_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.remove_btn = QPushButton("✕")
        self.remove_btn.setFixedSize(24, 24)
        self.remove_btn.setStyleSheet(
            "QPushButton { background: transparent; border: none; color: #888; }"
            "QPushButton:hover { color: #fff; }"
        )
        self.remove_btn.clicked.connect(lambda: self.rowRemoved.emit(self.path))
        right_col.addWidget(self.status_lbl)
        right_col.addWidget(self.remove_btn, alignment=Qt.AlignmentFlag.AlignRight)
        lay.addLayout(right_col)

    def _apply_bg(self, color: str):
        self.setStyleSheet(
            f"QueueRow {{ background: {color}; border-radius: 6px; }}"
            "QLabel { background: transparent; }"
        )

    def mousePressEvent(self, event):
        self.rowSelected.emit(self)
        super().mousePressEvent(event)

    @property
    def status(self) -> str:
        return self._status

    @status.setter
    def status(self, value: str):
        self._status = value
        self.status_lbl.setText(value)
        self.status_lbl.setStyleSheet(f"color: {STATUS_COLORS.get(value, '#888')};")
        self.remove_btn.setEnabled(value != "Compressing")

    def set_selected(self, sel: bool):
        self._apply_bg(self.SEL_BG if sel else self.NORMAL_BG)

    def set_info(self, info: VideoInfo):
        self.info = info
        if self.trim_end is None:
            self.trim_end = info.duration
        mb   = info.size_bytes / 1024 / 1024
        mins = int(info.duration // 60)
        secs = int(info.duration % 60)
        self.meta_lbl.setText(f"{mb:.1f} MB  ·  {mins}:{secs:02d}")


# ---------------------------------------------------------------------------
# Thread-safe signal bridge (background threads → Qt main thread)
# ---------------------------------------------------------------------------

class _Signals(QObject):
    probe_done        = pyqtSignal(object, object)  # (QueueRow, VideoInfo)
    probe_error       = pyqtSignal(object)          # QueueRow
    compress_progress = pyqtSignal(float)
    compress_status   = pyqtSignal(str)
    compress_row_done = pyqtSignal(object)          # QueueRow
    compress_finished = pyqtSignal()


class _MpvBridge(QObject):
    time_pos = pyqtSignal(float)
    paused   = pyqtSignal(bool)


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class CompressorWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Discord Video Compressor")
        self.resize(1440, 820)
        self.setMinimumSize(1000, 660)
        self.setAcceptDrops(True)

        self.encoder            = Encoder()
        self._output_folder: Optional[str]      = None
        self._queue_rows: list[QueueRow]        = []
        self._selected_row: Optional[QueueRow]  = None
        self._compressing  = False
        self._queue_total  = 0
        self._queue_done   = 0
        self._muted        = False
        self._paused       = False
        self._player       = None
        self._resize_paused      = False
        self._resize_was_playing = False

        self._resize_resume_timer = QTimer(self)
        self._resize_resume_timer.setSingleShot(True)
        self._resize_resume_timer.setInterval(150)
        self._resize_resume_timer.timeout.connect(self._on_resize_done)

        self._video_container: Optional[VideoContainer]     = None
        self._meter_strip: Optional[QWidget]               = None
        self._audio_meter: Optional[AudioMeter]            = None
        self._pause_btn: Optional[IconButton]               = None
        self._mute_btn:  Optional[IconButton]              = None
        self._trim_bar:    Optional[OverviewBar]           = None
        self._filmstrip:   Optional[FilmstripTimeline]     = None
        self._current_t:   float                           = 0.0
        self._normalize_cb:   Optional[QCheckBox]         = None
        self._strip_audio_cb: Optional[QCheckBox]         = None
        self._waveform:       Optional[WaveformView]      = None
        self._browse_btn:     Optional[QPushButton]       = None

        self._sig        = _Signals()
        self._mpv_bridge = _MpvBridge()
        self._sig.probe_done.connect(self._on_probe_done)
        self._sig.probe_error.connect(self._on_probe_error)
        self._sig.compress_progress.connect(self._on_compress_progress)
        self._sig.compress_status.connect(self._on_compress_status)
        self._sig.compress_row_done.connect(self._on_compress_row_done)
        self._sig.compress_finished.connect(self._compress_next)
        self._mpv_bridge.time_pos.connect(self._on_playhead_update)
        self._mpv_bridge.paused.connect(self._on_pause_update)

        self._build_ui()
        QShortcut(QKeySequence(Qt.Key.Key_Space), self, self._toggle_pause)
        QTimer.singleShot(400, self._init_player)
        QApplication.instance().installEventFilter(self)

    # ------------------------------------------------------------------ build

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(24, 12, 24, 12)
        root.setSpacing(0)

        if not ffmpeg_available():
            self._build_ffmpeg_warning(root)
            return

        top = QWidget()
        top_lay = QHBoxLayout(top)
        top_lay.setContentsMargins(0, 0, 0, 0)
        top_lay.setSpacing(8)
        self._build_clip_pool(top_lay)
        self._build_preview_panel(top_lay)
        self._build_meter_strip(top_lay)
        root.addWidget(top, 3)
        root.addSpacing(8)
        self._build_bottom_panel(root)

    def _build_ffmpeg_warning(self, layout: QVBoxLayout):
        card = Card(color="#3d1a1a")
        cl   = QVBoxLayout(card)
        cl.setContentsMargins(16, 14, 16, 14)
        t = QLabel("FFmpeg Not Found")
        t.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        t.setStyleSheet("color: #ff6b6b; background: transparent;")
        cl.addWidget(t)
        for line in [
            "FFmpeg is required. Install it by running:",
            "    winget install ffmpeg",
            "Then restart this application.",
        ]:
            lbl = QLabel(line)
            lbl.setStyleSheet("background: transparent; color: #ccc;")
            cl.addWidget(lbl)
        layout.addWidget(card)

    def _build_clip_pool(self, layout: QHBoxLayout):
        left     = QWidget()
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(0, 0, 0, 0)
        left_lay.setSpacing(8)

        # --- Clip Pool card ---
        pool_card = Card()
        pc_lay    = QVBoxLayout(pool_card)
        pc_lay.setContentsMargins(0, 0, 0, 8)
        pc_lay.setSpacing(0)

        hdr     = QWidget()
        hdr_lay = QHBoxLayout(hdr)
        hdr_lay.setContentsMargins(14, 12, 14, 6)
        title = QLabel("Clip Pool")
        title.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        title.setStyleSheet("background: transparent;")
        add_btn = QPushButton("Add")
        add_btn.setFixedSize(70, 28)
        add_btn.setStyleSheet(
            "QPushButton { background: #3b82f6; color: white; border-radius: 4px; }"
            "QPushButton:hover { background: #2563eb; }"
        )
        add_btn.clicked.connect(self._browse_add)
        clear_btn = QPushButton("Clear")
        clear_btn.setFixedSize(70, 28)
        clear_btn.clicked.connect(self._clear_queue)
        hdr_lay.addWidget(title, 1)
        hdr_lay.addWidget(add_btn)
        hdr_lay.addSpacing(6)
        hdr_lay.addWidget(clear_btn)
        pc_lay.addWidget(hdr)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; }")
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._queue_widget = QWidget()
        self._queue_widget.setStyleSheet("background: transparent;")
        self._queue_layout = QVBoxLayout(self._queue_widget)
        self._queue_layout.setContentsMargins(8, 0, 8, 0)
        self._queue_layout.setSpacing(6)
        self._queue_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self._empty_label = QLabel("Drop videos here or click Add")
        self._empty_label.setStyleSheet("color: #555; background: transparent;")
        self._empty_label.setFont(QFont("Segoe UI", 11))
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._queue_layout.addWidget(self._empty_label)

        scroll.setWidget(self._queue_widget)
        pc_lay.addWidget(scroll, 1)
        left_lay.addWidget(pool_card, 1)

        # --- Video Info card ---
        info_card = Card()
        ic_lay    = QVBoxLayout(info_card)
        ic_lay.setContentsMargins(14, 12, 14, 12)
        ic_lay.setSpacing(6)
        info_title = QLabel("Video Info")
        info_title.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        info_title.setStyleSheet("background: transparent;")
        ic_lay.addWidget(info_title)

        grid_w  = QWidget()
        grid_l  = QGridLayout(grid_w)
        grid_l.setContentsMargins(0, 0, 0, 0)
        grid_l.setSpacing(6)
        self.info_labels: dict[str, QLabel] = {}
        fields = [("Duration", "duration"), ("Resolution", "resolution"),
                  ("File Size", "size"),    ("Frame Rate", "fps")]
        for i, (lbl_text, key) in enumerate(fields):
            r, c = i // 2, (i % 2) * 2
            lbl = QLabel(lbl_text + ":")
            lbl.setStyleSheet("color: #888; background: transparent;")
            lbl.setFixedWidth(80)
            val = QLabel("—")
            val.setStyleSheet("background: transparent;")
            grid_l.addWidget(lbl, r, c)
            grid_l.addWidget(val, r, c + 1)
            self.info_labels[key] = val
        ic_lay.addWidget(grid_w)
        left_lay.addWidget(info_card)

        layout.addWidget(left, 1)

    def _build_preview_panel(self, layout: QHBoxLayout):
        card     = Card()
        card.setMinimumWidth(620)
        card_lay = QVBoxLayout(card)
        card_lay.setContentsMargins(14, 12, 14, 8)
        card_lay.setSpacing(6)

        hdr     = QWidget()
        hdr_lay = QHBoxLayout(hdr)
        hdr_lay.setContentsMargins(0, 0, 0, 0)
        title = QLabel("Preview")
        title.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        title.setStyleSheet("background: transparent;")

        self._pause_btn = IconButton("pause")
        self._pause_btn.clicked.connect(self._toggle_pause)

        hdr_lay.addWidget(title, 1)
        hdr_lay.addWidget(self._pause_btn)
        card_lay.addWidget(hdr)

        self._video_container = VideoContainer()
        card_lay.addWidget(self._video_container, 1)

        layout.addWidget(card, 2)

    def _build_meter_strip(self, layout: QHBoxLayout):
        meter_w = AudioMeter.PAD_L + 2 * AudioMeter.CH_W + AudioMeter.CH_GAP + AudioMeter.PAD_R
        card = Card()
        card.setFixedWidth(meter_w + 20)  # meter + 10px side margins
        card_lay = QVBoxLayout(card)
        card_lay.setContentsMargins(10, 12, 10, 8)
        card_lay.setSpacing(6)

        self._mute_btn = IconButton("vol_on")
        self._mute_btn.clicked.connect(self._toggle_mute)
        card_lay.addWidget(self._mute_btn, alignment=Qt.AlignmentFlag.AlignHCenter)

        self._audio_meter = AudioMeter(channels=2)
        sp = self._audio_meter.sizePolicy()
        sp.setVerticalPolicy(QSizePolicy.Policy.Expanding)
        self._audio_meter.setSizePolicy(sp)
        card_lay.addWidget(self._audio_meter, 1, Qt.AlignmentFlag.AlignHCenter)

        self._meter_strip = card
        layout.addWidget(card)

    def _build_bottom_panel(self, layout: QVBoxLayout):
        tabs = QTabWidget()

        trim_tab = QWidget()
        self._build_trim_tab(trim_tab)
        tabs.addTab(trim_tab, "Trim")

        audio_tab = QWidget()
        self._build_audio_tab(audio_tab)
        tabs.addTab(audio_tab, "Audio")

        compress_tab = QWidget()
        self._build_compress_tab(compress_tab)
        tabs.addTab(compress_tab, "Compress")

        tabs.setCurrentIndex(0)
        layout.addWidget(tabs, 1)

    def _build_trim_tab(self, parent: QWidget):
        lay = QVBoxLayout(parent)
        lay.setContentsMargins(8, 6, 8, 8)
        lay.setSpacing(4)

        self._trim_bar = OverviewBar()
        self._trim_bar.trimChanged.connect(self._on_trim_change)
        self._trim_bar.seeked.connect(self._on_seek)
        lay.addWidget(self._trim_bar)

        self._filmstrip = FilmstripTimeline()
        self._filmstrip.seeked.connect(self._on_seek)
        lay.addWidget(self._filmstrip, 1)

    def _build_audio_tab(self, parent: QWidget):
        lay = QVBoxLayout(parent)
        lay.setContentsMargins(8, 10, 8, 8)
        lay.setSpacing(8)

        # ── Single horizontal control strip ───────────────────────────
        ctrl = Card(color="#252525", radius=6)
        ctrl.setFixedHeight(46)
        row  = QHBoxLayout(ctrl)
        row.setContentsMargins(16, 0, 16, 0)
        row.setSpacing(0)

        def _sep():
            s = QWidget()
            s.setFixedSize(1, 20)
            s.setStyleSheet("background: #444;")
            return s

        def _cap(text):
            l = QLabel(text)
            l.setStyleSheet("color: #666; font-size: 11px;")
            return l

        SLIDER_SS = (
            "QSlider::groove:horizontal{height:4px;background:#404040;border-radius:2px;}"
            "QSlider::sub-page:horizontal{background:#3b82f6;border-radius:2px;}"
            "QSlider::handle:horizontal{background:#3b82f6;border-radius:6px;"
            "width:12px;height:12px;margin:-4px 0;}"
            "QSlider::handle:horizontal:disabled{background:#555;}"
            "QSlider::sub-page:horizontal:disabled{background:#1e3060;}"
        )

        # Volume
        row.addWidget(_cap("Volume"))
        row.addSpacing(10)
        self._vol_slider = QSlider(Qt.Orientation.Horizontal)
        self._vol_slider.setRange(-150, 150)  # each unit = 0.2 dB  →  ±30 dB
        self._vol_slider.setValue(0)
        self._vol_slider.setFixedWidth(300)
        self._vol_slider.setEnabled(False)
        self._vol_slider.setStyleSheet(SLIDER_SS)
        self._vol_slider.valueChanged.connect(self._on_volume_change)
        row.addWidget(self._vol_slider)
        row.addSpacing(10)
        self._vol_label = NumberEdit("—")
        self._vol_label.setFixedWidth(72)
        self._vol_label.setEnabled(False)
        self._vol_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._vol_label.setStyleSheet(
            "QLineEdit { background: #1e1e1e; border: 1px solid #444; border-radius: 4px;"
            " color: #e0e0e0; font-size: 12px; padding: 0 4px; }"
            "QLineEdit:focus { border-color: #3b82f6; }"
            "QLineEdit:disabled { color: #555; border-color: #333; }"
        )
        self._vol_label.editingFinished.connect(self._on_vol_entry_edited)
        self._vol_label.spacePressed.connect(self._toggle_pause)
        row.addWidget(self._vol_label)

        row.addSpacing(14); row.addWidget(_sep()); row.addSpacing(14)

        # Normalize
        self._normalize_cb = QCheckBox("Normalize")
        self._normalize_cb.setEnabled(False)
        self._normalize_cb.toggled.connect(self._on_normalize_change)
        row.addWidget(self._normalize_cb)

        row.addSpacing(14); row.addWidget(_sep()); row.addSpacing(14)

        # Bitrate (global)
        row.addWidget(_cap("Bitrate"))
        row.addSpacing(8)
        self._audio_bitrate = QComboBox()
        self._audio_bitrate.addItems(["64", "96", "128", "192"])
        self._audio_bitrate.setCurrentText("128")
        self._audio_bitrate.setFixedWidth(76)
        row.addWidget(self._audio_bitrate)
        row.addSpacing(5)
        row.addWidget(_cap("kbps"))

        row.addSpacing(14); row.addWidget(_sep()); row.addSpacing(14)

        # Strip Audio
        self._strip_audio_cb = QCheckBox("Strip Audio")
        self._strip_audio_cb.setEnabled(False)
        self._strip_audio_cb.toggled.connect(self._on_strip_audio_change)
        row.addWidget(self._strip_audio_cb)

        row.addStretch()
        lay.addWidget(ctrl)

        # ── Waveform fills all remaining space ─────────────────────────
        self._waveform = WaveformView()
        self._waveform.seeked.connect(self._on_seek)
        lay.addWidget(self._waveform, 1)

    def _build_compress_tab(self, parent: QWidget):
        lay = QVBoxLayout(parent)
        lay.setContentsMargins(8, 10, 8, 8)
        lay.setSpacing(8)

        lbl_style = "color: #888; font-size: 12px;"

        def _lbl(text):
            l = QLabel(text)
            l.setStyleSheet(lbl_style)
            return l

        # ---- Single top row: target size | separator | output folder ----
        top = QWidget()
        top.setFixedHeight(34)
        top_lay = QHBoxLayout(top)
        top_lay.setContentsMargins(4, 0, 4, 0)
        top_lay.setSpacing(6)

        top_lay.addWidget(_lbl("Target Size:"))
        self._target_group = QButtonGroup(self)
        self._preset_btns: dict[int, QRadioButton] = {}
        for label, mb in DISCORD_PRESETS:
            rb = QRadioButton(label)
            rb.setProperty("mb_value", mb)
            self._target_group.addButton(rb)
            self._preset_btns[mb] = rb
            top_lay.addWidget(rb)
        self._preset_btns[8].setChecked(True)

        self._custom_rb = QRadioButton("Custom:")
        self._custom_rb.toggled.connect(self._on_target_change)
        self._target_group.addButton(self._custom_rb)
        top_lay.addWidget(self._custom_rb)

        self._custom_entry = QLineEdit()
        self._custom_entry.setPlaceholderText("MB")
        self._custom_entry.setFixedWidth(52)
        self._custom_entry.setEnabled(False)
        top_lay.addWidget(self._custom_entry)

        top_lay.addSpacing(12)
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setStyleSheet("color: #444;")
        top_lay.addWidget(sep)
        top_lay.addSpacing(12)

        top_lay.addWidget(_lbl("Output:"))
        self._output_entry = QLineEdit()
        self._output_entry.setPlaceholderText("Select output folder…")
        self._output_entry.setReadOnly(True)
        top_lay.addWidget(self._output_entry, 1)

        self._browse_btn = QPushButton("Browse")
        self._browse_btn.setFixedSize(72, 28)
        self._browse_btn.clicked.connect(self._browse_output)
        top_lay.addWidget(self._browse_btn)

        lay.addWidget(top)

        # ---- Action card fills the remaining space ----
        action = Card(color="#252525", radius=6)
        action_lay = QVBoxLayout(action)
        action_lay.setContentsMargins(16, 14, 16, 14)
        action_lay.setSpacing(12)

        action_lay.addStretch(1)

        btn_row = QWidget()
        btn_lay = QHBoxLayout(btn_row)
        btn_lay.setContentsMargins(0, 0, 0, 0)
        btn_lay.setSpacing(10)

        self.compress_btn = QPushButton("Compress Videos")
        self.compress_btn.setFixedHeight(44)
        self.compress_btn.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        self.compress_btn.setStyleSheet(
            "QPushButton { background: #3b82f6; color: white; border-radius: 6px; padding: 0 16px; }"
            "QPushButton:hover { background: #2563eb; }"
            "QPushButton:disabled { background: #1e3a5f; color: #555; }"
        )
        self.compress_btn.clicked.connect(self._start_queue)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setFixedSize(90, 44)
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self._cancel)

        btn_lay.addWidget(self.compress_btn, 1)
        btn_lay.addWidget(self.cancel_btn)
        action_lay.addWidget(btn_row)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 1000)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(10)
        self.progress_bar.setTextVisible(False)
        action_lay.addWidget(self.progress_bar)

        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet("color: #888; font-size: 12px;")
        action_lay.addWidget(self.status_label)

        action_lay.addStretch(1)

        lay.addWidget(action, 1)

    # ------------------------------------------------------------------ mpv

    def _init_player(self):
        if not MPV_AVAILABLE or not self._video_container:
            return
        try:
            self._video_container.render_widget.show()
            wid = int(self._video_container.render_widget.winId())
            self._player = mpv.MPV(
                keep_open=True, idle=True, loop_file='inf',
                osc=False, osd_level=0, log_handler=print, loglevel='warn',
                volume_max=1000,  # allows up to +20 dB (mpv hard ceiling is 1000)
            )
            self._player['wid'] = str(wid)
            self._player.observe_property("time-pos", self._on_mpv_time_pos)
            self._player.observe_property("pause",    self._on_mpv_pause)
        except Exception as e:
            print(f"mpv init error: {e}")
            self._player = None

    def _analyze_audio(self, row: QueueRow, info: VideoInfo):
        RATE     = 22050
        CHANNELS = 2
        fps      = info.fps if info.fps > 0 else 30.0
        row.analysis_fps = fps
        CHUNK       = max(1, int(RATE / fps))
        CHUNK_BYTES = CHUNK * CHANNELS * 2
        cmd = [FFMPEG, "-y", "-i", row.path,
               "-vn", "-ar", str(RATE), "-ac", str(CHANNELS),
               "-f", "s16le", "pipe:1"]
        try:
            proc   = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            levels: list[tuple[float, float]] = []
            while True:
                data = proc.stdout.read(CHUNK_BYTES)
                if len(data) < CHUNK_BYTES:
                    break
                buf   = array.array("h", data)
                l_ch  = buf[0::2]
                r_ch  = buf[1::2]
                levels.append((
                    max(abs(s) for s in l_ch) / 32768.0,
                    max(abs(s) for s in r_ch) / 32768.0,
                ))
            proc.wait()
            row.audio_levels = levels
            # If this clip is currently selected, refresh the waveform now
            if self._waveform and self._selected_row is row and row.info:
                dur = row.info.duration
                end = row.trim_end if row.trim_end is not None else dur
                self._waveform.set_clip(
                    levels, row.analysis_fps, dur, row.trim_start, end)
                self._waveform.set_volume_db(row.volume_db)
                self._waveform.set_normalize(row.normalize)
        except Exception as e:
            print(f"audio analysis error: {e}")

    def _on_mpv_time_pos(self, _name, value):
        if value is not None:
            try:
                self._mpv_bridge.time_pos.emit(float(value))
            except RuntimeError:
                pass

    def _on_mpv_pause(self, _name, value):
        if value is not None:
            try:
                self._mpv_bridge.paused.emit(bool(value))
            except RuntimeError:
                pass

    def _on_playhead_update(self, t: float):
        self._current_t = t
        self._trim_bar.set_playhead(t)
        if self._filmstrip:
            self._filmstrip.set_playhead(t)
        if self._waveform:
            self._waveform.set_playhead(t)
        if self._audio_meter and self._selected_row:
            lvs = self._selected_row.audio_levels
            idx = int(t * self._selected_row.analysis_fps)
            if lvs and 0 <= idx < len(lvs):
                vol  = self._selected_row.volume_db
                db_l = 20 * math.log10(max(lvs[idx][0], 1e-10)) + vol
                db_r = 20 * math.log10(max(lvs[idx][1], 1e-10)) + vol
                def norm(db): return max(0.0, min(1.0, (db + 60) / 60))
                self._audio_meter.update_levels([norm(db_l), norm(db_r)])
            else:
                self._audio_meter.update_levels([0.0, 0.0])

    def _on_pause_update(self, paused: bool):
        self._paused = paused
        if self._pause_btn:
            self._pause_btn.set_icon("play" if paused else "pause")
        if paused and self._audio_meter:
            self._audio_meter.silence()

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.MouseButtonPress:
            fw = self.focusWidget()
            if isinstance(fw, QLineEdit) and fw is not obj:
                fw.clearFocus()
        return False

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._player and self._video_container:
            if not self._resize_paused:
                self._resize_paused      = True
                self._resize_was_playing = not self._paused
                if self._resize_was_playing:
                    try:
                        self._player.pause = True
                    except Exception:
                        pass
                self._video_container.render_widget.hide()
            self._resize_resume_timer.start()

    def _on_resize_done(self):
        if not self._resize_paused:
            return
        self._resize_paused = False
        if self._video_container:
            self._video_container.render_widget.show()
        if self._player and self._resize_was_playing:
            try:
                self._player.pause = False
            except Exception:
                pass

    def _toggle_pause(self):
        if not self._player:
            return
        try:
            self._player.pause = not self._paused
        except Exception:
            pass

    def _toggle_mute(self):
        self._muted = not self._muted
        if self._mute_btn:
            self._mute_btn.set_icon("vol_off" if self._muted else "vol_on")
        if self._player:
            try:
                self._player.mute = self._muted
            except Exception:
                pass

    def _load_video(self, row: QueueRow):
        if not MPV_AVAILABLE or not self._player:
            return
        try:
            self._paused = False
            if self._pause_btn:
                self._pause_btn.set_icon("pause")
            self._player.ab_loop_a = 'no'
            self._player.ab_loop_b = 'no'
            self._player.command('loadfile', row.path)
            self._player.pause = False
            self._player.mute  = self._muted
            QTimer.singleShot(350, lambda r=row: self._apply_trim(r))
        except Exception as e:
            print(f"mpv play error: {e}")

    def _apply_trim(self, row: QueueRow):
        if not self._player or self._selected_row is not row:
            return
        try:
            start     = row.trim_start
            end       = row.trim_end if row.trim_end is not None else (row.info.duration if row.info else None)
            has_trim  = start > 0.0 or (end is not None and row.info and end < row.info.duration - 0.05)
            if has_trim:
                if start > 0.0:
                    self._player.command("seek", str(start), "absolute", "exact")
                self._player.ab_loop_a = start
                if end is not None:
                    self._player.ab_loop_b = end
            else:
                self._player.ab_loop_a = 'no'
                self._player.ab_loop_b = 'no'
        except Exception as e:
            print(f"_apply_trim error: {e}")

    # ------------------------------------------------------------------ controls

    def _on_trim_change(self, start: float, end: float):
        if self._selected_row:
            self._selected_row.trim_start = start
            self._selected_row.trim_end   = end
        if self._filmstrip:
            self._filmstrip.set_trim(start, end)
        if self._waveform:
            self._waveform.set_trim(start, end)
        if self._player:
            try:
                self._player.ab_loop_a = start
                self._player.ab_loop_b = end
            except Exception:
                pass

    def _on_seek(self, t: float):
        self._trim_bar.set_playhead(t)
        if self._filmstrip:
            self._filmstrip.set_playhead(t)
        if self._player:
            try:
                self._player.command("seek", str(t), "absolute", "exact")
            except Exception:
                pass

    def _on_volume_change(self, value: int):
        db   = value / 5.0
        sign = "+" if db > 0 else ""
        self._vol_label.setText(f"{sign}{db:.1f} dB")
        if self._selected_row:
            self._selected_row.volume_db = db
        if self._player:
            try:
                self._player.volume = min(1000.0, 100.0 * (10.0 ** (db * 0.3 / 20.0)))
            except Exception:
                pass
        # Push immediate meter update (doesn't wait for next time-pos tick)
        if self._audio_meter and self._selected_row:
            row = self._selected_row
            lvs = row.audio_levels
            idx = int(self._current_t * row.analysis_fps)
            if lvs and 0 <= idx < len(lvs):
                db_l = 20 * math.log10(max(lvs[idx][0], 1e-10)) + db
                db_r = 20 * math.log10(max(lvs[idx][1], 1e-10)) + db
                def norm(x): return max(0.0, min(1.0, (x + 60) / 60))
                self._audio_meter.update_levels([norm(db_l), norm(db_r)])
        if self._waveform:
            self._waveform.set_volume_db(db)

    def _on_vol_entry_edited(self):
        text = self._vol_label.text().replace("dB", "").replace(" ", "").strip()
        try:
            db = max(-30.0, min(30.0, float(text)))
        except ValueError:
            db = self._vol_slider.value() / 5.0
        self._vol_slider.setValue(int(round(db * 5)))

    def _on_normalize_change(self, checked: bool):
        if self._selected_row:
            self._selected_row.normalize = checked
        if self._waveform:
            self._waveform.set_normalize(checked)

    def _on_strip_audio_change(self, checked: bool):
        if self._selected_row:
            self._selected_row.strip_audio = checked
        # Toggle dependent controls
        self._vol_slider.setEnabled(not checked)
        self._vol_label.setEnabled(not checked)
        self._vol_label.setText("—" if checked else self._vol_label.text())
        if self._normalize_cb:
            self._normalize_cb.setEnabled(not checked)
        if self._player:
            try:
                if checked:
                    self._player.volume = 0.0
                elif self._selected_row:
                    self._player.volume = min(1000.0,
                        100.0 * (10.0 ** (self._selected_row.volume_db * 0.3 / 20.0)))
            except Exception:
                pass

    def _load_middle(self, row: QueueRow):
        stripped = row.strip_audio
        # Block signals on checkboxes while loading so their handlers don't
        # fire side-effects (e.g. _on_strip_audio_change re-enabling the slider).
        if self._normalize_cb:
            self._normalize_cb.blockSignals(True)
            self._normalize_cb.setChecked(row.normalize)
            self._normalize_cb.blockSignals(False)
            self._normalize_cb.setEnabled(not stripped)
        if self._strip_audio_cb:
            self._strip_audio_cb.blockSignals(True)
            self._strip_audio_cb.setChecked(stripped)
            self._strip_audio_cb.blockSignals(False)
            self._strip_audio_cb.setEnabled(True)
        # Block slider signals too — setValue fires valueChanged which would
        # overwrite row.volume_db with a rounded value before we've restored it.
        self._vol_slider.blockSignals(True)
        self._vol_slider.setValue(int(round(row.volume_db * 5)))
        self._vol_slider.blockSignals(False)
        self._vol_slider.setEnabled(not stripped)
        self._vol_label.setEnabled(not stripped)
        db   = round(row.volume_db, 1)
        sign = "+" if db > 0 else ""
        self._vol_label.setText(f"{sign}{db:.1f} dB" if not stripped else "—")
        if self._player:
            try:
                self._player.volume = min(1000.0, 100.0 * (10.0 ** (row.volume_db * 0.3 / 20.0)))
            except Exception:
                pass

        if self._waveform:
            if row.info and row.audio_levels:
                dur = row.info.duration
                end = row.trim_end if row.trim_end is not None else dur
                self._waveform.set_clip(
                    row.audio_levels, row.analysis_fps, dur, row.trim_start, end)
                self._waveform.set_volume_db(row.volume_db)
                self._waveform.set_normalize(row.normalize)
            else:
                self._waveform.reset()

        if row.info:
            dur = row.info.duration
            end = row.trim_end if row.trim_end is not None else dur
            self._trim_bar.set_clip(dur, row.trim_start, end)
            if self._filmstrip:
                self._filmstrip.set_clip(row.path, dur, row.trim_start, end)
        else:
            self._trim_bar.reset()
            if self._filmstrip:
                self._filmstrip.reset()
        self._load_video(row)

    def _clear_middle(self):
        self._vol_slider.blockSignals(True)
        self._vol_slider.setValue(0)
        self._vol_slider.blockSignals(False)
        self._vol_slider.setEnabled(False)
        self._vol_label.setEnabled(False)
        self._vol_label.setText("—")
        if self._normalize_cb:
            self._normalize_cb.blockSignals(True)
            self._normalize_cb.setChecked(False)
            self._normalize_cb.blockSignals(False)
            self._normalize_cb.setEnabled(False)
        if self._strip_audio_cb:
            self._strip_audio_cb.blockSignals(True)
            self._strip_audio_cb.setChecked(False)
            self._strip_audio_cb.blockSignals(False)
            self._strip_audio_cb.setEnabled(False)
        if self._waveform:
            self._waveform.reset()
        self._trim_bar.reset()
        if self._filmstrip:
            self._filmstrip.reset()
        self._paused = False
        if self._pause_btn:
            self._pause_btn.set_icon("pause")
        if self._audio_meter:
            self._audio_meter.silence()
        if self._player:
            try:
                self._player.command("stop")
            except Exception:
                pass

    # ------------------------------------------------------------------ queue

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if Path(path).suffix.lower() in VIDEO_EXT:
                if not any(r.path == path for r in self._queue_rows):
                    self._add_to_queue(path)

    def _browse_add(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Select Videos", "",
            "Video files (*.mp4 *.mov *.avi *.mkv *.webm *.flv *.wmv *.m4v *.ts);;All files (*.*)"
        )
        for path in paths:
            if not any(r.path == path for r in self._queue_rows):
                self._add_to_queue(path)

    def _add_to_queue(self, path: str):
        self._empty_label.hide()
        row = QueueRow(path)
        row.rowSelected.connect(self._select_row)
        row.rowRemoved.connect(self._remove_from_queue)
        self._queue_layout.addWidget(row)
        self._queue_rows.append(row)

        sig = self._sig
        def _probe():
            try:
                info = probe_video(path)
                sig.probe_done.emit(row, info)
                threading.Thread(target=self._analyze_audio, args=(row, info), daemon=True).start()
            except Exception:
                sig.probe_error.emit(row)
        threading.Thread(target=_probe, daemon=True).start()

    def _on_probe_done(self, row: QueueRow, info: VideoInfo):
        row.set_info(info)
        row.status = "Ready"
        if self._selected_row is row:
            self._populate_stats(info)
            self._load_middle(row)

    def _on_probe_error(self, row: QueueRow):
        row.status = "Error"
        row.meta_lbl.setText("Could not read file")

    def _remove_from_queue(self, path: str):
        row = next((r for r in self._queue_rows if r.path == path), None)
        if not row or row.status == "Compressing":
            return
        if self._selected_row is row:
            self._selected_row = None
            self._clear_stats()
            self._clear_middle()
        row.deleteLater()
        self._queue_rows.remove(row)
        if not self._queue_rows:
            self._empty_label.show()

    def _clear_queue(self):
        for row in list(self._queue_rows):
            if row.status != "Compressing":
                row.deleteLater()
                self._queue_rows.remove(row)
        self._selected_row = None
        self._clear_stats()
        self._clear_middle()
        if not self._queue_rows:
            self._empty_label.show()

    def _select_row(self, row: QueueRow):
        if self._selected_row:
            self._selected_row.set_selected(False)
        self._selected_row = row
        row.set_selected(True)
        if row.info:
            self._populate_stats(row.info)
        else:
            self._clear_stats()
        self._load_middle(row)

    def _populate_stats(self, info: VideoInfo):
        mins = int(info.duration // 60)
        secs = int(info.duration % 60)
        self.info_labels["duration"].setText(f"{mins}:{secs:02d}")
        self.info_labels["resolution"].setText(f"{info.width} × {info.height}")
        self.info_labels["size"].setText(f"{info.size_bytes / 1024 / 1024:.1f} MB")
        self.info_labels["fps"].setText(f"{info.fps:.2f} fps")

    def _clear_stats(self):
        for lbl in self.info_labels.values():
            lbl.setText("—")

    # ------------------------------------------------------------------ compression

    def _browse_output(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Output Folder")
        if folder:
            self._output_folder = folder
            self._output_entry.setText(folder)

    def _on_target_change(self, checked: bool):
        self._custom_entry.setEnabled(checked)

    def _get_target_mb(self) -> Optional[float]:
        if self._custom_rb.isChecked():
            try:
                return float(self._custom_entry.text())
            except ValueError:
                return None
        for btn in self._target_group.buttons():
            if btn.isChecked() and btn is not self._custom_rb:
                return float(btn.property("mb_value"))
        return None

    def _get_target_suffix(self) -> str:
        if self._custom_rb.isChecked():
            return "_compressed"
        for btn in self._target_group.buttons():
            if btn.isChecked() and btn is not self._custom_rb:
                return f"_{int(btn.property('mb_value'))}mb"
        return "_compressed"

    def _set_queue_controls_enabled(self, enabled: bool):
        """Enable/disable settings that must not change during compression."""
        for btn in self._preset_btns.values():
            btn.setEnabled(enabled)
        self._custom_rb.setEnabled(enabled)
        self._custom_entry.setEnabled(enabled and self._custom_rb.isChecked())
        self._output_entry.setEnabled(enabled)
        if self._browse_btn:
            self._browse_btn.setEnabled(enabled)
        self._audio_bitrate.setEnabled(enabled)
        # Per-clip controls — honour strip_audio state when re-enabling
        row = self._selected_row
        strip = row.strip_audio if row else True
        self._vol_slider.setEnabled(enabled and not strip)
        self._vol_label.setEnabled(enabled and not strip)
        if self._normalize_cb:
            self._normalize_cb.setEnabled(enabled and not strip)
        if self._strip_audio_cb:
            self._strip_audio_cb.setEnabled(enabled and row is not None)

    def _start_queue(self):
        pending = [r for r in self._queue_rows if r.status == "Ready"]
        if not pending:
            QMessageBox.warning(self, "No Videos", "Add at least one video to compress.")
            return
        if self._get_target_mb() is None:
            QMessageBox.critical(self, "Error", "Enter a valid custom size in MB.")
            return
        if not self._output_folder:
            QMessageBox.warning(self, "No Output Folder", "Please select an output folder.")
            return
        self._compressing  = True
        self._queue_total  = len(pending)
        self._queue_done   = 0
        self._set_queue_controls_enabled(False)
        self.compress_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.progress_bar.setValue(0)
        self._compress_next()

    def _compress_next(self):
        if not self._compressing:
            self._on_queue_done()
            return
        pending = [r for r in self._queue_rows if r.status == "Ready"]
        if not pending:
            self._on_queue_done()
            return
        row = pending[0]
        row.status = "Compressing"

        if row.info is None:
            sig = self._sig
            def _probe_then():
                try:
                    info = probe_video(row.path)
                    sig.probe_done.emit(row, info)
                    QTimer.singleShot(0, lambda: self._run_compression(row))
                except Exception:
                    sig.probe_error.emit(row)
                    sig.compress_finished.emit()
            threading.Thread(target=_probe_then, daemon=True).start()
        else:
            self._run_compression(row)

    def _run_compression(self, row: QueueRow):
        target_mb     = self._get_target_mb()
        include_audio = not row.strip_audio
        audio_kbps    = int(self._audio_bitrate.currentText())
        start_time    = row.trim_start
        end_time      = row.trim_end
        effective_dur = max(0.1,
            (end_time - start_time) if end_time is not None
            else (row.info.duration - start_time))
        vbr = calculate_video_bitrate(target_mb, effective_dur, audio_kbps, include_audio)

        stem   = Path(row.path).stem
        dst    = str(Path(self._output_folder) / f"{stem}{self._get_target_suffix()}.mp4")

        if vbr < 10:
            row.status = "Error"
            self.status_label.setText(f"Skipped {Path(row.path).name} — target too small for duration")
            self._sig.compress_finished.emit()
            return

        sig = self._sig
        self.encoder.start(
            src=row.path, dst=dst, vbr=vbr,
            abr=audio_kbps if include_audio else 0,
            duration=effective_dur,
            on_progress=lambda p: sig.compress_progress.emit(p),
            on_status=lambda s: sig.compress_status.emit(s),
            on_done=lambda _path, _kb, r=row: sig.compress_row_done.emit(r),
            on_finished=lambda: sig.compress_finished.emit(),
            start_time=start_time,
            end_time=end_time,
            volume_db=row.volume_db,
            normalize=row.normalize,
        )

    def _on_compress_progress(self, p: float):
        if self._queue_total > 0:
            global_p = (self._queue_done + p) / self._queue_total
        else:
            global_p = p
        self.progress_bar.setValue(int(global_p * 1000))

    def _on_compress_status(self, s: str):
        if self._queue_total > 1:
            self.status_label.setText(
                f"[{self._queue_done + 1}/{self._queue_total}]  {s}"
            )
        else:
            self.status_label.setText(s)

    def _on_compress_row_done(self, row: QueueRow):
        row.status = "Done"
        self._queue_done += 1
        self.progress_bar.setValue(int(self._queue_done / max(1, self._queue_total) * 1000))

    def _cancel(self):
        self._compressing = False
        self.encoder.cancel()
        for r in self._queue_rows:
            if r.status == "Compressing":
                r.status = "Cancelled"
        self._set_queue_controls_enabled(True)
        self.compress_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)

    def _on_queue_done(self):
        self._compressing = False
        self._set_queue_controls_enabled(True)
        self.compress_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        done  = sum(1 for r in self._queue_rows if r.status == "Done")
        total = len(self._queue_rows)
        self.status_label.setText(f"Done  —  {done} of {total} videos compressed")

    def closeEvent(self, event):
        self.encoder.cancel()
        if self._player:
            try:
                self._player.terminate()
            except Exception:
                pass
        event.accept()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Discord Video Compressor")
    apply_dark_theme(app)
    app.setStyleSheet(STYLESHEET)
    window = CompressorWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
