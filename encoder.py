import subprocess
import threading
import re
import os
from pathlib import Path
from typing import Callable, Optional
from ff_paths import FFMPEG, FFPROBE


def ffmpeg_available() -> bool:
    try:
        subprocess.run([FFPROBE, "-version"], capture_output=True, check=True,
                       creationflags=subprocess.CREATE_NO_WINDOW)
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False


def calculate_video_bitrate(target_mb: float, duration: float, audio_kbps: int,
                             include_audio: bool) -> int:
    # 10% headroom — two-pass CBR routinely overshoots by 5-15%
    target_bits = target_mb * 1024 * 1024 * 8 * 0.90
    audio_bits = (audio_kbps * 1000 * duration) if include_audio else 0
    return max(1, int((target_bits - audio_bits) / duration / 1000))


class Encoder:
    def __init__(self):
        self._cancel_flag = threading.Event()
        self._process: Optional[subprocess.Popen] = None

    def start(
        self,
        src: str,
        dst: str,
        vbr: int,
        abr: int,
        duration: float,
        on_progress: Callable[[float], None],
        on_status: Callable[[str], None],
        on_done: Callable[[str, float], None],
        on_finished: Callable[[], None],
        start_time: float = 0.0,
        end_time: Optional[float] = None,
        volume_db: float = 0.0,
        normalize: bool = False,
    ):
        self._cancel_flag.clear()
        threading.Thread(
            target=self._compress,
            args=(src, dst, vbr, abr, duration, on_progress, on_status, on_done,
                  on_finished, start_time, end_time, volume_db, normalize),
            daemon=True,
        ).start()

    def cancel(self):
        self._cancel_flag.set()
        if self._process:
            try:
                self._process.terminate()
            except OSError:
                pass

    def _compress(self, src, dst, vbr, abr, duration, on_progress, on_status,
                  on_done, on_finished, start_time, end_time, volume_db, normalize):
        passlog = str(Path(dst).parent / "ffmpeg2pass")
        try:
            seek = ["-ss", str(start_time)] if start_time > 0 else []
            trim = ["-t", str(end_time - start_time)] if end_time is not None else []

            on_status("Pass 1 / 2  —  Analyzing…")
            pass1 = (
                [FFMPEG, "-y"]
                + seek
                + ["-i", src,
                   "-c:v", "libx264", "-b:v", f"{vbr}k",
                   "-maxrate", f"{vbr}k", "-bufsize", f"{vbr * 2}k",
                   "-pass", "1", "-passlogfile", passlog,
                   "-an"]
                + trim
                + ["-f", "null", "NUL"]
            )
            if not self._run_ffmpeg(pass1, duration, 0.0, 0.5, on_progress, on_status):
                return

            on_status("Pass 2 / 2  —  Encoding…")
            pass2 = (
                [FFMPEG, "-y"]
                + seek
                + ["-i", src,
                   "-c:v", "libx264", "-b:v", f"{vbr}k",
                   "-maxrate", f"{vbr}k", "-bufsize", f"{vbr * 2}k",
                   "-pass", "2", "-passlogfile", passlog]
            )
            if abr > 0:
                pass2 += ["-c:a", "aac", "-b:a", f"{abr}k"]
                filters = []
                if normalize:
                    filters.append("loudnorm")
                if volume_db != 0.0:
                    filters.append(f"volume={volume_db:.1f}dB")
                if filters:
                    pass2 += ["-af", ",".join(filters)]
            else:
                pass2 += ["-an"]
            pass2 += trim + [dst]
            print(f"[encoder] pass2: {' '.join(pass2)}", flush=True)

            if not self._run_ffmpeg(pass2, duration, 0.5, 1.0, on_progress, on_status):
                return

            size_bytes = os.path.getsize(dst)
            size_kb = round(size_bytes / 1024)
            on_status(f"Done  —  {size_kb:,} KB saved to {dst}")
            on_done(dst, size_kb)

        except Exception as e:
            on_status(f"Error: {e}")
        finally:
            for f in Path(dst).parent.glob("ffmpeg2pass*"):
                try:
                    f.unlink()
                except OSError:
                    pass
            on_finished()

    def _run_ffmpeg(self, cmd, duration, p_start, p_end, on_progress, on_status) -> bool:
        self._process = subprocess.Popen(
            cmd, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        time_re = re.compile(r"time=(\d+):(\d+):(\d+\.\d+)")
        for line in self._process.stderr:
            if self._cancel_flag.is_set():
                self._process.terminate()
                on_status("Cancelled.")
                return False
            m = time_re.search(line)
            if m:
                elapsed = (float(m.group(1)) * 3600 + float(m.group(2)) * 60
                           + float(m.group(3)))
                frac = min(1.0, elapsed / duration)
                on_progress(p_start + frac * (p_end - p_start))
        self._process.wait()
        return self._process.returncode == 0
