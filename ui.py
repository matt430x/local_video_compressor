import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog, messagebox
import threading
from pathlib import Path
from typing import Optional

from tkinterdnd2 import TkinterDnD, DND_FILES
from video import VideoInfo, probe_video
from encoder import Encoder, ffmpeg_available, calculate_video_bitrate

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

DISCORD_PRESETS = [("8 MB", 8), ("50 MB", 50), ("100 MB", 100)]
VERSION = "v2.0"

STATUS_COLORS = {
    "Reading":     "#f59e0b",
    "Ready":       "#4ade80",
    "Compressing": "#3b82f6",
    "Done":        "#22c55e",
    "Error":       "#ef4444",
    "Cancelled":   "#f97316",
}


class QueueRow(ctk.CTkFrame):
    NORMAL_COLOR  = "#2a2a2a"
    SELECTED_COLOR = "#1e3a5f"

    def __init__(self, parent, path: str, on_remove, on_select):
        super().__init__(parent, corner_radius=6, fg_color=self.NORMAL_COLOR)
        self.path = path
        self.info: Optional[VideoInfo] = None
        self._status = "Reading"

        self.columnconfigure(0, weight=1)

        name = Path(path).name
        display_name = name if len(name) <= 36 else name[:35] + "…"
        name_lbl = ctk.CTkLabel(self, text=display_name, anchor="w",
                                  font=("Segoe UI", 11))
        name_lbl.grid(row=0, column=0, padx=(10, 4), pady=(8, 2), sticky="w")

        self.meta_lbl = ctk.CTkLabel(self, text="Reading…", text_color="#666",
                                      font=("Segoe UI", 10), anchor="w")
        self.meta_lbl.grid(row=1, column=0, padx=(10, 4), pady=(0, 8), sticky="w")

        right = ctk.CTkFrame(self, fg_color="transparent")
        right.grid(row=0, column=1, rowspan=2, padx=(0, 8), pady=4, sticky="e")

        self.status_lbl = ctk.CTkLabel(right, text="Reading",
                                        font=("Segoe UI", 10, "bold"),
                                        text_color=STATUS_COLORS["Reading"], width=80)
        self.status_lbl.pack(anchor="e")

        self.remove_btn = ctk.CTkButton(right, text="✕", width=24, height=24,
                                         fg_color="transparent", hover_color="#555",
                                         font=("Segoe UI", 11), command=on_remove)
        self.remove_btn.pack(anchor="e", pady=(4, 0))

        # Make the whole row clickable
        for widget in (self, name_lbl, self.meta_lbl, right, self.status_lbl):
            widget.bind("<Button-1>", lambda e, r=self: on_select(r))

    @property
    def status(self):
        return self._status

    @status.setter
    def status(self, value: str):
        self._status = value
        self.status_lbl.configure(text=value, text_color=STATUS_COLORS.get(value, "#888"))
        self.remove_btn.configure(state="disabled" if value == "Compressing" else "normal")

    def set_selected(self, selected: bool):
        self.configure(fg_color=self.SELECTED_COLOR if selected else self.NORMAL_COLOR)

    def set_info(self, info: VideoInfo):
        self.info = info
        mb = info.size_bytes / 1024 / 1024
        mins = int(info.duration // 60)
        secs = int(info.duration % 60)
        self.meta_lbl.configure(text=f"{mb:.1f} MB  ·  {mins}:{secs:02d}")


class CompressorApp(ctk.CTk, TkinterDnD.DnDWrapper):
    def __init__(self):
        super().__init__()
        self.TkdndVersion = TkinterDnD._require(self)
        self.title("Discord Video Compressor")
        self.geometry("960x700")
        self.resizable(True, True)
        self.minsize(960, 700)

        self.encoder = Encoder()
        self._output_folder: Optional[str] = None
        self._queue_rows: list[QueueRow] = []
        self._selected_row: Optional[QueueRow] = None
        self._compressing = False

        self._build_ui()

    # ------------------------------------------------------------------ build

    def _build_ui(self):
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=24, pady=(20, 12))

        title_row = ctk.CTkFrame(header, fg_color="transparent")
        title_row.pack(fill="x")
        ctk.CTkLabel(title_row, text="Discord Video Compressor",
                      font=("Segoe UI", 22, "bold")).pack(side="left")
        ctk.CTkLabel(title_row, text=VERSION, font=("Segoe UI", 12),
                      text_color="#666").pack(side="right", anchor="s", pady=(0, 4))
        ctk.CTkLabel(header, text="by matt430", font=("Segoe UI", 11),
                      text_color="#666").pack(anchor="w", pady=(2, 0))

        if not ffmpeg_available():
            self._build_ffmpeg_warning()
            return

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=24, pady=(0, 20))
        body.columnconfigure(0, weight=2, minsize=320)
        body.columnconfigure(1, weight=3)
        body.rowconfigure(0, weight=1)

        self._build_left_column(body)
        self._build_right_column(body)

        self.drop_target_register(DND_FILES)
        self.dnd_bind("<<Drop>>", self._on_drop)

    def _on_drop(self, event):
        VIDEO_EXT = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".flv", ".wmv", ".m4v", ".ts"}
        for path in self.tk.splitlist(event.data):
            if Path(path).suffix.lower() in VIDEO_EXT:
                if not any(r.path == path for r in self._queue_rows):
                    self._add_to_queue(path)

    def _build_ffmpeg_warning(self):
        frame = ctk.CTkFrame(self, fg_color="#3d1a1a", corner_radius=8)
        frame.pack(fill="x", padx=24, pady=8)
        ctk.CTkLabel(frame, text="FFmpeg Not Found", font=("Segoe UI", 14, "bold"),
                      text_color="#ff6b6b").pack(anchor="w", padx=16, pady=(14, 4))
        ctk.CTkLabel(frame, text="FFmpeg is required. Install it by running:",
                      text_color="#cccccc").pack(anchor="w", padx=16)
        ctk.CTkLabel(frame, text="    winget install ffmpeg", font=("Courier New", 12),
                      text_color="#7dd3fc").pack(anchor="w", padx=16, pady=(4, 4))
        ctk.CTkLabel(frame, text="Then restart this application.",
                      text_color="#888").pack(anchor="w", padx=16, pady=(0, 14))

    def _build_left_column(self, parent):
        left = ctk.CTkFrame(parent, fg_color="transparent")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        left.rowconfigure(0, weight=1)
        left.columnconfigure(0, weight=1)

        # Input Videos card
        queue_card = ctk.CTkFrame(left, corner_radius=8)
        queue_card.grid(row=0, column=0, sticky="nsew", pady=(0, 8))
        queue_card.rowconfigure(1, weight=1)
        queue_card.columnconfigure(0, weight=1)

        hdr = ctk.CTkFrame(queue_card, fg_color="transparent")
        hdr.grid(row=0, column=0, sticky="ew", padx=14, pady=(12, 6))
        ctk.CTkLabel(hdr, text="Input Videos", font=("Segoe UI", 13, "bold")).pack(side="left")
        ctk.CTkButton(hdr, text="Clear", width=70, height=28,
                       fg_color="#555", hover_color="#444",
                       command=self._clear_queue).pack(side="right", padx=(6, 0))
        ctk.CTkButton(hdr, text="Add", width=70, height=28,
                       command=self._browse_add).pack(side="right")

        self.queue_list = ctk.CTkScrollableFrame(queue_card, fg_color="transparent")
        self.queue_list.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))
        self.queue_list.columnconfigure(0, weight=1)

        self.empty_label = ctk.CTkLabel(self.queue_list,
                                         text="Drop videos here or click Add",
                                         text_color="#555", font=("Segoe UI", 11))
        self.empty_label.grid(row=0, column=0, pady=20)

        # Video Info card
        info_card = ctk.CTkFrame(left, corner_radius=8)
        info_card.grid(row=1, column=0, sticky="ew")

        ctk.CTkLabel(info_card, text="Video Info", font=("Segoe UI", 13, "bold")).pack(
            anchor="w", padx=14, pady=(12, 6))

        grid = ctk.CTkFrame(info_card, fg_color="transparent")
        grid.pack(fill="x", padx=14, pady=(0, 12))

        self.info_labels: dict[str, ctk.CTkLabel] = {}
        fields = [("Duration", "duration"), ("Resolution", "resolution"),
                  ("File Size", "size"), ("Frame Rate", "fps")]
        for i, (label, key) in enumerate(fields):
            c = (i % 2) * 3
            r = i // 2
            ctk.CTkLabel(grid, text=label + ":", text_color="#888", width=80,
                          anchor="w").grid(row=r, column=c, padx=(0, 4), pady=3, sticky="w")
            lbl = ctk.CTkLabel(grid, text="—", anchor="w", width=120)
            lbl.grid(row=r, column=c + 1, padx=(0, 20), pady=3, sticky="w")
            self.info_labels[key] = lbl

    def _build_right_column(self, parent):
        right = ctk.CTkFrame(parent, fg_color="transparent")
        right.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        right.columnconfigure(0, weight=1)
        right.rowconfigure(3, weight=1)  # spacer — absorbs extra vertical space

        self._build_target_section(right)
        self._build_audio_section(right)
        self._build_output_section(right)
        self._build_progress_section(right)

    def _build_target_section(self, parent):
        frame = ctk.CTkFrame(parent, corner_radius=8)
        frame.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        ctk.CTkLabel(frame, text="Target Size", font=("Segoe UI", 13, "bold")).pack(
            anchor="w", padx=14, pady=(12, 8))

        row = ctk.CTkFrame(frame, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=(0, 12))

        self.target_var = tk.StringVar(value="8")
        for label, mb in DISCORD_PRESETS:
            ctk.CTkRadioButton(row, text=label, variable=self.target_var,
                                value=str(mb)).pack(side="left", padx=(0, 14))
        ctk.CTkRadioButton(row, text="Custom:", variable=self.target_var,
                            value="custom", command=self._on_target_change).pack(side="left")
        self.custom_entry = ctk.CTkEntry(row, width=72, placeholder_text="MB")
        self.custom_entry.pack(side="left", padx=(8, 0))
        self.custom_entry.configure(state="disabled")

    def _build_audio_section(self, parent):
        frame = ctk.CTkFrame(parent, corner_radius=8)
        frame.grid(row=1, column=0, sticky="ew", pady=(0, 10))

        row = ctk.CTkFrame(frame, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=12)

        self.audio_var = tk.BooleanVar(value=True)
        ctk.CTkCheckBox(row, text="Include Audio", variable=self.audio_var).pack(side="left")
        ctk.CTkLabel(row, text="Audio Bitrate:", text_color="#888").pack(side="left", padx=(24, 8))
        self.audio_bitrate_var = tk.StringVar(value="128")
        ctk.CTkOptionMenu(row, variable=self.audio_bitrate_var,
                           values=["64", "96", "128", "192"], width=90).pack(side="left")
        ctk.CTkLabel(row, text="kbps", text_color="#888").pack(side="left", padx=(6, 0))

    def _build_output_section(self, parent):
        frame = ctk.CTkFrame(parent, corner_radius=8)
        frame.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        ctk.CTkLabel(frame, text="Output Folder", font=("Segoe UI", 13, "bold")).pack(
            anchor="w", padx=14, pady=(12, 6))

        row = ctk.CTkFrame(frame, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=(0, 12))

        self.output_path = tk.StringVar()
        ctk.CTkEntry(row, textvariable=self.output_path,
                      placeholder_text="Select output folder…").pack(
            side="left", fill="x", expand=True, padx=(0, 10))
        ctk.CTkButton(row, text="Browse", width=90, height=32,
                       command=self._browse_output).pack(side="right")

    def _build_progress_section(self, parent):
        progress_frame = ctk.CTkFrame(parent, fg_color="transparent")
        progress_frame.grid(row=4, column=0, sticky="ew")
        progress_frame.columnconfigure(0, weight=1)

        self.status_label = ctk.CTkLabel(progress_frame, text="Ready", text_color="#888", anchor="w")
        self.status_label.grid(row=0, column=0, sticky="ew", pady=(4, 4))

        self.progress_bar = ctk.CTkProgressBar(progress_frame)
        self.progress_bar.grid(row=1, column=0, sticky="ew", pady=(0, 14))
        self.progress_bar.set(0)

        btn_row = ctk.CTkFrame(progress_frame, fg_color="transparent")
        btn_row.grid(row=2, column=0, sticky="w")

        self.compress_btn = ctk.CTkButton(
            btn_row, text="Compress Videos", width=180, height=42,
            font=("Segoe UI", 14, "bold"), command=self._start_queue,
        )
        self.compress_btn.pack(side="left")

        self.cancel_btn = ctk.CTkButton(
            btn_row, text="Cancel", width=100, height=42,
            fg_color="#555", hover_color="#444", command=self._cancel, state="disabled",
        )
        self.cancel_btn.pack(side="left", padx=(12, 0))

    # ------------------------------------------------------------------ queue

    def _browse_add(self):
        paths = filedialog.askopenfilenames(
            title="Select Videos",
            filetypes=[("Video files", "*.mp4 *.mov *.avi *.mkv *.webm *.flv *.wmv *.m4v *.ts"),
                       ("All files", "*.*")],
        )
        for path in paths:
            if not any(r.path == path for r in self._queue_rows):
                self._add_to_queue(path)

    def _add_to_queue(self, path: str):
        self.empty_label.grid_remove()

        row = QueueRow(
            self.queue_list, path,
            on_remove=lambda p=path: self._remove_from_queue(p),
            on_select=self._select_row,
        )
        row.grid(row=len(self._queue_rows), column=0, sticky="ew", pady=(0, 6))
        self._queue_rows.append(row)

        def _probe():
            try:
                info = probe_video(path)
                def update():
                    row.set_info(info)
                    row.status = "Ready"
                    if self._selected_row is row:
                        self._populate_stats(info)
                self.after(0, update)
            except Exception:
                def err():
                    row.status = "Error"
                    row.meta_lbl.configure(text="Could not read file")
                self.after(0, err)
        threading.Thread(target=_probe, daemon=True).start()

    def _remove_from_queue(self, path: str):
        row = next((r for r in self._queue_rows if r.path == path), None)
        if not row or row.status == "Compressing":
            return
        if self._selected_row is row:
            self._selected_row = None
            self._clear_stats()
        row.destroy()
        self._queue_rows.remove(row)
        for i, r in enumerate(self._queue_rows):
            r.grid(row=i, column=0, sticky="ew", pady=(0, 6))
        if not self._queue_rows:
            self.empty_label.grid(row=0, column=0, pady=20)

    def _clear_queue(self):
        for row in list(self._queue_rows):
            if row.status != "Compressing":
                row.destroy()
                self._queue_rows.remove(row)
        self._selected_row = None
        self._clear_stats()
        if not self._queue_rows:
            self.empty_label.grid(row=0, column=0, pady=20)

    def _select_row(self, row: QueueRow):
        if self._selected_row:
            self._selected_row.set_selected(False)
        self._selected_row = row
        row.set_selected(True)
        if row.info:
            self._populate_stats(row.info)
        else:
            self._clear_stats()

    def _populate_stats(self, info: VideoInfo):
        mins = int(info.duration // 60)
        secs = int(info.duration % 60)
        self.info_labels["duration"].configure(text=f"{mins}:{secs:02d}")
        self.info_labels["resolution"].configure(text=f"{info.width} × {info.height}")
        self.info_labels["size"].configure(text=f"{info.size_bytes / 1024 / 1024:.1f} MB")
        self.info_labels["fps"].configure(text=f"{info.fps:.2f} fps")

    def _clear_stats(self):
        for lbl in self.info_labels.values():
            lbl.configure(text="—")

    # ------------------------------------------------------------------ compression

    def _browse_output(self):
        folder = filedialog.askdirectory(title="Select Output Folder")
        if folder:
            self._output_folder = folder
            self.output_path.set(folder)

    def _on_target_change(self):
        is_custom = self.target_var.get() == "custom"
        self.custom_entry.configure(state="normal" if is_custom else "disabled")

    def _get_target_mb(self) -> Optional[float]:
        val = self.target_var.get()
        if val == "custom":
            try:
                return float(self.custom_entry.get())
            except ValueError:
                return None
        return float(val)

    def _start_queue(self):
        pending = [r for r in self._queue_rows if r.status == "Ready"]
        if not pending:
            messagebox.showwarning("No Videos", "Add at least one video to compress.")
            return
        if self._get_target_mb() is None:
            messagebox.showerror("Error", "Enter a valid custom size in MB.")
            return
        if not self._output_folder:
            messagebox.showwarning("No Output Folder", "Please select an output folder.")
            return

        self._compressing = True
        self.compress_btn.configure(state="disabled")
        self.cancel_btn.configure(state="normal")
        self.progress_bar.set(0)
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
        self.progress_bar.set(0)

        if row.info is None:
            def _probe_then():
                try:
                    info = probe_video(row.path)
                    def go():
                        row.set_info(info)
                        if self._selected_row is row:
                            self._populate_stats(info)
                        self._run_compression(row)
                    self.after(0, go)
                except Exception:
                    def err():
                        row.status = "Error"
                        self._compress_next()
                    self.after(0, err)
            threading.Thread(target=_probe_then, daemon=True).start()
        else:
            self._run_compression(row)

    def _run_compression(self, row: QueueRow):
        target_mb = self._get_target_mb()
        include_audio = self.audio_var.get()
        audio_kbps = int(self.audio_bitrate_var.get())
        vbr = calculate_video_bitrate(target_mb, row.info.duration, audio_kbps, include_audio)

        stem = Path(row.path).stem
        target = self.target_var.get()
        suffix = f"_{target}mb" if target != "custom" else "_compressed"
        dst = str(Path(self._output_folder) / f"{stem}{suffix}.mp4")

        if vbr < 10:
            row.status = "Error"
            self.status_label.configure(
                text=f"Skipped {Path(row.path).name} — target too small for duration")
            self._compress_next()
            return

        def on_done(path, kb, _row=row):
            def update():
                _row.status = "Done"
                self.progress_bar.set(1.0)
            self.after(0, update)

        self.encoder.start(
            src=row.path,
            dst=dst,
            vbr=vbr,
            abr=audio_kbps if include_audio else 0,
            duration=row.info.duration,
            on_progress=lambda p: self.after(0, lambda: self.progress_bar.set(p)),
            on_status=lambda s: self.after(0, lambda: self.status_label.configure(text=s)),
            on_done=on_done,
            on_finished=lambda: self.after(0, self._compress_next),
        )

    def _cancel(self):
        self._compressing = False
        self.encoder.cancel()
        for r in self._queue_rows:
            if r.status == "Compressing":
                r.status = "Cancelled"

    def _on_queue_done(self):
        self._compressing = False
        self.compress_btn.configure(state="normal")
        self.cancel_btn.configure(state="disabled")
        done = sum(1 for r in self._queue_rows if r.status == "Done")
        total = len(self._queue_rows)
        self.status_label.configure(text=f"Done  —  {done} of {total} videos compressed")
