#!/usr/bin/env python3
import os
import subprocess
import sys
import threading
import math
import shutil
from dataclasses import dataclass
from typing import List, Optional, Dict
from tkinter import Tk, Button, Label, Entry, StringVar, BooleanVar, Checkbutton, filedialog, messagebox, ttk
import json


@dataclass
class SliceConfig:
    segment_seconds: int = 15
    fast_copy: bool = False
    audio_stream_index: Optional[int] = None  # ffprobe stream index within audio streams (0-based)


def resolve_tool_path(tool_name: str) -> str:
    """
    Resolve ffmpeg/ffprobe path with support for PyInstaller bundles on Windows.
    Search order:
    - Inside PyInstaller temp dir (sys._MEIPASS) if present
    - Next to executable on Windows
    - PATH via shutil.which
    - Fallback to tool name
    """
    # 1) PyInstaller onefile extraction dir
    base_dir = getattr(sys, "_MEIPASS", None)
    if base_dir:
        candidate = os.path.join(base_dir, tool_name)
        if os.path.isfile(candidate):
            return candidate
        # Windows .exe
        candidate_exe = os.path.join(base_dir, f"{tool_name}.exe")
        if os.path.isfile(candidate_exe):
            return candidate_exe

    # 2) Next to current executable/script
    exe_dir = os.path.dirname(sys.executable if getattr(sys, "frozen", False) else os.path.abspath(__file__))
    candidate2 = os.path.join(exe_dir, tool_name)
    if os.path.isfile(candidate2):
        return candidate2
    candidate2_exe = os.path.join(exe_dir, f"{tool_name}.exe")
    if os.path.isfile(candidate2_exe):
        return candidate2_exe

    # 3) PATH
    found = shutil.which(tool_name)
    if found:
        return found

    # 4) Fallback
    return tool_name


