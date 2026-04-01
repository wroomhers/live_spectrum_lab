#!/usr/bin/env python3
import math
import re
import subprocess
import threading
import time
import tkinter as tk
from array import array
from collections import deque


RATE = 24_000
CHANNELS = 2
CHUNK = 480
PREVIEW_SIZE = 2048


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
        sinks.append(
            {
                "id": match.group(2),
                "description": match.group(3).strip(),
                "default": bool(match.group(1)),
            }
        )
    return sinks


def detect_default_sink():
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


def sine_wave(phase):
    return math.sin(phase)


def square_wave(phase):
    return 1.0 if math.sin(phase) >= 0 else -1.0


def saw_wave(phase):
    cycle = (phase / (2 * math.pi)) % 1.0
    return 2.0 * cycle - 1.0


def tri_wave(phase):
    cycle = (phase / (2 * math.pi)) % 1.0
    return 1.0 - 4.0 * abs(cycle - 0.5)


WAVES = {
    "sine": sine_wave,
    "square": square_wave,
    "saw": saw_wave,
    "triangle": tri_wave,
}


class ToneEngine:
    def __init__(self, sink_id):
        self.lock = threading.Lock()
        self.process = None
        self.thread = None
        self.running = False
        self.sample_cursor = 0
        self.preview = deque([0.0] * PREVIEW_SIZE, maxlen=PREVIEW_SIZE)
        self.last_error = ""
        self.state = {
            "sink_id": sink_id,
            "waveform": "sine",
            "freq_a": 220.0,
            "freq_b": 440.0,
            "mix_b": 0.0,
            "gain": 0.22,
            "formula": "",
            "mode": "knob",
        }
        self.compiled_formula = None

    def set_state(self, **changes):
        with self.lock:
            self.state.update(changes)
            if "formula" in changes:
                self._compile_formula_locked()

    def get_state(self):
        with self.lock:
            return dict(self.state)

    def _compile_formula_locked(self):
        formula = self.state["formula"].strip()
        self.compiled_formula = None
        self.last_error = ""
        if not formula:
            return
        try:
            self.compiled_formula = compile(formula, "<formula>", "eval")
        except Exception as exc:
            self.last_error = str(exc)

    def start(self):
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._audio_loop, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                self.process.kill()

    def _restart_process(self, sink_id):
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                self.process.kill()
        self.process = subprocess.Popen(
            [
                "pw-play",
                "--target",
                str(sink_id),
                "--rate",
                str(RATE),
                "--channels",
                str(CHANNELS),
                "--format",
                "s16",
                "-",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            bufsize=0,
        )

    def _formula_sample(self, t, state):
        text = state["formula"].strip()
        if not text:
            return 0.0
        if re.fullmatch(r"\d+(\.\d+)?", text):
            freq = float(text)
            return sine_wave(2 * math.pi * freq * t)
        if re.fullmatch(r"\d+(\.\d+)?(\s*,\s*\d+(\.\d+)?)+", text):
            freqs = [float(item.strip()) for item in text.split(",")]
            return sum(sine_wave(2 * math.pi * freq * t) for freq in freqs) / len(freqs)
        if not self.compiled_formula:
            return 0.0

        def sine(freq):
            return sine_wave(2 * math.pi * freq * t)

        def square(freq):
            return square_wave(2 * math.pi * freq * t)

        def saw(freq):
            return saw_wave(2 * math.pi * freq * t)

        def tri(freq):
            return tri_wave(2 * math.pi * freq * t)

        safe_globals = {"__builtins__": {}}
        safe_locals = {
            "t": t,
            "pi": math.pi,
            "sin": math.sin,
            "cos": math.cos,
            "tan": math.tan,
            "abs": abs,
            "min": min,
            "max": max,
            "sine": sine,
            "square": square,
            "saw": saw,
            "tri": tri,
            "f1": state["freq_a"],
            "f2": state["freq_b"],
        }
        try:
            value = eval(self.compiled_formula, safe_globals, safe_locals)
            return float(value)
        except Exception as exc:
            self.last_error = str(exc)
            return 0.0

    def _knob_sample(self, t, state):
        wave = WAVES[state["waveform"]]
        sample = wave(2 * math.pi * state["freq_a"] * t)
        if state["mix_b"] > 0.0001 and state["freq_b"] > 0:
            sample += wave(2 * math.pi * state["freq_b"] * t) * state["mix_b"]
            sample /= 1.0 + state["mix_b"]
        return sample

    def _audio_loop(self):
        current_sink = None
        while self.running:
            state = self.get_state()
            if current_sink != state["sink_id"] or not self.process or self.process.poll() is not None:
                self._restart_process(state["sink_id"])
                current_sink = state["sink_id"]

            pcm = array("h")
            preview_chunk = []
            for offset in range(CHUNK):
                t = (self.sample_cursor + offset) / RATE
                if state["mode"] == "formula":
                    sample = self._formula_sample(t, state)
                else:
                    sample = self._knob_sample(t, state)
                sample = max(-1.0, min(1.0, sample * state["gain"]))
                preview_chunk.append(sample)
                value = int(sample * 32767)
                pcm.append(value)
                pcm.append(value)

            self.sample_cursor += CHUNK
            self.preview.extend(preview_chunk)
            if self.process and self.process.stdin:
                try:
                    self.process.stdin.write(pcm.tobytes())
                except BrokenPipeError:
                    current_sink = None


class ToneLabApp:
    def __init__(self, root):
        self.root = root
        self.sinks = list_output_sinks()
        default_sink = detect_default_sink()
        if not default_sink:
            raise RuntimeError("No output sink found")

        self.engine = ToneEngine(default_sink["id"])
        self.engine.start()
        self.canvas = tk.Canvas(root, width=1320, height=860, bg="#07111c", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)

        self.selected_sink = tk.StringVar(value=self._label_for_sink(default_sink["id"]))
        self.waveform_var = tk.StringVar(value="sine")
        self.freq_a = tk.DoubleVar(value=220.0)
        self.freq_b = tk.DoubleVar(value=440.0)
        self.mix_b = tk.DoubleVar(value=0.0)
        self.gain = tk.DoubleVar(value=0.22)
        self.status_var = tk.StringVar(value="Knob mode active")
        self.last_draw_error = ""
        self.scene_size = (0, 0)
        self.static_items_ready = False
        self.wave_line = None
        self.fft_line = None
        self.status_text_id = None

        self._build_controls()
        self.root.title("Tone Lab")
        self.root.configure(bg="#07111c")
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.after(30, self.update_ui)

    def _label_for_sink(self, sink_id):
        for sink in self.sinks:
            if sink["id"] == sink_id:
                prefix = "default" if sink["default"] else "sink"
                return f"{prefix} | {sink['description']} | id={sink['id']}"
        return f"sink | id={sink_id}"

    def _sink_id_from_label(self, label):
        match = re.search(r"id=(\d+)$", label)
        return match.group(1) if match else detect_default_sink()["id"]

    def _build_controls(self):
        options = [self._label_for_sink(sink["id"]) for sink in self.sinks]
        self.sink_menu = tk.OptionMenu(self.root, self.selected_sink, *options, command=self.on_sink_change)
        self.wave_menu = tk.OptionMenu(self.root, self.waveform_var, "sine", "square", "saw", "triangle", command=self.on_control_change)
        for widget in [self.sink_menu, self.wave_menu]:
            widget.config(
                bg="#112233",
                fg="#f2f7fb",
                activebackground="#1d3c56",
                activeforeground="#f2f7fb",
                highlightthickness=0,
                bd=0,
                font=("DejaVu Sans Mono", 10),
            )
            widget["menu"].config(
                bg="#112233",
                fg="#f2f7fb",
                activebackground="#1d3c56",
                activeforeground="#f2f7fb",
                font=("DejaVu Sans Mono", 10),
            )

        self.scale_a = self._make_scale(self.freq_a, 20, 2000, "POT A")
        self.scale_b = self._make_scale(self.freq_b, 0, 2000, "POT B")
        self.scale_mix = self._make_scale(self.mix_b, 0, 1, "MIX B", resolution=0.01)
        self.scale_gain = self._make_scale(self.gain, 0.01, 0.8, "GAIN", resolution=0.01)

        self.formula_box = tk.Text(
            self.root,
            width=44,
            height=14,
            bg="#0a1320",
            fg="#e7f4ff",
            insertbackground="#e7f4ff",
            highlightthickness=1,
            highlightbackground="#173041",
            relief="flat",
            font=("DejaVu Sans Mono", 11),
        )
        self.formula_box.insert(
            "1.0",
            "200\n\n# examples\n200,400\n0.6*sine(200)+0.4*sine(400)\n0.7*square(220)\n0.4*sine(f1)+0.4*saw(f2)",
        )

        self.apply_button = tk.Button(
            self.root,
            text="Apply Formula",
            command=self.apply_formula,
            bg="#112233",
            fg="#f2f7fb",
            activebackground="#1d3c56",
            activeforeground="#f2f7fb",
            bd=0,
            highlightthickness=0,
            font=("DejaVu Sans Mono", 10, "bold"),
            padx=12,
            pady=4,
        )
        self.knob_button = tk.Button(
            self.root,
            text="Use Knobs",
            command=self.use_knobs,
            bg="#112233",
            fg="#f2f7fb",
            activebackground="#1d3c56",
            activeforeground="#f2f7fb",
            bd=0,
            highlightthickness=0,
            font=("DejaVu Sans Mono", 10, "bold"),
            padx=12,
            pady=4,
        )

    def _make_scale(self, variable, frm, to, label, resolution=1.0):
        scale = tk.Scale(
            self.root,
            from_=frm,
            to=to,
            orient="horizontal",
            variable=variable,
            resolution=resolution,
            command=lambda _value: self.on_control_change(),
            bg="#0a1320",
            fg="#e7f4ff",
            troughcolor="#173041",
            activebackground="#53c8f3",
            highlightthickness=0,
            bd=0,
            relief="flat",
            length=320,
            font=("DejaVu Sans Mono", 10),
            label=label,
        )
        return scale

    def on_sink_change(self, label):
        self.engine.set_state(sink_id=self._sink_id_from_label(label))

    def on_control_change(self, *_args):
        self.engine.set_state(
            waveform=self.waveform_var.get(),
            freq_a=self.freq_a.get(),
            freq_b=self.freq_b.get(),
            mix_b=self.mix_b.get(),
            gain=self.gain.get(),
        )
        if self.engine.get_state()["mode"] == "knob":
            self.status_var.set("Knob mode active")

    def apply_formula(self):
        text = self.formula_box.get("1.0", "end").strip().splitlines()[0].strip()
        self.engine.set_state(
            formula=text,
            mode="formula",
            waveform=self.waveform_var.get(),
            freq_a=self.freq_a.get(),
            freq_b=self.freq_b.get(),
            mix_b=self.mix_b.get(),
            gain=self.gain.get(),
        )
        if self.engine.last_error:
            self.status_var.set(f"Formula error: {self.engine.last_error}")
        else:
            self.status_var.set(f"Formula mode: {text}")

    def use_knobs(self):
        self.engine.set_state(mode="knob")
        self.status_var.set("Knob mode active")

    def _fft_preview(self, samples):
        if len(samples) < PREVIEW_SIZE:
            return []
        prepared = [complex(samples[i] * (0.5 - 0.5 * math.cos((2 * math.pi * i) / (PREVIEW_SIZE - 1))), 0.0) for i in range(PREVIEW_SIZE)]
        bins = fft(prepared)[: PREVIEW_SIZE // 2]
        magnitudes = [abs(value) for value in bins]
        preview = []
        for index in range(72):
            lo = int(index * len(magnitudes) / 72)
            hi = max(lo + 1, int((index + 1) * len(magnitudes) / 72))
            level = math.sqrt(sum(value * value for value in magnitudes[lo:hi]) / max(1, hi - lo))
            preview.append(min(1.0, level / (3.0 + level)))
        return preview

    def update_ui(self):
        self.draw_scene()
        self.root.after(33, self.update_ui)

    def _draw_static_scene(self, width, height):
        self.canvas.delete("all")
        self.canvas.create_rectangle(0, 0, width, height, fill="#07111c", outline="")
        self.canvas.create_rectangle(0, 0, width, height * 0.22, fill="#0b1d30", outline="")
        self.canvas.create_oval(-120, -120, width * 0.34, height * 0.42, fill="#102846", outline="")
        self.canvas.create_oval(width * 0.60, -100, width + 180, height * 0.36, fill="#0d3b3d", outline="")

        self.canvas.create_text(30, 18, anchor="nw", fill="#f2f7fb", font=("DejaVu Sans Mono", 16, "bold"), text="TONE LAB")
        self.canvas.create_text(30, 42, anchor="nw", fill="#8eb2c7", font=("DejaVu Sans Mono", 9), text="interactive frequency generator")
        self.status_text_id = self.canvas.create_text(30, 60, anchor="nw", fill="#8eb2c7", font=("DejaVu Sans Mono", 9), text=self.status_var.get())

        self.canvas.create_text(30, 90, anchor="nw", fill="#9cb6c7", font=("DejaVu Sans Mono", 9), text="output device")
        self.canvas.create_window(136, 88, anchor="nw", window=self.sink_menu)
        self.canvas.create_text(30, 132, anchor="nw", fill="#9cb6c7", font=("DejaVu Sans Mono", 9), text="waveform")
        self.canvas.create_window(136, 130, anchor="nw", window=self.wave_menu)

        self.canvas.create_window(34, 190, anchor="nw", window=self.scale_a)
        self.canvas.create_window(34, 270, anchor="nw", window=self.scale_b)
        self.canvas.create_window(34, 350, anchor="nw", window=self.scale_mix)
        self.canvas.create_window(34, 430, anchor="nw", window=self.scale_gain)

        right_left = width * 0.52
        self.canvas.create_text(right_left, 90, anchor="nw", fill="#9cb6c7", font=("DejaVu Sans Mono", 9), text="text / formula input")
        self.canvas.create_window(right_left, 118, anchor="nw", window=self.formula_box)
        self.canvas.create_window(right_left, 392, anchor="nw", window=self.apply_button)
        self.canvas.create_window(right_left + 148, 392, anchor="nw", window=self.knob_button)

        graph_left = 30
        graph_right = width - 30
        wave_top = height * 0.62
        wave_bottom = height * 0.80
        fft_top = height * 0.83
        fft_bottom = height - 34

        self.canvas.create_rectangle(graph_left, wave_top, graph_right, wave_bottom, fill="#0a1320", outline="#173041")
        self.canvas.create_text(graph_left + 10, wave_top + 8, anchor="nw", fill="#9cb6c7", font=("DejaVu Sans Mono", 9), text="generated waveform")
        self.wave_line = self.canvas.create_line(0, 0, 1, 1, fill="#9bf6ff", width=2, smooth=True)

        self.canvas.create_rectangle(graph_left, fft_top, graph_right, fft_bottom, fill="#0a1320", outline="#173041")
        self.canvas.create_text(graph_left + 10, fft_top + 8, anchor="nw", fill="#9cb6c7", font=("DejaVu Sans Mono", 9), text="fourier / output preview")
        self.fft_line = self.canvas.create_line(0, 0, 1, 1, fill="#ff9f68", width=2, smooth=True)
        self.scene_size = (width, height)
        self.static_items_ready = True

    def draw_scene(self):
        width = max(self.canvas.winfo_width(), 1040)
        height = max(self.canvas.winfo_height(), 760)
        if not self.static_items_ready or self.scene_size != (width, height):
            self._draw_static_scene(width, height)

        self.canvas.itemconfigure(self.status_text_id, text=self.status_var.get())

        preview_samples = list(self.engine.preview)
        fft_preview = self._fft_preview(preview_samples)
        graph_left = 30
        graph_right = width - 30
        wave_top = height * 0.62
        wave_bottom = height * 0.80
        fft_top = height * 0.83
        fft_bottom = height - 34

        wave_points = []
        if preview_samples:
            wave_mid = (wave_top + wave_bottom) / 2
            wave_amp = (wave_bottom - wave_top) * 0.38
            for index, sample in enumerate(preview_samples[-1024:]):
                x = graph_left + (graph_right - graph_left) * (index / 1023)
                y = wave_mid - sample * wave_amp
                wave_points.extend((x, y))
        if wave_points:
            self.canvas.coords(self.wave_line, *wave_points)
        else:
            self.canvas.coords(self.wave_line, 0, 0, 1, 1)

        fft_points = []
        fft_height = fft_bottom - fft_top - 24
        fft_width = graph_right - graph_left - 20
        for index, value in enumerate(fft_preview):
            x = graph_left + 10 + fft_width * (index / max(1, len(fft_preview) - 1))
            y = fft_bottom - 10 - (value ** 0.8) * fft_height
            fft_points.extend((x, y))
        if fft_points:
            self.canvas.coords(self.fft_line, *fft_points)
        else:
            self.canvas.coords(self.fft_line, 0, 0, 1, 1)

    def close(self):
        self.engine.stop()
        self.root.destroy()


def main():
    root = tk.Tk()
    ToneLabApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
