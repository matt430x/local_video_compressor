import os
import sys

def _ff(name: str) -> str:
    """Return the path to an ffmpeg binary.

    When running as a PyInstaller bundle the binaries live in _MEIPASS.
    In dev they are expected in ffmpeg_bin/ next to this file.
    Falls back to bare name (PATH lookup) if neither location has the file.
    """
    if getattr(sys, 'frozen', False):
        return os.path.join(sys._MEIPASS, name)
    local = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ffmpeg_bin', name)
    if os.path.exists(local):
        return local
    return name

FFMPEG  = _ff('ffmpeg.exe')
FFPROBE = _ff('ffprobe.exe')