def is_ffmpeg_available() -> bool:
    try:
        ffmpeg_path = resolve_tool_path("ffmpeg")
        result = subprocess.run([ffmpeg_path, "-version"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        return result.returncode == 0
    except Exception:
        return False


def get_video_duration_seconds(input_path: str) -> float:
    """Return duration in seconds using ffprobe."""
    ffprobe_path = resolve_tool_path("ffprobe")
    try:
        result = subprocess.run(
            [
                ffprobe_path,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                input_path,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=True,
        )
        dur = float(result.stdout.strip())
        return dur
    except Exception as exc:
        raise RuntimeError(f"Не удалось определить длительность видео: {exc}") from exc


def list_audio_tracks(input_path: str) -> List[Dict[str, str]]:
    """Return a list of audio tracks with metadata using ffprobe (JSON output).
    Each item has keys: idx (stream index in file), codec, lang, title, channels, label.
    The order of returned items corresponds to 0:a:<position> mapping.
    """
    ffprobe_path = resolve_tool_path("ffprobe")
    try:
        result = subprocess.run(
            [
                ffprobe_path,
                "-v",
                "error",
                "-select_streams",
                "a",
                "-show_entries",
                "stream=index,codec_name,channels,tags",
                "-of",
                "json",
                input_path,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=True,
        )
        data = json.loads(result.stdout or "{}")
        streams = data.get("streams", []) or []
        tracks: List[Dict[str, str]] = []
        for s in streams:
            idx = str(s.get("index", ""))
            codec = str(s.get("codec_name", ""))
            channels = str(s.get("channels", ""))
            tags = s.get("tags", {}) or {}
            lang = str(tags.get("language", ""))
            title = str(tags.get("title", ""))
            # Prefer human-readable name: title > language > #index
            main = title.strip() or lang.strip() or f"Stream #{idx}"
            # Provide compact technical suffix
            tech_parts = []
            if codec:
                tech_parts.append(codec)
            if channels:
                tech_parts.append(f"{channels}ch")
            suffix = f" ({' '.join(tech_parts)})" if tech_parts else ""
            label = f"{main}{suffix}"
            tracks.append({
                "idx": idx,
                "codec": codec,
                "lang": lang,
                "title": title,
                "channels": channels,
                "label": label,
            })
        return tracks
    except Exception:
        return []


def build_output_pattern(output_dir: str, base_name: str) -> str:
    name, _ = os.path.splitext(base_name)
    return os.path.join(output_dir, f"{name}_%03d.mp4")


def slice_video_ffmpeg(input_path: str, output_dir: str, config: SliceConfig, progress_callback=None) -> None:
    """
    Slice video into segments using ffmpeg segment muxer.
    If fast_copy is True, streams are copied (-c copy), which is much faster but
    cuts can align to keyframes. Otherwise, re-encode to H.264/AAC for compatibility
    and enforce keyframes at boundaries for more stable segment lengths.
    """
    if not os.path.exists(output_dir):
        os.makedirs(output_dir, exist_ok=True)

    output_pattern = build_output_pattern(output_dir, os.path.basename(input_path))

    # Determine duration to approximate progress
    try:
        duration_seconds = get_video_duration_seconds(input_path)
    except Exception:
        duration_seconds = 0.0

    ffmpeg_path = resolve_tool_path("ffmpeg")

    cmd = [
        ffmpeg_path,
        "-hide_banner",
        "-y",
        "-i",
        input_path,
    ]

    # Stream mapping: always one video stream (0:v:0)
    cmd += ["-map", "0:v:0"]
    # Audio: map selected index if provided, else pick first if present
    if config.audio_stream_index is not None:
        cmd += ["-map", f"0:a:{config.audio_stream_index}"]
    else:
        cmd += ["-map", "0:a:0?"]

    if config.fast_copy:
        cmd += [
            "-c",
            "copy",
        ]
    else:
        # Re-encode video and enforce keyframes at segment boundaries
        force_expr = f"expr:gte(t,n_forced*{config.segment_seconds})"
        cmd += [
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "23",
            "-sc_threshold",
            "0",
            "-force_key_frames",
            force_expr,
            "-c:a",
            "aac",
            "-b:a",
            "128k",
        ]

    # Segmenter settings
    cmd += [
        "-f",
        "segment",
        "-segment_time",
        str(config.segment_seconds),
        "-segment_time_delta",
        "0.05",
        "-reset_timestamps",
        "1",
        output_pattern,
    ]

    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)

    approx_total_segments = int(math.ceil(duration_seconds / config.segment_seconds)) if duration_seconds > 0 else None
    segments_done = 0

    if progress_callback is not None and approx_total_segments is not None:
        progress_callback(0, approx_total_segments)

    try:
        for line in process.stdout:  # type: ignore[attr-defined]
            # Heuristic: count 'Opening' lines for each segment write
            if "Opening '" in line and "for writing" in line:
                segments_done += 1
                if progress_callback is not None and approx_total_segments is not None:
                    progress_callback(min(segments_done, approx_total_segments), approx_total_segments)
        process.wait()
        if process.returncode != 0:
            raise RuntimeError("ffmpeg завершился с ошибкой")
    finally:
        try:
            process.stdout.close()  # type: ignore[union-attr]
        except Exception:
            pass


class App:
    def __init__(self, root: Tk):
        self.root = root
        self.root.title("Нарезчик видео — 15с")

        self.video_path_var = StringVar()
        self.output_dir_var = StringVar()
        self.segment_len_var = StringVar(value="15")
        self.fast_copy_var = BooleanVar(value=False)
        self.status_var = StringVar(value="Готово")
        self.audio_choice_var = StringVar(value="")
        self._audio_tracks: List[Dict[str, str]] = []

        pad = dict(padx=10, pady=6)

        Label(root, text="Видео файл:").grid(row=0, column=0, sticky="w", **pad)
        Entry(root, textvariable=self.video_path_var, width=50).grid(row=0, column=1, **pad)
        Button(root, text="Выбрать...", command=self.choose_video).grid(row=0, column=2, **pad)

        Label(root, text="Папка вывода:").grid(row=1, column=0, sticky="w", **pad)
        Entry(root, textvariable=self.output_dir_var, width=50).grid(row=1, column=1, **pad)
        Button(root, text="Папка...", command=self.choose_output_dir).grid(row=1, column=2, **pad)

        Label(root, text="Длина сегмента (сек):").grid(row=2, column=0, sticky="w", **pad)
        Entry(root, textvariable=self.segment_len_var, width=10).grid(row=2, column=1, sticky="w", **pad)

        Checkbutton(root, text="Быстро (без перекодирования)", variable=self.fast_copy_var).grid(row=2, column=2, sticky="w", **pad)

        Label(root, text="Аудиодорожка:").grid(row=3, column=0, sticky="w", **pad)
        self.audio_combo = ttk.Combobox(root, textvariable=self.audio_choice_var, width=48, state="readonly")
        self.audio_combo.grid(row=3, column=1, columnspan=2, sticky="we", **pad)
        self.audio_combo["values"] = ["(нет данных)"]

        self.progress = ttk.Progressbar(root, orient="horizontal", length=460, mode="determinate")
        self.progress.grid(row=4, column=0, columnspan=3, padx=10, pady=12)

        self.start_button = Button(root, text="Нарезать", command=self.start_slicing)
        self.start_button.grid(row=5, column=0, columnspan=3, **pad)

        self.status_label = Label(root, textvariable=self.status_var)
        self.status_label.grid(row=6, column=0, columnspan=3, sticky="w", **pad)

        # macOS/Windows: set a reasonable window size
        root.minsize(700, 260)

    def choose_video(self):
        path = filedialog.askopenfilename(title="Выберите видео файл", filetypes=[("Видео", "*.mp4 *.mov *.mkv *.avi *.m4v *.webm"), ("Все файлы", "*.*")])
        if path:
            self.video_path_var.set(path)
            # Suggest output dir next to the input file
            suggest = os.path.join(os.path.dirname(path), "clips")
            self.output_dir_var.set(suggest)
            # Load audio tracks
            tracks = list_audio_tracks(path)
            self._audio_tracks = tracks
            if tracks:
                values = [t["label"] for t in tracks]
                self.audio_combo["values"] = values
                self.audio_combo.current(0)
            else:
                self.audio_combo["values"] = ["(аудио не найдено)"]
                self.audio_combo.set("(аудио не найдено)")

    def choose_output_dir(self):
        path = filedialog.askdirectory(title="Выберите папку для сохранения")
        if path:
            self.output_dir_var.set(path)

    def _selected_audio_index(self) -> Optional[int]:
        if not self._audio_tracks:
            return None
        current = self.audio_combo.get()
        for pos, track in enumerate(self._audio_tracks):
            if track.get("label") == current:
                # Map by position among audio streams, which corresponds to 0:a:<pos>
                return pos
        return None

    def start_slicing(self):
        input_path = self.video_path_var.get().strip()
        output_dir = self.output_dir_var.get().strip()

        if not input_path or not os.path.isfile(input_path):
            messagebox.showerror("Ошибка", "Выберите корректный видео файл")
            return
        if not output_dir:
            messagebox.showerror("Ошибка", "Укажите папку вывода")
            return
        if not is_ffmpeg_available():
            messagebox.showerror("FFmpeg не найден", "Установите ffmpeg и повторите попытку.")
            return

        try:
            seg = int(self.segment_len_var.get().strip())
            if seg <= 0:
                raise ValueError
        except Exception:
            messagebox.showerror("Ошибка", "Длина сегмента должна быть положительным целым числом")
            return

        config = SliceConfig(
            segment_seconds=seg,
            fast_copy=self.fast_copy_var.get(),
            audio_stream_index=self._selected_audio_index(),
        )

        self.progress.configure(mode="determinate")
        self.progress["value"] = 0
        self.status_var.set("В работе...")
        self.start_button.configure(state="disabled")

        def on_progress(done: int, total: int):
            pct = 0 if total == 0 else int(done * 100 / max(total, 1))
            self.progress["maximum"] = 100
            self.progress["value"] = pct
            self.status_var.set(f"Готово сегментов: {done}/{total}")

        def worker():
            try:
                slice_video_ffmpeg(input_path, output_dir, config, progress_callback=on_progress)
                self.status_var.set("Готово. Открываю папку...")
                self.progress["value"] = 100
                self.open_folder(output_dir)
            except Exception as exc:
                messagebox.showerror("Ошибка", str(exc))
            finally:
                self.start_button.configure(state="normal")
                if self.progress["value"] == 0:
                    self.progress.configure(mode="indeterminate")

        threading.Thread(target=worker, daemon=True).start()

    def open_folder(self, path: str):
        if sys.platform == "darwin":
            subprocess.call(["open", path])
        elif os.name == "nt":
            subprocess.call(["explorer", path])
        else:
            subprocess.call(["xdg-open", path])


if __name__ == "__main__":
    root = Tk()
    try:
        # Better looking themed widgets if available
        style = ttk.Style()
        if sys.platform == "darwin":
            style.theme_use("aqua")
        else:
            style.theme_use(style.theme_names()[0])
    except Exception:
        pass
    app = App(root)
    root.mainloop()
