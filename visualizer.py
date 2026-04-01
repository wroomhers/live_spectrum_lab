#!/usr/bin/env python3
import argparse
import math
import os
import queue
import re
import subprocess
import sys
import threading
import time
import tkinter as tk
from array import array
from collections import deque


RATE = 48_000
CHANNELS = 2
FORMAT = "s16"
WINDOW_SIZE = 2048
FRAME_SIZE = 512
HISTORY_SECONDS = 2.8
BAND_SMOOTHING = 0.72
BAND_DECAY = 0.92
SILENCE_RMS_THRESHOLD = 0.006
REFERENCE_LEVEL = 1.6
FLOOR_RISE = 0.18
FLOOR_FALL = 0.003
FLOOR_MARGIN = 0.05
BANDS = [
    {"label": "SUB", "lo": 30, "hi": 60, "color": "#44c2f0"},
    {"label": "KICK", "lo": 60, "hi": 100, "color": "#53c8f3"},
    {"label": "LOW BASS", "lo": 100, "hi": 150, "color": "#52d9e8"},
    {"label": "UPPER BASS", "lo": 150, "hi": 220, "color": "#4ee3b8"},
    {"label": "LOW MID A", "lo": 220, "hi": 320, "color": "#77e36f"},
    {"label": "LOW MID B", "lo": 320, "hi": 480, "color": "#c7e25a"},
    {"label": "MID A", "lo": 480, "hi": 720, "color": "#f6d365"},
    {"label": "MID B", "lo": 720, "hi": 1100, "color": "#f4bf58"},
    {"label": "PRESENCE A", "lo": 1100, "hi": 1800, "color": "#ffb15c"},
    {"label": "PRESENCE B", "lo": 1800, "hi": 2800, "color": "#ff9f68"},
    {"label": "TREBLE", "lo": 2800, "hi": 4200, "color": "#ff8a74"},
    {"label": "AIR", "lo": 4200, "hi": 7000, "color": "#ff7790"},
    {"label": "SPARKLE", "lo": 7000, "hi": 12000, "color": "#ff6f91"},
]


def run_command(args):
    return subprocess.run(args, capture_output=True, text=True, check=False)


def list_output_sinks():
    status = run_command(["wpctl", "status"])
    sinks = []
    in_sinks = False
    for raw_line in status.stdout.splitlines():
        line = raw_line.rstrip()
        if "Sinks:" in line:
            in_sinks = True
            continue
        if in_sinks and "Sink endpoints:" in line:
            break
        if not in_sinks:
            continue
        match = re.search(r"(\*)?\s*(\d+)\.\s+(.+?)\s+\[vol:", line.strip())
        if not match:
            continue
        is_default = bool(match.group(1))
        sink_id = match.group(2)
        description = match.group(3).strip()
        sinks.append({"id": sink_id, "description": description, "default": is_default})
    return sinks


def detect_default_sink_target():
    sinks = list_output_sinks()
    for sink in sinks:
        if sink["default"]:
            return sink
    return sinks[0] if sinks else None


def fft(values):
    n = len(values)
    j = 0
    for i in range(1, n):
        bit = n >> 1
        while j & bit:
            j ^= bit
            bit >>= 1
        j ^= bit
        if i < j:
            values[i], values[j] = values[j], values[i]

    length = 2
    while length <= n:
        angle = -2.0 * math.pi / length
        step = complex(math.cos(angle), math.sin(angle))
        half = length // 2
        for start in range(0, n, length):
            factor = 1 + 0j
            for offset in range(half):
                even = values[start + offset]
                odd = values[start + offset + half] * factor
                values[start + offset] = even + odd
                values[start + offset + half] = even - odd
                factor *= step
        length <<= 1
    return values


def interpolate_color(left, right, mix):
    return tuple(int(left[i] + (right[i] - left[i]) * mix) for i in range(3))


def rgb_hex(rgb):
    return "#%02x%02x%02x" % rgb


