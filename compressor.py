import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog, messagebox
import subprocess
import threading
import os
import re
import json
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

DISCORD_PRESETS = [("8 MB", 8), ("50 MB", 50), ("100 MB", 100)]


@dataclass
class VideoInfo:
    path: str
    duration: float
    width: int
    height: int
    fps: float
    size_bytes: int
    has_audio: bool


def probe_video(path: str) -> VideoInfo:
    cmd = [
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_streams", "-show_format", path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr)
    data = json.loads(result.stdout)

    duration = float(data["format"]["duration"])
    size = int(data["format"]["size"])

    video_stream = next(s for s in data["streams"] if s["codec_type"] == "video")
    has_audio = any(s["codec_type"] == "audio" for s in data["streams"])

    fps_str = video_stream.get("r_frame_rate", "30/1")
    num, den = fps_str.split("/")
    fps = float(num) / float(den) if float(den) != 0 else 30.0

    return VideoInfo(
        path=path,
        duration=duration,
        width=int(video_stream["width"]),
        height=int(video_stream["height"]),
        fps=fps,
        size_bytes=size,
        has_audio=has_audio,
    )


def calculate_video_bitrate(target_mb: float, duration: float, audio_kbps: int, include_audio: bool) -> int:
    # 2% headroom so the output reliably stays under the limit
    target_bits = target_mb * 1024 * 1024 * 8 * 0.98
    audio_bits = (audio_kbps * 1000 * duration) if include_audio else 0
    video_kbps = max(1, int((target_bits - audio_bits) / duration / 1000))
    return video_kbps


def ffmpeg_available() -> bool:
    try:
        subprocess.run(["ffprobe", "-version"], capture_output=True, check=True)
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False


class CompressorApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Discord Video Compressor")
        self.geometry("720x680")
        self.resizable(False, False)

        self.video_info: Optional[VideoInfo] = None
        self.cancel_flag = threading.Event()
        self.process: Optional[subprocess.Popen] = None

        self._build_ui()

    # ------------------------------------------------------------------ build

    def _build_ui(self):
        main = ctk.CTkFrame(self, fg_color="transparent")
        main.pack(fill="both", expand=True, padx=24, pady=20)

        ctk.CTkLabel(main, text="Discord Video Compressor", font=("Segoe UI", 22, "bold")).pack(anchor="w", pady=(0, 16))

        if not ffmpeg_available():
            self._build_ffmpeg_warning(main)
            return

        self._build_input_section(main)
        self._build_info_section(main)
        self._build_target_section(main)
        self._build_audio_section(main)
        self._build_output_section(main)
        self._build_progress_section(main)

    def _build_ffmpeg_warning(self, parent):
        frame = ctk.CTkFrame(parent, fg_color="#3d1a1a", corner_radius=8)
        frame.pack(fill="x", pady=8)
        ctk.CTkLabel(frame, text="FFmpeg Not Found", font=("Segoe UI", 14, "bold"), text_color="#ff6b6b").pack(anchor="w", padx=16, pady=(14, 4))
        ctk.CTkLabel(frame, text="FFmpeg is required for video compression. Install it by running this in a terminal:", text_color="#cccccc").pack(anchor="w", padx=16)
        ctk.CTkLabel(frame, text="    winget install ffmpeg", font=("Courier New", 12), text_color="#7dd3fc").pack(anchor="w", padx=16, pady=(4, 4))
        ctk.CTkLabel(frame, text="Then restart this application.", text_color="#888").pack(anchor="w", padx=16, pady=(0, 14))

    def _build_input_section(self, parent):
        frame = ctk.CTkFrame(parent, corner_radius=8)
        frame.pack(fill="x", pady=(0, 10))

        header = ctk.CTkFrame(frame, fg_color="transparent")
        header.pack(fill="x", padx=14, pady=(12, 6))
        ctk.CTkLabel(header, text="Input Video", font=("Segoe UI", 13, "bold")).pack(side="left")
        ctk.CTkButton(header, text="Browse", width=90, height=30, command=self._browse_input).pack(side="right")

        self.input_label = ctk.CTkLabel(frame, text="No file selected", text_color="#888", anchor="w", wraplength=660)
        self.input_label.pack(anchor="w", padx=14, pady=(0, 12))

    def _build_info_section(self, parent):
        self.info_frame = ctk.CTkFrame(parent, corner_radius=8)
        self.info_frame.pack(fill="x", pady=(0, 10))

        ctk.CTkLabel(self.info_frame, text="Video Info", font=("Segoe UI", 13, "bold")).pack(anchor="w", padx=14, pady=(12, 6))

        grid = ctk.CTkFrame(self.info_frame, fg_color="transparent")
        grid.pack(fill="x", padx=14, pady=(0, 12))

        self.info_labels: dict[str, ctk.CTkLabel] = {}
        fields = [("Duration", "duration"), ("Resolution", "resolution"), ("Current Size", "size"), ("Frame Rate", "fps")]
        for i, (label, key) in enumerate(fields):
            col = (i % 2) * 3
            row = i // 2
            ctk.CTkLabel(grid, text=label + ":", text_color="#888", width=90, anchor="w").grid(row=row, column=col, padx=(0, 4), pady=3, sticky="w")
            lbl = ctk.CTkLabel(grid, text="—", anchor="w", width=160)
            lbl.grid(row=row, column=col + 1, padx=(0, 30), pady=3, sticky="w")
            self.info_labels[key] = lbl

    def _build_target_section(self, parent):
        frame = ctk.CTkFrame(parent, corner_radius=8)
        frame.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(frame, text="Target Size", font=("Segoe UI", 13, "bold")).pack(anchor="w", padx=14, pady=(12, 8))

        row = ctk.CTkFrame(frame, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=(0, 12))

        self.target_var = tk.StringVar(value="8")
        for label, mb in DISCORD_PRESETS:
            ctk.CTkRadioButton(row, text=label, variable=self.target_var, value=str(mb), command=self._on_target_change).pack(side="left", padx=(0, 18))

        ctk.CTkRadioButton(row, text="Custom:", variable=self.target_var, value="custom", command=self._on_target_change).pack(side="left")
        self.custom_entry = ctk.CTkEntry(row, width=72, placeholder_text="MB")
        self.custom_entry.pack(side="left", padx=(8, 0))
        self.custom_entry.configure(state="disabled")

        self.bitrate_label = ctk.CTkLabel(frame, text="", text_color="#888", font=("Segoe UI", 11))
        self.bitrate_label.pack(anchor="w", padx=14, pady=(0, 12))

    def _build_audio_section(self, parent):
        frame = ctk.CTkFrame(parent, corner_radius=8)
        frame.pack(fill="x", pady=(0, 10))

        row = ctk.CTkFrame(frame, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=12)

        self.audio_var = tk.BooleanVar(value=True)
        ctk.CTkCheckBox(row, text="Include Audio", variable=self.audio_var, command=self._update_bitrate_label).pack(side="left")

        ctk.CTkLabel(row, text="Audio Bitrate:", text_color="#888").pack(side="left", padx=(28, 8))
        self.audio_bitrate_var = tk.StringVar(value="128")
        ctk.CTkOptionMenu(row, variable=self.audio_bitrate_var, values=["64", "96", "128", "192"], width=90,
                          command=lambda _: self._update_bitrate_label()).pack(side="left")
        ctk.CTkLabel(row, text="kbps", text_color="#888").pack(side="left", padx=(6, 0))

    def _build_output_section(self, parent):
        frame = ctk.CTkFrame(parent, corner_radius=8)
        frame.pack(fill="x", pady=(0, 10))

        ctk.CTkLabel(frame, text="Output", font=("Segoe UI", 13, "bold")).pack(anchor="w", padx=14, pady=(12, 6))

        row = ctk.CTkFrame(frame, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=(0, 12))

        self.output_path = tk.StringVar()
        ctk.CTkEntry(row, textvariable=self.output_path, placeholder_text="Output file (auto-generated)").pack(side="left", fill="x", expand=True, padx=(0, 10))
        ctk.CTkButton(row, text="Browse", width=90, height=32, command=self._browse_output).pack(side="right")

    def _build_progress_section(self, parent):
        self.status_label = ctk.CTkLabel(parent, text="Ready", text_color="#888", anchor="w")
        self.status_label.pack(fill="x", pady=(4, 4))

        self.progress_bar = ctk.CTkProgressBar(parent)
        self.progress_bar.pack(fill="x", pady=(0, 14))
        self.progress_bar.set(0)

        btn_row = ctk.CTkFrame(parent, fg_color="transparent")
        btn_row.pack(fill="x")

        self.compress_btn = ctk.CTkButton(
            btn_row, text="Compress Video", width=180, height=42,
            font=("Segoe UI", 14, "bold"), command=self._start_compression,
        )
        self.compress_btn.pack(side="left")

        self.cancel_btn = ctk.CTkButton(
            btn_row, text="Cancel", width=100, height=42,
            fg_color="#555", hover_color="#444", command=self._cancel, state="disabled",
        )
        self.cancel_btn.pack(side="left", padx=(12, 0))

    # ------------------------------------------------------------------ logic

    def _browse_input(self):
        path = filedialog.askopenfilename(
            title="Select Video",
            filetypes=[("Video files", "*.mp4 *.mov *.avi *.mkv *.webm *.flv *.wmv *.m4v *.ts"), ("All files", "*.*")],
        )
        if path:
            self._load_video(path)

    def _load_video(self, path: str):
        self.status_label.configure(text="Reading video info…")
        self.update()
        try:
            info = probe_video(path)
        except Exception as e:
            messagebox.showerror("Error", f"Could not read video:\n{e}")
            self.status_label.configure(text="Ready")
            return

        self.video_info = info
        self.input_label.configure(text=path, text_color="white")

        mins = int(info.duration // 60)
        secs = int(info.duration % 60)
        self.info_labels["duration"].configure(text=f"{mins}:{secs:02d}")
        self.info_labels["resolution"].configure(text=f"{info.width} × {info.height}")
        self.info_labels["size"].configure(text=f"{info.size_bytes / 1024 / 1024:.1f} MB")
        self.info_labels["fps"].configure(text=f"{info.fps:.2f} fps")

        self._auto_output_path()
        self._update_bitrate_label()
        self.status_label.configure(text="Ready")

    def _auto_output_path(self):
        if not self.video_info:
            return
        stem = Path(self.video_info.path).stem
        folder = Path(self.video_info.path).parent
        target = self.target_var.get()
        suffix = f"_{target}mb" if target != "custom" else "_compressed"
        self.output_path.set(str(folder / f"{stem}{suffix}.mp4"))

    def _browse_output(self):
        path = filedialog.asksaveasfilename(
            title="Save As",
            defaultextension=".mp4",
            filetypes=[("MP4 files", "*.mp4"), ("All files", "*.*")],
        )
        if path:
            self.output_path.set(path)

    def _on_target_change(self):
        is_custom = self.target_var.get() == "custom"
        self.custom_entry.configure(state="normal" if is_custom else "disabled")
        self._auto_output_path()
        self._update_bitrate_label()

    def _update_bitrate_label(self):
        if not self.video_info:
            return
        target_mb = self._get_target_mb()
        if target_mb is None:
            return
        include_audio = self.audio_var.get()
        audio_kbps = int(self.audio_bitrate_var.get())
        vbr = calculate_video_bitrate(target_mb, self.video_info.duration, audio_kbps, include_audio)
        self.bitrate_label.configure(text=f"Estimated video bitrate: {vbr} kbps")

    def _get_target_mb(self) -> Optional[float]:
        val = self.target_var.get()
        if val == "custom":
            try:
                return float(self.custom_entry.get())
            except ValueError:
                return None
        return float(val)

    def _start_compression(self):
        if not self.video_info:
            messagebox.showwarning("No Input", "Please select a video file first.")
            return

        target_mb = self._get_target_mb()
        if target_mb is None:
            messagebox.showerror("Error", "Enter a valid custom size in MB.")
            return

        output = self.output_path.get().strip()
        if not output:
            messagebox.showwarning("No Output", "Please specify an output file path.")
            return

        include_audio = self.audio_var.get()
        audio_kbps = int(self.audio_bitrate_var.get())
        vbr = calculate_video_bitrate(target_mb, self.video_info.duration, audio_kbps, include_audio)

        if vbr < 10:
            messagebox.showerror(
                "Error",
                f"The target size is too small for this video duration.\n"
                f"The video bitrate would only be {vbr} kbps, which won't produce usable output.\n\n"
                f"Try a larger target size or a shorter clip.",
            )
            return

        self.cancel_flag.clear()
        self.compress_btn.configure(state="disabled")
        self.cancel_btn.configure(state="normal")
        self.progress_bar.set(0)

        t = threading.Thread(
            target=self._compress,
            args=(self.video_info.path, output, vbr, audio_kbps if include_audio else 0, self.video_info.duration),
            daemon=True,
        )
        t.start()

    def _compress(self, src: str, dst: str, vbr: int, abr: int, duration: float):
        passlog = str(Path(dst).parent / "ffmpeg2pass")
        try:
            self._set_status("Pass 1 / 2  —  Analyzing…")

            pass1 = [
                "ffmpeg", "-y", "-i", src,
                "-c:v", "libx264", "-b:v", f"{vbr}k",
                "-pass", "1", "-passlogfile", passlog,
                "-an", "-f", "null", "NUL",
            ]
            if not self._run_ffmpeg(pass1, duration, 0.0, 0.5):
                return

            self._set_status("Pass 2 / 2  —  Encoding…")

            pass2 = [
                "ffmpeg", "-y", "-i", src,
                "-c:v", "libx264", "-b:v", f"{vbr}k",
                "-pass", "2", "-passlogfile", passlog,
            ]
            pass2 += ["-c:a", "aac", "-b:a", f"{abr}k"] if abr > 0 else ["-an"]
            pass2.append(dst)

            if not self._run_ffmpeg(pass2, duration, 0.5, 1.0):
                return

            final_mb = os.path.getsize(dst) / 1024 / 1024
            self._set_status(f"Done  —  {final_mb:.2f} MB saved to {Path(dst).name}")
            self.after(0, lambda: self.progress_bar.set(1.0))
            self.after(0, lambda: messagebox.showinfo("Done", f"Output: {final_mb:.2f} MB\n\n{dst}"))

        except Exception as e:
            self._set_status(f"Error: {e}")
        finally:
            for f in Path(dst).parent.glob("ffmpeg2pass*"):
                try:
                    f.unlink()
                except OSError:
                    pass
            self.after(0, lambda: self.compress_btn.configure(state="normal"))
            self.after(0, lambda: self.cancel_btn.configure(state="disabled"))

    def _run_ffmpeg(self, cmd: list, duration: float, p_start: float, p_end: float) -> bool:
        self.process = subprocess.Popen(cmd, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
        time_re = re.compile(r"time=(\d+):(\d+):(\d+\.\d+)")

        for line in self.process.stderr:
            if self.cancel_flag.is_set():
                self.process.terminate()
                self._set_status("Cancelled.")
                return False
            m = time_re.search(line)
            if m:
                elapsed = float(m.group(1)) * 3600 + float(m.group(2)) * 60 + float(m.group(3))
                frac = min(1.0, elapsed / duration)
                p = p_start + frac * (p_end - p_start)
                self.after(0, lambda v=p: self.progress_bar.set(v))

        self.process.wait()
        return self.process.returncode == 0

    def _cancel(self):
        self.cancel_flag.set()
        if self.process:
            try:
                self.process.terminate()
            except OSError:
                pass

    def _set_status(self, text: str):
        self.after(0, lambda: self.status_label.configure(text=text))


if __name__ == "__main__":
    app = CompressorApp()
    app.mainloop()
