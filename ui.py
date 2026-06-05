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
from PyQt6.QtCore import Qt, QTimer, QObject, pyqtSignal, QPoint, QRect
from PyQt6.QtGui import (
    QPainter, QColor, QBrush, QPalette, QFont, QKeySequence, QShortcut,
    QPixmap, QPolygon,
)

try:
    import mpv
    MPV_AVAILABLE = True
except Exception:
    MPV_AVAILABLE = False

from video import VideoInfo, probe_video
from encoder import Encoder, ffmpeg_available, calculate_video_bitrate

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
# Trim bar
# ---------------------------------------------------------------------------

class OverviewBar(QWidget):
    """Compact full-clip strip: trim handles + moving playhead."""
    trimChanged = pyqtSignal(float, float)
    seeked      = pyqtSignal(float)

    H    = 32
    GRAB = 8

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
        # Inactive regions
        p.fillRect(0,  0, lx,     h, QColor("#1a1a1a"))
        p.fillRect(rx, 0, w - rx, h, QColor("#1a1a1a"))
        # Active region
        p.fillRect(lx, 0, rx - lx, h, QColor("#1e3a5f"))
        # Trim handles
        hc = QColor("#93c5fd")
        p.fillRect(lx,     0, 3, h, hc)
        p.fillRect(rx - 3, 0, 3, h, hc)
        # Playhead
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
            "ffmpeg", "-i", path,
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
        self._pause_btn: Optional[QPushButton]             = None
        self._mute_btn:  Optional[QPushButton]             = None
        self._trim_bar:  Optional[OverviewBar]             = None
        self._filmstrip: Optional[FilmstripTimeline]       = None

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
        card.setFixedWidth(620)
        card_lay = QVBoxLayout(card)
        card_lay.setContentsMargins(14, 12, 14, 8)
        card_lay.setSpacing(6)

        hdr     = QWidget()
        hdr_lay = QHBoxLayout(hdr)
        hdr_lay.setContentsMargins(0, 0, 0, 0)
        title = QLabel("Preview")
        title.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        title.setStyleSheet("background: transparent;")

        self._pause_btn = QPushButton("⏸")
        self._pause_btn.setFixedSize(36, 28)
        self._pause_btn.setStyleSheet(
            "QPushButton { background: #2c2c2c; border: 1px solid #505050; border-radius: 5px; font-size: 14px; color: #e0e0e0; }"
            "QPushButton:hover { background: #3d3d3d; border-color: #707070; }"
            "QPushButton:pressed { background: #222; }"
        )
        self._pause_btn.clicked.connect(self._toggle_pause)

        hdr_lay.addWidget(title, 1)
        hdr_lay.addWidget(self._pause_btn)
        card_lay.addWidget(hdr)

        self._video_container = VideoContainer()
        card_lay.addWidget(self._video_container, 1)

        layout.addWidget(card)

    def _build_meter_strip(self, layout: QHBoxLayout):
        meter_w = AudioMeter.PAD_L + 2 * AudioMeter.CH_W + AudioMeter.CH_GAP + AudioMeter.PAD_R
        card = Card()
        card.setFixedWidth(meter_w + 20)  # meter + 10px side margins
        card_lay = QVBoxLayout(card)
        card_lay.setContentsMargins(10, 12, 10, 8)
        card_lay.setSpacing(6)

        self._mute_btn = QPushButton("🔊")
        self._mute_btn.setFixedSize(36, 28)
        self._mute_btn.setStyleSheet(
            "QPushButton { background: #2c2c2c; border: 1px solid #505050; border-radius: 5px; font-size: 14px; color: #e0e0e0; }"
            "QPushButton:hover { background: #3d3d3d; border-color: #707070; }"
            "QPushButton:pressed { background: #222; }"
        )
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
        lay.setContentsMargins(8, 12, 8, 8)
        lay.setAlignment(Qt.AlignmentFlag.AlignTop)

        row     = QWidget()
        row_lay = QHBoxLayout(row)
        row_lay.setContentsMargins(4, 0, 0, 0)

        lbl = QLabel("Volume Adjustment:")
        lbl.setStyleSheet("color: #888;")
        lbl.setFont(QFont("Segoe UI", 12))
        row_lay.addWidget(lbl)
        row_lay.addSpacing(14)

        self._vol_slider = QSlider(Qt.Orientation.Horizontal)
        self._vol_slider.setRange(-300, 300)  # tenths of dB
        self._vol_slider.setValue(0)
        self._vol_slider.setFixedWidth(220)
        self._vol_slider.setEnabled(False)
        self._vol_slider.valueChanged.connect(self._on_volume_change)
        row_lay.addWidget(self._vol_slider)
        row_lay.addSpacing(12)

        self._vol_label = QLabel("—")
        self._vol_label.setFixedWidth(68)
        self._vol_label.setFont(QFont("Segoe UI", 12))
        self._vol_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        row_lay.addWidget(self._vol_label)
        row_lay.addStretch()

        lay.addWidget(row)

    def _build_compress_tab(self, parent: QWidget):
        lay = QVBoxLayout(parent)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)
        lay.setAlignment(Qt.AlignmentFlag.AlignTop)

        lbl_style = "color: #888; font-size: 12px;"
        LW = 110

        def _lbl(text):
            l = QLabel(text)
            l.setStyleSheet(lbl_style)
            l.setFixedWidth(LW)
            return l

        # Target size
        r1     = QWidget()
        r1_lay = QHBoxLayout(r1)
        r1_lay.setContentsMargins(4, 0, 0, 0)
        r1_lay.addWidget(_lbl("Target Size:"))

        self._target_group = QButtonGroup(self)
        self._preset_btns: dict[int, QRadioButton] = {}
        for label, mb in DISCORD_PRESETS:
            rb = QRadioButton(label)
            rb.setProperty("mb_value", mb)
            self._target_group.addButton(rb)
            self._preset_btns[mb] = rb
            r1_lay.addWidget(rb)
        self._preset_btns[8].setChecked(True)

        self._custom_rb = QRadioButton("Custom:")
        self._custom_rb.toggled.connect(self._on_target_change)
        self._target_group.addButton(self._custom_rb)
        r1_lay.addWidget(self._custom_rb)

        self._custom_entry = QLineEdit()
        self._custom_entry.setPlaceholderText("MB")
        self._custom_entry.setFixedWidth(60)
        self._custom_entry.setEnabled(False)
        r1_lay.addWidget(self._custom_entry)
        r1_lay.addStretch()
        lay.addWidget(r1)

        # Audio
        r2     = QWidget()
        r2_lay = QHBoxLayout(r2)
        r2_lay.setContentsMargins(4, 0, 0, 0)
        r2_lay.addWidget(_lbl("Audio:"))

        self._audio_cb = QCheckBox("Include Audio")
        self._audio_cb.setChecked(True)
        r2_lay.addWidget(self._audio_cb)
        r2_lay.addSpacing(18)

        br_lbl = QLabel("Bitrate:")
        br_lbl.setStyleSheet("color: #888;")
        r2_lay.addWidget(br_lbl)
        r2_lay.addSpacing(8)

        self._audio_bitrate = QComboBox()
        self._audio_bitrate.addItems(["64", "96", "128", "192"])
        self._audio_bitrate.setCurrentText("128")
        self._audio_bitrate.setFixedWidth(90)
        r2_lay.addWidget(self._audio_bitrate)

        kbps_lbl = QLabel("kbps")
        kbps_lbl.setStyleSheet("color: #888;")
        r2_lay.addWidget(kbps_lbl)
        r2_lay.addStretch()
        lay.addWidget(r2)

        # Output folder
        r3     = QWidget()
        r3_lay = QHBoxLayout(r3)
        r3_lay.setContentsMargins(4, 0, 0, 0)
        r3_lay.addWidget(_lbl("Output Folder:"))

        self._output_entry = QLineEdit()
        self._output_entry.setPlaceholderText("Select output folder…")
        self._output_entry.setReadOnly(True)
        r3_lay.addWidget(self._output_entry, 1)

        browse_btn = QPushButton("Browse")
        browse_btn.setFixedSize(80, 30)
        browse_btn.clicked.connect(self._browse_output)
        r3_lay.addWidget(browse_btn)
        lay.addWidget(r3)

        # Progress + buttons
        r4     = QWidget()
        r4_lay = QVBoxLayout(r4)
        r4_lay.setContentsMargins(LW + 4, 0, 8, 0)
        r4_lay.setSpacing(4)

        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet("color: #888;")
        r4_lay.addWidget(self.status_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 1000)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(8)
        r4_lay.addWidget(self.progress_bar)

        btn_row = QWidget()
        btn_lay = QHBoxLayout(btn_row)
        btn_lay.setContentsMargins(0, 4, 0, 0)
        btn_lay.setSpacing(10)

        self.compress_btn = QPushButton("Compress Videos")
        self.compress_btn.setFixedHeight(38)
        self.compress_btn.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        self.compress_btn.setStyleSheet(
            "QPushButton { background: #3b82f6; color: white; border-radius: 6px; padding: 0 16px; }"
            "QPushButton:hover { background: #2563eb; }"
            "QPushButton:disabled { background: #1e3a5f; color: #555; }"
        )
        self.compress_btn.clicked.connect(self._start_queue)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setFixedSize(90, 38)
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self._cancel)

        btn_lay.addWidget(self.compress_btn)
        btn_lay.addWidget(self.cancel_btn)
        btn_lay.addStretch()
        r4_lay.addWidget(btn_row)
        lay.addWidget(r4)
        lay.addStretch()

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
        cmd = ["ffmpeg", "-y", "-i", row.path,
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
        self._trim_bar.set_playhead(t)
        if self._filmstrip:
            self._filmstrip.set_playhead(t)
        if self._audio_meter and self._selected_row:
            lvs = self._selected_row.audio_levels
            idx = int(t * self._selected_row.analysis_fps)
            if lvs and 0 <= idx < len(lvs):
                db_l = 20 * math.log10(max(lvs[idx][0], 1e-10))
                db_r = 20 * math.log10(max(lvs[idx][1], 1e-10))
                def norm(db): return max(0.0, min(1.0, (db + 60) / 60))
                self._audio_meter.update_levels([norm(db_l), norm(db_r)])
            else:
                self._audio_meter.update_levels([0.0, 0.0])

    def _on_pause_update(self, paused: bool):
        self._paused = paused
        if self._pause_btn:
            self._pause_btn.setText("▶" if paused else "⏸")
        if paused and self._audio_meter:
            self._audio_meter.silence()

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
            self._mute_btn.setText("🔇" if self._muted else "🔊")
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
                self._pause_btn.setText("⏸")
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
        db   = value / 10.0
        sign = "+" if db > 0 else ""
        self._vol_label.setText(f"{sign}{db:.1f} dB")
        if self._selected_row:
            self._selected_row.volume_db = db

    def _load_middle(self, row: QueueRow):
        self._vol_slider.setEnabled(True)
        self._vol_slider.setValue(int(row.volume_db * 10))
        db   = round(row.volume_db, 1)
        sign = "+" if db > 0 else ""
        self._vol_label.setText(f"{sign}{db:.1f} dB")

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
        self._vol_slider.setEnabled(False)
        self._vol_slider.setValue(0)
        self._vol_label.setText("—")
        self._trim_bar.reset()
        if self._filmstrip:
            self._filmstrip.reset()
        self._paused = False
        if self._pause_btn:
            self._pause_btn.setText("⏸")
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
        self._compressing = True
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
        self.progress_bar.setValue(0)

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
        include_audio = self._audio_cb.isChecked()
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
        )

    def _on_compress_progress(self, p: float):
        self.progress_bar.setValue(int(p * 1000))

    def _on_compress_status(self, s: str):
        self.status_label.setText(s)

    def _on_compress_row_done(self, row: QueueRow):
        row.status = "Done"
        self.progress_bar.setValue(1000)

    def _cancel(self):
        self._compressing = False
        self.encoder.cancel()
        for r in self._queue_rows:
            if r.status == "Compressing":
                r.status = "Cancelled"

    def _on_queue_done(self):
        self._compressing = False
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