def subdivide_band(band, count=6):
    lo = band["lo"]
    hi = band["hi"]
    if hi - lo <= 40:
        return []

    edges = []
    if lo > 0 and hi / lo > 1.8:
        for index in range(count + 1):
            value = lo * ((hi / lo) ** (index / count))
            edges.append(int(round(value)))
    else:
        for index in range(count + 1):
            value = lo + (hi - lo) * (index / count)
            edges.append(int(round(value)))

    normalized = [edges[0]]
    for edge in edges[1:]:
        normalized.append(max(normalized[-1] + 1, edge))
    normalized[-1] = hi

    palette_start = (74, 206, 243)
    palette_end = (255, 115, 145)
    bands = []
    for index in range(count):
        child_lo = normalized[index]
        child_hi = normalized[index + 1]
        mix = index / max(1, count - 1)
        color = rgb_hex(interpolate_color(palette_start, palette_end, mix))
        bands.append(
            {
                "label": f"{child_lo}-{child_hi}",
                "lo": child_lo,
                "hi": child_hi,
                "color": color,
            }
        )
    return bands


class PipeWireCapture:
    def __init__(self, target, rate=RATE, channels=CHANNELS):
        self.target = target
        self.rate = rate
        self.channels = channels
        self.process = None
        self.thread = None
        self.running = False
        self.samples = deque(maxlen=rate * 4)
        self.errors = queue.Queue()

    def start(self):
        cmd = [
            "gst-launch-1.0",
            "-q",
            "pipewiresrc",
            f"target-object={self.target}",
            "!",
            "audioconvert",
            "!",
            f"audio/x-raw,format=S16LE,channels={self.channels},rate={self.rate}",
            "!",
            "fdsink",
            "fd=1",
        ]
        self.process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )
        self.running = True
        self.thread = threading.Thread(target=self._reader_loop, daemon=True)
        self.thread.start()
        threading.Thread(target=self._stderr_loop, daemon=True).start()

    def _reader_loop(self):
        chunk_bytes = 8192
        while self.running and self.process and self.process.stdout:
            data = self.process.stdout.read(chunk_bytes)
            if not data:
                break
            pcm = array("h")
            pcm.frombytes(data)
            if sys.byteorder != "little":
                pcm.byteswap()
            if self.channels == 2:
                mono = [
                    (pcm[i] + pcm[i + 1]) // 2
                    for i in range(0, len(pcm) - 1, 2)
                ]
            else:
                mono = pcm.tolist()
            self.samples.extend(mono)
        self.running = False

    def _stderr_loop(self):
        if not self.process or not self.process.stderr:
            return
        for line in self.process.stderr:
            text = line.decode("utf-8", errors="replace").strip()
            if text:
                self.errors.put(text)

    def latest(self, size):
        if len(self.samples) < size:
            return []
        return list(self.samples)[-size:]

    def probe(self, seconds):
        self.start()
        start = time.time()
        while time.time() - start < seconds:
            if not self.running:
                break
            time.sleep(0.05)
        captured = len(self.samples)
        self.stop()
        return captured

    def stop(self):
        self.running = False
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                self.process.kill()


class SpectrumApp:
    def __init__(self, root, capture, target, sinks):
        self.root = root
        self.capture = capture
        self.target = target
        self.sinks = sinks
        self.canvas = tk.Canvas(root, width=1320, height=860, bg="#07111c", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.window = [0.5 - 0.5 * math.cos((2 * math.pi * i) / (WINDOW_SIZE - 1)) for i in range(WINDOW_SIZE)]
        self.frame_window = [0.5 - 0.5 * math.cos((2 * math.pi * i) / (FRAME_SIZE - 1)) for i in range(FRAME_SIZE)]
        history_size = int(RATE * HISTORY_SECONDS)
        self.history_frames = max(64, history_size // FRAME_SIZE)
        self.last_stats = {"peak_freq": 0.0, "energy": 0.0, "active": False, "fft": []}
        self.selected_sink = tk.StringVar()
        self.selected_sink.set(self._label_for_target(target))
        self.view_stack = [self._make_view(BANDS, "full range")]
        self.lane_hitboxes = []
        self.hover_info = None
        self.hover_box = None
        self.device_menu = None
        self.back_button = None
        self.canvas.bind("<Motion>", self.on_mouse_move)
        self.canvas.bind("<Leave>", self.on_mouse_leave)
        self.canvas.bind("<Button-1>", self.on_left_click)
        self.canvas.bind("<Button-2>", self.on_middle_click)
        self.canvas.bind("<Button-3>", self.on_right_click)
        self.root.title("Live Spectrum Lab")
        self.root.configure(bg="#07111c")
        self.root.bind("<Escape>", lambda _: self.close())
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.after(10, self.update_frame)

    @property
    def current_view(self):
        return self.view_stack[-1]

    def _make_view(self, bands, title):
        return {
            "title": title,
            "bands": bands,
            "ranges": self._build_band_ranges(bands),
            "histories": [deque([0.0] * self.history_frames, maxlen=self.history_frames) for _ in bands],
            "peaks": [0.0] * len(bands),
            "floors": [0.02] * len(bands),
            "markers": [],
        }

    def _build_band_ranges(self, bands):
        nyquist = RATE / 2
        ranges = []
        for band in bands:
            low_bin = max(1, int(band["lo"] / nyquist * (FRAME_SIZE // 2)))
            high_bin = max(low_bin + 1, int(band["hi"] / nyquist * (FRAME_SIZE // 2)))
            ranges.append((low_bin, min(high_bin, FRAME_SIZE // 2)))
        return ranges

    def _label_for_target(self, target):
        for sink in self.sinks:
            if sink["id"] == target:
                prefix = "default" if sink["default"] else "sink"
                return f"{prefix} | {sink['description']} | id={sink['id']}"
        return f"sink | id={target}"

    def _target_from_label(self, label):
        match = re.search(r"id=(\d+)$", label)
        return match.group(1) if match else self.target

    def _reset_views(self):
        self.view_stack = [self._make_view(BANDS, "full range")]

    def switch_target(self, label):
        new_target = self._target_from_label(label)
        if new_target == self.target:
            return
        self.capture.stop()
        self.target = new_target
        self.capture = PipeWireCapture(target=new_target)
        self._reset_views()
        self.hover_info = None
        self.capture.start()

    def close(self):
        self.capture.stop()
        self.root.destroy()

    def _build_fft_preview(self, magnitudes):
        if not magnitudes:
            return []
        start_bin = max(1, int(30 / (RATE / WINDOW_SIZE)))
        end_bin = min(len(magnitudes), int(12000 / (RATE / WINDOW_SIZE)))
        window = magnitudes[start_bin:end_bin]
        if not window:
            return []
        chunks = 84
        preview = []
        for index in range(chunks):
            lo = int(index * len(window) / chunks)
            hi = max(lo + 1, int((index + 1) * len(window) / chunks))
            level = math.sqrt(sum(value * value for value in window[lo:hi]) / max(1, hi - lo))
            normalized = level / (REFERENCE_LEVEL * 1.8 + level)
            preview.append(min(1.0, normalized))
        return preview

    def _update_view_from_frames(self, view, frame_magnitudes, active):
        if active:
            frame_values = [[] for _ in view["bands"]]
            for magnitudes in frame_magnitudes:
                for band_index, (start_bin, end_bin) in enumerate(view["ranges"]):
                    band_slice = magnitudes[start_bin:end_bin]
                    raw_level = math.sqrt(sum(value * value for value in band_slice) / max(1, len(band_slice)))
                    floor = view["floors"][band_index]
                    if raw_level <= floor:
                        floor += (raw_level - floor) * FLOOR_RISE
                    else:
                        floor += (raw_level - floor) * FLOOR_FALL
                    view["floors"][band_index] = floor
                    lifted = max(0.0, raw_level - floor - FLOOR_MARGIN)
                    normalized = lifted / (REFERENCE_LEVEL + lifted)
                    frame_values[band_index].append(min(1.0, normalized * 0.9))

            for band_index, values in enumerate(frame_values):
                for value in values:
                    previous = view["histories"][band_index][-1] if view["histories"][band_index] else 0.0
                    smoothed = max(value * BAND_SMOOTHING + previous * (1.0 - BAND_SMOOTHING), previous * BAND_DECAY)
                    view["histories"][band_index].append(smoothed)
                    view["peaks"][band_index] = max(smoothed, view["peaks"][band_index] * 0.965)
        else:
            for band_index in range(len(view["bands"])):
                view["peaks"][band_index] = 0.0

    def _seed_view_from_history(self, view):
        samples = self.capture.latest(self.history_frames * FRAME_SIZE)
        if not samples:
            return
        centered = [sample / 32768.0 for sample in samples]
        mean = sum(centered) / len(centered)
        centered = [sample - mean for sample in centered]
        frame_count = len(centered) // FRAME_SIZE
        frames = []
        for frame_index in range(frame_count):
            start_sample = frame_index * FRAME_SIZE
            frame = centered[start_sample:start_sample + FRAME_SIZE]
            prepared_frame = [complex(frame[i] * self.frame_window[i], 0.0) for i in range(FRAME_SIZE)]
            frame_bins = fft(prepared_frame)[: FRAME_SIZE // 2]
            frames.append([abs(value) for value in frame_bins])
        rms = math.sqrt(sum(value * value for value in centered) / max(1, len(centered)))
        self._update_view_from_frames(view, frames, rms >= SILENCE_RMS_THRESHOLD)

    def go_back(self):
        if len(self.view_stack) > 1:
            self.view_stack.pop()
            self.hover_info = None

    def update_frame(self):
        if not self.capture.running and not self.capture.latest(WINDOW_SIZE):
            self.draw_status("PipeWire akisi gelmiyor. Muzik caliyor ve hedef dogru mu kontrol et.")
            self.root.after(250, self.update_frame)
            return

        samples = self.capture.latest(WINDOW_SIZE)
        if not samples:
            self.draw_status("Veri bekleniyor...")
            self.root.after(30, self.update_frame)
            return

        timeline, waveform, stats = self.analyze(samples)
        self.last_stats = stats
        self.draw_scene(timeline, waveform, stats)
        self.root.after(33, self.update_frame)

    def analyze(self, samples):
        centered = [sample / 32768.0 for sample in samples]
        mean = sum(centered) / len(centered)
        centered = [sample - mean for sample in centered]
        waveform = centered[-896:]

        prepared = [complex(centered[i] * self.window[i], 0.0) for i in range(WINDOW_SIZE)]
        bins = fft(prepared)[: WINDOW_SIZE // 2]
        magnitudes = [abs(value) for value in bins]
        fft_preview = self._build_fft_preview(magnitudes)

        rms = math.sqrt(sum(value * value for value in centered) / len(centered))
        active = rms >= SILENCE_RMS_THRESHOLD
        peak_freq = 0.0
        if active:
            peak_bin = max(range(1, len(magnitudes)), key=lambda idx: magnitudes[idx])
            peak_freq = peak_bin * RATE / WINDOW_SIZE

        frame_count = len(centered) // FRAME_SIZE
        frame_magnitudes = []
        for frame_index in range(frame_count):
            start_sample = frame_index * FRAME_SIZE
            frame = centered[start_sample:start_sample + FRAME_SIZE]
            prepared_frame = [complex(frame[i] * self.frame_window[i], 0.0) for i in range(FRAME_SIZE)]
            frame_bins = fft(prepared_frame)[: FRAME_SIZE // 2]
            frame_magnitudes.append([abs(value) for value in frame_bins])

        for view in self.view_stack:
            self._update_view_from_frames(view, frame_magnitudes, active)

        timeline = [list(history) for history in self.current_view["histories"]]
        return timeline, waveform, {"peak_freq": peak_freq, "energy": rms, "active": active, "fft": fft_preview}

    def _ensure_controls(self):
        options = [self._label_for_target(sink["id"]) for sink in self.sinks]
        if self.device_menu is None:
            self.device_menu = tk.OptionMenu(self.root, self.selected_sink, *options, command=self.switch_target)
            self.device_menu.config(
                bg="#112233",
                fg="#f2f7fb",
                activebackground="#1d3c56",
                activeforeground="#f2f7fb",
                highlightthickness=0,
                bd=0,
                font=("DejaVu Sans Mono", 9),
            )
            self.device_menu["menu"].config(
                bg="#112233",
                fg="#f2f7fb",
                activebackground="#1d3c56",
                activeforeground="#f2f7fb",
                font=("DejaVu Sans Mono", 9),
            )
        if self.back_button is None:
            self.back_button = tk.Button(
                self.root,
                text="Back",
                command=self.go_back,
                bg="#112233",
                fg="#f2f7fb",
                activebackground="#1d3c56",
                activeforeground="#f2f7fb",
                bd=0,
                highlightthickness=0,
                font=("DejaVu Sans Mono", 9, "bold"),
                padx=10,
                pady=2,
            )

    def draw_scene(self, timeline, waveform, stats):
        width = max(self.canvas.winfo_width(), 960)
        height = max(self.canvas.winfo_height(), 720)
        self.canvas.delete("all")
        self.lane_hitboxes = []
        self._ensure_controls()

        self.canvas.create_rectangle(0, 0, width, height, fill="#07111c", outline="")
        self.canvas.create_rectangle(0, 0, width, height * 0.22, fill="#0b1d30", outline="")
        self.canvas.create_oval(-120, -120, width * 0.33, height * 0.42, fill="#102846", outline="")
        self.canvas.create_oval(width * 0.58, -90, width + 180, height * 0.38, fill="#0d3b3d", outline="")

        self.canvas.create_text(30, 18, anchor="nw", fill="#f2f7fb", font=("DejaVu Sans Mono", 16, "bold"), text="LIVE SPECTRUM LAB")
        self.canvas.create_text(30, 42, anchor="nw", fill="#8eb2c7", font=("DejaVu Sans Mono", 9), text=f"view: {self.current_view['title']}  sink: {self.target}")
        self.canvas.create_text(
            30,
            60,
            anchor="nw",
            fill="#8eb2c7",
            font=("DejaVu Sans Mono", 9),
            text=f"peak: {stats['peak_freq']:.0f} Hz   rms: {stats['energy']:.4f}   state: {'active' if stats['active'] else 'silent'}   timeline: {HISTORY_SECONDS:.1f}s",
        )

        self.canvas.create_text(30, 84, anchor="nw", fill="#9cb6c7", font=("DejaVu Sans Mono", 9), text="output device")
        self.canvas.create_window(136, 82, anchor="nw", window=self.device_menu)
        if len(self.view_stack) > 1:
            self.canvas.create_window(30, 112, anchor="nw", window=self.back_button)

        fft_left = width - 360
        fft_top = 18
        fft_right = width - 26
        fft_bottom = 102
        self.canvas.create_rectangle(fft_left, fft_top, fft_right, fft_bottom, fill="#0a1320", outline="#173041", width=1)
        self.canvas.create_text(fft_left + 10, fft_top + 8, anchor="nw", fill="#9cb6c7", font=("DejaVu Sans Mono", 9), text="fourier")
        fft_points = []
        fft_width = fft_right - fft_left - 20
        fft_height = fft_bottom - fft_top - 24
        for index, value in enumerate(stats["fft"]):
            x = fft_left + 10 + fft_width * (index / max(1, len(stats["fft"]) - 1))
            y = fft_bottom - 10 - (value ** 0.8) * fft_height
            fft_points.extend((x, y))
        if fft_points:
            self.canvas.create_line(fft_points, fill="#9bf6ff", width=2, smooth=True)

        graph_left = 30
        graph_right = width - 30
        graph_top = 150
        graph_bottom = height * 0.83
        graph_height = graph_bottom - graph_top
        usable_width = graph_right - graph_left
        lane_gap = 4
        lane_height = max(20, (graph_height - lane_gap * (len(self.current_view["bands"]) - 1)) / len(self.current_view["bands"]))

        for band_index, band in enumerate(self.current_view["bands"]):
            lane_top = graph_top + band_index * (lane_height + lane_gap)
            lane_bottom = lane_top + lane_height
            baseline_y = lane_bottom - 5
            ceiling_y = lane_top + 5
            drawable_height = max(8, baseline_y - ceiling_y)
            self.canvas.create_rectangle(graph_left, lane_top, graph_right, lane_bottom, fill="#0b1520", outline="#173041", width=1)
            self.canvas.create_line(graph_left, baseline_y, graph_right, baseline_y, fill="#1b3548", dash=(4, 8))

            values = timeline[band_index]
            points = []
            fill_points = [graph_left, baseline_y]
            for idx, value in enumerate(values):
                x = graph_left + usable_width * (idx / max(1, len(values) - 1))
                y = baseline_y - (value ** 1.1) * drawable_height
                points.extend((x, y))
                fill_points.extend((x, y))
            fill_points.extend((graph_right, baseline_y))
            self.canvas.create_polygon(fill_points, fill=band["color"], stipple="gray25", outline="")
            if points:
                self.canvas.create_line(points, fill=band["color"], width=2, smooth=True)

            peak = self.current_view["peaks"][band_index]
            peak_y = baseline_y - (peak ** 1.1) * drawable_height
            self.canvas.create_line(graph_left, peak_y, graph_right, peak_y, fill="#f6f2c4", dash=(2, 6))

            for marker in self.current_view["markers"]:
                if marker["band_index"] != band_index:
                    continue
                mx = graph_left + usable_width * (marker["frame_index"] / max(1, self.history_frames - 1))
                my = baseline_y - (marker["value"] ** 1.1) * drawable_height
                self.canvas.create_line(mx, lane_top + 1, mx, lane_bottom - 1, fill="#ffd166", dash=(2, 3))
                self.canvas.create_oval(mx - 3, my - 3, mx + 3, my + 3, fill="#ffd166", outline="")

            self.canvas.create_text(graph_left + 10, lane_top + 4, anchor="nw", fill="#d9ebf7", font=("DejaVu Sans Mono", 9, "bold"), text=band["label"])
            self.canvas.create_text(graph_right - 10, lane_top + 4, anchor="ne", fill="#8fb2c4", font=("DejaVu Sans Mono", 8), text=f"{band['lo']}-{band['hi']} Hz")

            self.lane_hitboxes.append(
                {
                    "band_index": band_index,
                    "left": graph_left,
                    "right": graph_right,
                    "top": lane_top,
                    "bottom": lane_bottom,
                    "baseline_y": baseline_y,
                    "drawable_height": drawable_height,
                }
            )

        for label, pos in [("older", 0.0), ("mid", 0.5), ("now", 1.0)]:
            x = graph_left + usable_width * pos
            self.canvas.create_line(x, graph_top, x, graph_bottom, fill="#112433", dash=(2, 10))
            self.canvas.create_text(x, graph_bottom + 14, fill="#89a6b8", font=("DejaVu Sans Mono", 8), text=label)

        wave_top = height * 0.86
        wave_bottom = height - 34
        wave_mid = (wave_top + wave_bottom) / 2
        wave_amp = (wave_bottom - wave_top) * 0.42
        wave_points = []
        for index, sample in enumerate(waveform):
            x = graph_left + usable_width * (index / max(1, len(waveform) - 1))
            y = wave_mid - sample * wave_amp
            wave_points.extend((x, y))
        self.canvas.create_text(graph_left, wave_top - 10, anchor="sw", fill="#89a6b8", font=("DejaVu Sans Mono", 8), text="full mix waveform")
        if wave_points:
            self.canvas.create_line(wave_points, fill="#9bf6ff", width=2, smooth=True)
        self.canvas.create_rectangle(graph_left, wave_top, graph_right, wave_bottom, outline="#1d3446", width=1)

        if self.hover_info:
            tooltip_x = min(width - 190, self.hover_info["x"] + 14)
            tooltip_y = max(18, self.hover_info["y"] - 36)
            self.canvas.create_rectangle(tooltip_x, tooltip_y, tooltip_x + 176, tooltip_y + 42, fill="#09131d", outline="#33506a")
            self.canvas.create_text(
                tooltip_x + 8,
                tooltip_y + 8,
                anchor="nw",
                fill="#e8f3fb",
                font=("DejaVu Sans Mono", 8),
                text=f"{self.hover_info['band']}  t={self.hover_info['time']:+.2f}s",
            )
            self.canvas.create_text(
                tooltip_x + 8,
                tooltip_y + 24,
                anchor="nw",
                fill="#9cb6c7",
                font=("DejaVu Sans Mono", 8),
                text=f"height={self.hover_info['value']:.3f}  freq={self.hover_info['freq']}",
            )

    def _lane_at(self, event):
        for lane in self.lane_hitboxes:
            if lane["left"] <= event.x <= lane["right"] and lane["top"] <= event.y <= lane["bottom"]:
                return lane
        return None

    def _frame_index_from_x(self, lane, x):
        ratio = (x - lane["left"]) / max(1, lane["right"] - lane["left"])
        ratio = min(1.0, max(0.0, ratio))
        return int(round(ratio * max(1, self.history_frames - 1)))

    def on_mouse_move(self, event):
        lane = self._lane_at(event)
        if not lane:
            self.hover_info = None
            return
        frame_index = self._frame_index_from_x(lane, event.x)
        values = list(self.current_view["histories"][lane["band_index"]])
        value = values[min(frame_index, len(values) - 1)] if values else 0.0
        time_offset = -HISTORY_SECONDS + (frame_index / max(1, self.history_frames - 1)) * HISTORY_SECONDS
        band = self.current_view["bands"][lane["band_index"]]
        self.hover_info = {
            "x": event.x,
            "y": event.y,
            "band": band["label"],
            "time": time_offset,
            "value": value,
            "freq": f"{band['lo']}-{band['hi']} Hz",
        }

    def on_mouse_leave(self, _event):
        self.hover_info = None

    def on_right_click(self, event):
        lane = self._lane_at(event)
        if not lane:
            return
        frame_index = self._frame_index_from_x(lane, event.x)
        values = list(self.current_view["histories"][lane["band_index"]])
        value = values[min(frame_index, len(values) - 1)] if values else 0.0
        self.current_view["markers"].append({"band_index": lane["band_index"], "frame_index": frame_index, "value": value})

    def on_middle_click(self, event):
        lane = self._lane_at(event)
        if not lane or not self.current_view["markers"]:
            return
        frame_index = self._frame_index_from_x(lane, event.x)
        candidates = [
            (idx, abs(marker["frame_index"] - frame_index))
            for idx, marker in enumerate(self.current_view["markers"])
            if marker["band_index"] == lane["band_index"]
        ]
        if not candidates:
            return
        marker_index, distance = min(candidates, key=lambda item: item[1])
        if distance <= max(2, self.history_frames // 20):
            self.current_view["markers"].pop(marker_index)

    def on_left_click(self, event):
        lane = self._lane_at(event)
        if not lane:
            return
        selected_band = self.current_view["bands"][lane["band_index"]]
        child_bands = subdivide_band(selected_band)
        if not child_bands:
            return
        title = f"{selected_band['lo']}-{selected_band['hi']} Hz"
        child_view = self._make_view(child_bands, title)
        self._seed_view_from_history(child_view)
        self.view_stack.append(child_view)
        self.hover_info = None

    def draw_status(self, text):
        width = max(self.canvas.winfo_width(), 960)
        height = max(self.canvas.winfo_height(), 720)
        self.canvas.delete("all")
        self.canvas.create_rectangle(0, 0, width, height, fill="#07111c", outline="")
        self.canvas.create_text(width / 2, height / 2 - 18, fill="#f2f7fb", font=("DejaVu Sans Mono", 20, "bold"), text="LIVE SPECTRUM LAB")
        self.canvas.create_text(width / 2, height / 2 + 12, fill="#9cb6c7", font=("DejaVu Sans Mono", 11), text=text)

def parse_args():
    parser = argparse.ArgumentParser(description="Real-time PipeWire spectrum visualizer.")
    parser.add_argument("--target", help="PipeWire output sink id. Default: active sink.")
    parser.add_argument("--list-targets", action="store_true", help="List available output sinks.")
    parser.add_argument("--probe-seconds", type=float, help="Capture without GUI for a short test.")
    return parser.parse_args()


def main():
    args = parse_args()

    if args.list_targets:
        for sink in list_output_sinks():
            mark = "*" if sink["default"] else " "
            print(f"{mark} id={sink['id']}  {sink['description']}")
        return 0

    selected_sink = args.target or os.environ.get("PIPEWIRE_TARGET")
    if selected_sink:
        target = {"id": selected_sink, "description": f"Selected sink {selected_sink}", "default": False}
    else:
        target = detect_default_sink_target()

    if not target:
        print("PipeWire output sink bulunamadi. `python3 visualizer.py --list-targets` ile kontrol et.")
        return 1

    capture = PipeWireCapture(target=target["id"])

    if args.probe_seconds:
        samples = capture.probe(args.probe_seconds)
        if samples <= 0:
            print(f"Hedefe baglanildi ama ornek gelmedi: sink id {target['id']}")
            return 2
        print(f"Hedef aktif: sink id {target['id']}")
        print(f"Yakalanan mono ornek sayisi: {samples}")
        return 0

    capture.start()
    root = tk.Tk()
    SpectrumApp(root, capture, target["id"], list_output_sinks())
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
