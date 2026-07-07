import csv
import re
import sys
import time
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

import numpy as np

try:
    import serial
    import serial.tools.list_ports
except ImportError:
    messagebox.showerror("Thieu thu vien", "Can cai pyserial:\npip install pyserial")
    sys.exit(1)

try:
    import pywt
    HAS_PYWT = True
except ImportError:
    HAS_PYWT = False

import matplotlib
matplotlib.use("TkAgg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure


BG = "#0f172a"
PANEL = "#111827"
PANEL_ALT = "#172033"
SURFACE = "#1f2937"
BORDER = "#334155"
TEXT = "#e5e7eb"
MUTED = "#94a3b8"
ACCENT = "#38bdf8"
ACCENT_DARK = "#0f766e"
DANGER = "#ef4444"
PLOT_BG = "#0b1120"
GRID = "#334155"

BAUD_RATE = 115200
WAVELET_NAME = "db4"
WAVELET_LEVEL = 3
ECG_SAMPLE_RATE_HZ = 1000.0
ECG_HIGHPASS_HZ = 0.5
ECG_LOWPASS_HZ = 45.0
ECG_MAINS_HZ = 50.0
ECG_MAINS_NOTCH_WIDTH_HZ = 2.0
ECG_CLIP_LOW_THRESHOLD = 20.0
ECG_CLIP_HIGH_THRESHOLD = 4075.0
PPG_FALLBACK_SAMPLE_RATE_HZ = 25.0
PPG_HIGHPASS_HZ = 0.5
PPG_LOWPASS_HZ = 8.0
PPG_TREND_WINDOW_S = 1.2
MAX30102_ADC_MAX = 262143.0
BASE_DIR = Path("data_csv") / "SYNC"
RAW_DIR = BASE_DIR / "raw"
FILTERED_DIR = BASE_DIR / "filtered"
RAW_DIR.mkdir(parents=True, exist_ok=True)
FILTERED_DIR.mkdir(parents=True, exist_ok=True)


def safe_filename(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"[^a-zA-Z0-9_-]+", "_", text)
    return text.strip("_") or "unknown"


def wavelet_denoise(values: np.ndarray, wavelet_name: str = WAVELET_NAME, level: int = WAVELET_LEVEL) -> np.ndarray:
    values = np.asarray(values, dtype=float)
    if len(values) < 8:
        return values.copy()
    if not HAS_PYWT:
        return np.full(len(values), np.nan)

    wavelet = pywt.Wavelet(wavelet_name)
    max_level = pywt.dwt_max_level(data_len=len(values), filter_len=wavelet.dec_len)
    level = min(level, max_level)
    if level < 1:
        return values.copy()

    coeffs = pywt.wavedec(values, wavelet_name, mode="symmetric", level=level)
    sigma = np.median(np.abs(coeffs[-1])) / 0.6745 if len(coeffs[-1]) else 0.0
    threshold = sigma * np.sqrt(2 * np.log(len(values)))
    filtered_coeffs = [coeffs[0]]
    for detail in coeffs[1:]:
        filtered_coeffs.append(pywt.threshold(detail, value=threshold, mode="soft"))
    return pywt.waverec(filtered_coeffs, wavelet_name, mode="symmetric")[:len(values)]


def fft_ecg_band_clean(values: np.ndarray, sample_rate_hz: float = ECG_SAMPLE_RATE_HZ) -> np.ndarray:
    values = np.asarray(values, dtype=float)
    if len(values) < 8:
        return values.copy()

    baseline = float(np.nanmedian(values))
    centered = values - baseline
    spectrum = np.fft.rfft(centered)
    freqs = np.fft.rfftfreq(len(centered), d=1.0 / sample_rate_hz)

    keep = (freqs >= ECG_HIGHPASS_HZ) & (freqs <= ECG_LOWPASS_HZ)
    notch = np.abs(freqs - ECG_MAINS_HZ) <= (ECG_MAINS_NOTCH_WIDTH_HZ / 2.0)
    spectrum[~keep | notch] = 0

    return np.fft.irfft(spectrum, n=len(centered))


def ecg_denoise(values: np.ndarray) -> np.ndarray:
    cleaned = fft_ecg_band_clean(values)
    filtered = wavelet_denoise(cleaned, wavelet_name=WAVELET_NAME, level=WAVELET_LEVEL)
    return filtered - np.nanmedian(filtered)


def estimate_sample_rate_hz(time_ms: np.ndarray, fallback_hz: float = PPG_FALLBACK_SAMPLE_RATE_HZ) -> float:
    time_ms = np.asarray(time_ms, dtype=float)
    if len(time_ms) < 2:
        return fallback_hz

    dt_ms = np.diff(time_ms)
    dt_ms = dt_ms[np.isfinite(dt_ms) & (dt_ms > 0)]
    if len(dt_ms) == 0:
        return fallback_hz

    return 1000.0 / float(np.nanmedian(dt_ms))


def centered_moving_average(values: np.ndarray, window_samples: int) -> np.ndarray:
    values = np.asarray(values, dtype=float)
    if len(values) < 3:
        return np.full(len(values), np.nanmedian(values))

    window_samples = max(3, int(window_samples))
    if window_samples % 2 == 0:
        window_samples += 1
    if window_samples > len(values):
        window_samples = len(values) if len(values) % 2 == 1 else len(values) - 1
    if window_samples < 3:
        return np.full(len(values), np.nanmedian(values))

    pad = window_samples // 2
    padded = np.pad(values, (pad, pad), mode="edge")
    kernel = np.ones(window_samples, dtype=float) / float(window_samples)
    return np.convolve(padded, kernel, mode="valid")


def ppg_ac_component(values: np.ndarray, time_ms: np.ndarray) -> np.ndarray:
    values = np.asarray(values, dtype=float)
    sample_rate_hz = estimate_sample_rate_hz(time_ms)
    window_samples = int(round(PPG_TREND_WINDOW_S * sample_rate_hz))
    trend = centered_moving_average(values, window_samples)
    return values - trend


def fft_ppg_band_clean(values: np.ndarray, sample_rate_hz: float) -> np.ndarray:
    values = np.asarray(values, dtype=float)
    if len(values) < 8 or sample_rate_hz <= 0:
        return values - np.nanmedian(values)

    centered = values - np.nanmedian(values)
    spectrum = np.fft.rfft(centered)
    freqs = np.fft.rfftfreq(len(centered), d=1.0 / sample_rate_hz)
    lowpass_hz = min(PPG_LOWPASS_HZ, sample_rate_hz * 0.45)

    keep = (freqs >= PPG_HIGHPASS_HZ) & (freqs <= lowpass_hz)
    spectrum[~keep] = 0

    return np.fft.irfft(spectrum, n=len(centered))


def ppg_denoise(values: np.ndarray, time_ms: np.ndarray) -> np.ndarray:
    sample_rate_hz = estimate_sample_rate_hz(time_ms)
    ac = ppg_ac_component(values, time_ms)
    cleaned = fft_ppg_band_clean(ac, sample_rate_hz)
    filtered = wavelet_denoise(cleaned, wavelet_name=WAVELET_NAME, level=WAVELET_LEVEL)
    if np.all(np.isnan(filtered)):
        filtered = cleaned
    return filtered - np.nanmedian(filtered)


def summarize_signal_quality(rows: list["SyncRow"], duration_s: int) -> str:
    ecg = np.array([row.ecg_raw for row in rows if np.isfinite(row.ecg_raw)], dtype=float)
    ppg_rows = [row for row in rows if np.isfinite(row.ppg_ir_raw)]
    ppg = np.array([row.ppg_ir_raw for row in ppg_rows], dtype=float)
    ppg_time = np.array([row.time_ms for row in ppg_rows], dtype=float)
    notes: list[str] = []

    if len(ecg):
        clip_low = int(np.count_nonzero(ecg <= ECG_CLIP_LOW_THRESHOLD))
        clip_high = int(np.count_nonzero(ecg >= ECG_CLIP_HIGH_THRESHOLD))
        if clip_low or clip_high:
            notes.append(f"ECG clipping low={clip_low}, high={clip_high}")
        notes.append(f"ECG n={len(ecg)}")

    if len(ppg):
        rate = estimate_sample_rate_hz(ppg_time)
        ir_dc = float(np.nanmean(ppg))
        ir_ac = ppg_ac_component(ppg, ppg_time)
        ir_ac_rms = float(np.sqrt(np.nanmean(np.square(ir_ac)))) if len(ir_ac) else 0.0
        ir_acdc_percent = 100.0 * ir_ac_rms / max(abs(ir_dc), 1.0)
        saturated = int(np.count_nonzero(ppg >= MAX30102_ADC_MAX * 0.95))
        notes.append(f"PPG n={len(ppg)} Fs={rate:.1f}Hz IR_AC/DC={ir_acdc_percent:.2f}%")
        if saturated:
            notes.append(f"PPG saturated={saturated}")

    return " | ".join(notes)


@dataclass
class SyncRow:
    time_ms: int
    ecg_raw: float
    ppg_red_raw: float
    ppg_ir_raw: float


def parse_float_or_nan(text: str) -> float:
    text = text.strip()
    if not text:
        return np.nan
    return float(text)


def parse_sync_csv_line(line: str) -> SyncRow | None:
    parts = [p.strip() for p in line.split(",")]
    if len(parts) < 4:
        return None
    try:
        return SyncRow(
            time_ms=int(float(parts[0])),
            ecg_raw=parse_float_or_nan(parts[1]),
            ppg_red_raw=parse_float_or_nan(parts[2]),
            ppg_ir_raw=parse_float_or_nan(parts[3]),
        )
    except ValueError:
        return None


def normalize_sync_rows(rows: list[SyncRow]) -> list[SyncRow]:
    return [row for _, row in sorted(enumerate(rows), key=lambda item: (item[1].time_ms, item[0]))]


def load_sync_rows_from_file(path: Path) -> list[SyncRow]:
    rows: list[SyncRow] = []
    in_uart_block = False
    saw_uart_marker = False

    with path.open("r", encoding="utf-8", errors="ignore", newline="") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line:
                continue

            upper = line.upper()
            if upper.startswith("BEGIN_SYNC_CSV"):
                saw_uart_marker = True
                in_uart_block = True
                rows.clear()
                continue
            if upper.startswith("END_SYNC_CSV"):
                break
            if upper.startswith("TIME_MS"):
                continue

            if saw_uart_marker and not in_uart_block:
                continue

            # Saved raw CSV has person_name,time_ms,...; UART capture has time_ms,...
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 5 and parts[1].lower() == "time_ms":
                continue
            if len(parts) >= 5:
                line = ",".join(parts[1:5])

            row = parse_sync_csv_line(line)
            if row is not None:
                rows.append(row)

    return normalize_sync_rows(rows)


class SyncUARTMonitor:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("ECG + PPG Sync UART Logger")
        self.root.geometry("1240x780")
        self.root.minsize(1040, 660)
        self.root.configure(bg=BG)

        self.serial_obj = None
        self.worker = None
        self.stop_event = threading.Event()
        self.latest_raw_file = None
        self.latest_filtered_file = None

        self.port_var = tk.StringVar()
        self.person_var = tk.StringVar(value="unknown")
        self.duration_var = tk.StringVar(value="10")
        self.mode_var = tk.StringVar(value="BOTH")
        self.status_var = tk.StringVar(value="Ready")

        self.configure_styles()
        self.build_ui()
        self.refresh_ports()

    def configure_styles(self):
        self.style = ttk.Style(self.root)
        try:
            self.style.theme_use("clam")
        except tk.TclError:
            pass

        self.style.configure(".", background=BG, foreground=TEXT, font=("Segoe UI", 10))
        self.style.configure("App.TFrame", background=BG)
        self.style.configure("Panel.TFrame", background=PANEL, relief="flat")
        self.style.configure("Topbar.TFrame", background=PANEL)
        self.style.configure("TLabel", background=BG, foreground=TEXT)
        self.style.configure("Muted.TLabel", background=PANEL, foreground=MUTED, font=("Segoe UI", 9))
        self.style.configure("Title.TLabel", background=PANEL, foreground=TEXT, font=("Segoe UI Semibold", 15))
        self.style.configure("Status.TLabel", background=PANEL_ALT, foreground=TEXT, padding=(14, 8), font=("Segoe UI", 9))
        self.style.configure("Field.TLabel", background=PANEL, foreground=MUTED, font=("Segoe UI", 9))
        self.style.configure("Section.TLabel", background=PANEL, foreground=TEXT, font=("Segoe UI Semibold", 10))

        self.style.configure(
            "TButton",
            background=SURFACE,
            foreground=TEXT,
            bordercolor=BORDER,
            focusthickness=0,
            padding=(12, 7),
        )
        self.style.map(
            "TButton",
            background=[("active", "#27364a"), ("pressed", "#0f172a"), ("disabled", "#1e293b")],
            foreground=[("disabled", "#64748b")],
        )
        self.style.configure("Accent.TButton", background=ACCENT_DARK, foreground="#ecfeff", bordercolor=ACCENT_DARK)
        self.style.map("Accent.TButton", background=[("active", "#0d9488"), ("pressed", "#115e59")])
        self.style.configure("Danger.TButton", background="#7f1d1d", foreground="#fee2e2", bordercolor="#991b1b")
        self.style.map("Danger.TButton", background=[("active", "#991b1b"), ("pressed", "#450a0a")])

        for widget in ("TEntry", "TCombobox"):
            self.style.configure(
                widget,
                fieldbackground="#0b1220",
                background="#0b1220",
                foreground=TEXT,
                bordercolor=BORDER,
                lightcolor=BORDER,
                darkcolor=BORDER,
                insertcolor=TEXT,
                arrowsize=14,
                padding=5,
            )
            self.style.map(
                widget,
                fieldbackground=[("readonly", "#0b1220"), ("disabled", "#111827")],
                foreground=[("readonly", TEXT), ("disabled", "#64748b")],
                bordercolor=[("focus", ACCENT), ("active", ACCENT)],
            )

        self.root.option_add("*TCombobox*Listbox.background", "#0b1220")
        self.root.option_add("*TCombobox*Listbox.foreground", TEXT)
        self.root.option_add("*TCombobox*Listbox.selectBackground", ACCENT_DARK)
        self.root.option_add("*TCombobox*Listbox.selectForeground", "#ecfeff")

        self.style.configure(
            "TProgressbar",
            troughcolor="#0b1220",
            background=ACCENT,
            bordercolor=BORDER,
            lightcolor=ACCENT,
            darkcolor=ACCENT,
            thickness=10,
        )
        self.style.configure("TPanedwindow", background=BG)
        self.style.configure("Sash", background=BORDER)

    def build_ui(self):
        shell = ttk.Frame(self.root, style="App.TFrame", padding=14)
        shell.pack(fill="both", expand=True)

        top = ttk.Frame(shell, style="Topbar.TFrame", padding=(12, 10))
        top.pack(fill="x")
        top.columnconfigure(1, weight=1)

        title_group = ttk.Frame(top, style="Topbar.TFrame")
        title_group.grid(row=0, column=0, sticky="w")
        ttk.Label(title_group, text="ECG + PPG Sync Monitor", style="Title.TLabel").pack(anchor="w")
        ttk.Label(title_group, text="UART logger, CSV capture, FFT + wavelet preview", style="Muted.TLabel").pack(anchor="w", pady=(2, 0))

        actions = ttk.Frame(top, style="Topbar.TFrame")
        actions.grid(row=0, column=2, sticky="e")
        ttk.Button(actions, text="Start", style="Accent.TButton", command=self.start_measurement).pack(side="left", padx=(0, 8))
        ttk.Button(actions, text="Stop", style="Danger.TButton", command=self.stop_measurement).pack(side="left", padx=(0, 8))
        ttk.Button(actions, text="Open CSV", command=self.open_csv_file).pack(side="left")

        controls = ttk.Frame(shell, style="Panel.TFrame", padding=(12, 8))
        controls.pack(fill="x", pady=(8, 6))
        controls.columnconfigure(9, weight=1)

        ttk.Label(controls, text="COM PORT", style="Field.TLabel").grid(row=0, column=0, sticky="w")
        self.port_combo = ttk.Combobox(controls, textvariable=self.port_var, width=18, state="readonly")
        self.port_combo.grid(row=1, column=0, padx=(0, 8), pady=(4, 0), sticky="ew")
        ttk.Button(controls, text="Refresh", command=self.refresh_ports).grid(row=1, column=1, padx=(0, 18), pady=(4, 0), sticky="w")

        ttk.Label(controls, text="NGUOI DO", style="Field.TLabel").grid(row=0, column=2, sticky="w")
        ttk.Entry(controls, textvariable=self.person_var, width=18).grid(row=1, column=2, padx=(0, 18), pady=(4, 0), sticky="ew")

        ttk.Label(controls, text="MODE", style="Field.TLabel").grid(row=0, column=3, sticky="w")
        ttk.Combobox(controls, textvariable=self.mode_var, values=["BOTH", "ECG", "PPG"], width=9, state="readonly").grid(row=1, column=3, padx=(0, 18), pady=(4, 0), sticky="ew")

        ttk.Label(controls, text="THOI GIAN (S)", style="Field.TLabel").grid(row=0, column=4, sticky="w")
        ttk.Entry(controls, textvariable=self.duration_var, width=10).grid(row=1, column=4, padx=(0, 18), pady=(4, 0), sticky="ew")

        ttk.Label(controls, text="TIEN TRINH", style="Field.TLabel").grid(row=0, column=5, sticky="w")
        self.progress = ttk.Progressbar(controls, mode="determinate", length=220)
        self.progress.grid(row=1, column=5, columnspan=5, pady=(4, 0), sticky="ew")

        ttk.Label(shell, textvariable=self.status_var, style="Status.TLabel").pack(fill="x", pady=(0, 8))

        body = ttk.PanedWindow(shell, orient="horizontal")
        body.pack(fill="both", expand=True)

        plot_frame = ttk.Frame(body, style="Panel.TFrame", padding=8)
        body.add(plot_frame, weight=6)

        self.figure = Figure(figsize=(8.4, 5.2), dpi=100, facecolor=PLOT_BG)
        self.ax_ecg = self.figure.add_subplot(211)
        self.ax_ppg = self.figure.add_subplot(212, sharex=self.ax_ecg)
        self.style_axes()
        self.canvas = FigureCanvasTkAgg(self.figure, master=plot_frame)
        canvas_widget = self.canvas.get_tk_widget()
        canvas_widget.configure(bg=PLOT_BG, highlightthickness=0)
        canvas_widget.pack(fill="both", expand=True)
        toolbar = NavigationToolbar2Tk(self.canvas, plot_frame)
        toolbar.configure(bg=PANEL)
        for child in toolbar.winfo_children():
            try:
                child.configure(bg=PANEL)
            except tk.TclError:
                pass

        log_frame = ttk.Frame(body, style="Panel.TFrame", padding=8, width=260)
        body.add(log_frame, weight=1)
        ttk.Label(log_frame, text="UART log", style="Section.TLabel").pack(anchor="w", pady=(0, 8))
        self.log_text = tk.Text(
            log_frame,
            height=10,
            wrap="none",
            bg="#070d1a",
            fg="#cbd5e1",
            insertbackground=TEXT,
            selectbackground=ACCENT_DARK,
            selectforeground="#ecfeff",
            relief="flat",
            borderwidth=0,
            highlightthickness=1,
            highlightbackground=BORDER,
            highlightcolor=ACCENT,
            padx=10,
            pady=10,
            font=("Consolas", 9),
        )
        self.log_text.pack(fill="both", expand=True)

    def style_axes(self):
        for ax in (self.ax_ecg, self.ax_ppg):
            ax.set_facecolor(PLOT_BG)
            ax.tick_params(colors=MUTED, labelsize=9)
            ax.xaxis.label.set_color(TEXT)
            ax.yaxis.label.set_color(TEXT)
            ax.title.set_color(TEXT)
            for spine in ax.spines.values():
                spine.set_color(BORDER)
            ax.grid(True, color=GRID, alpha=0.28, linewidth=0.7)

    def refresh_ports(self):
        ports = [p.device for p in serial.tools.list_ports.comports()]
        self.port_combo["values"] = ports
        if ports and not self.port_var.get():
            self.port_var.set(ports[0])

    def set_status(self, text: str):
        self.root.after(0, lambda: self.status_var.set(text))

    def log(self, text: str):
        def append():
            self.log_text.insert("end", text + "\n")
            self.log_text.see("end")
        self.root.after(0, append)

    def start_measurement(self):
        if self.worker and self.worker.is_alive():
            messagebox.showwarning("Dang do", "Dang co phien do khac.")
            return
        if not self.port_var.get():
            messagebox.showerror("COM", "Chua chon cong COM.")
            return
        try:
            duration_s = int(self.duration_var.get())
            if duration_s <= 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("Thoi gian", "Thoi gian do phai la so nguyen duong.")
            return

        self.stop_event.clear()
        self.progress["maximum"] = duration_s
        self.progress["value"] = 0
        self.worker = threading.Thread(target=self.measure_worker, args=(duration_s,), daemon=True)
        self.worker.start()
        self.update_progress(duration_s, time.time())

    def stop_measurement(self):
        self.stop_event.set()
        if self.serial_obj and self.serial_obj.is_open:
            try:
                self.serial_obj.write(b"STOP\n")
            except Exception:
                pass
        self.set_status("Dang dung...")

    def update_progress(self, duration_s: int, start_time: float):
        if not (self.worker and self.worker.is_alive()):
            return
        elapsed = min(duration_s, time.time() - start_time)
        self.progress["value"] = elapsed
        self.root.after(200, lambda: self.update_progress(duration_s, start_time))

    def open_csv_file(self):
        initial_dir = RAW_DIR if RAW_DIR.exists() else Path.cwd()
        filename = filedialog.askopenfilename(
            title="Chon file CSV raw/capture",
            initialdir=str(initial_dir),
            filetypes=[
                ("CSV/Text files", "*.csv *.txt *.log"),
                ("All files", "*.*"),
            ],
        )
        if not filename:
            return

        path = Path(filename)
        try:
            rows = load_sync_rows_from_file(path)
            if not rows:
                raise ValueError("Khong tim thay dong time_ms,ecg_raw,ppg_red_raw,ppg_ir_raw hop le.")
            self.plot_rows(rows, path.name)
            self.set_status(f"Da mo file: {path}")
            self.log(f"[OPEN] {path}")
        except Exception as exc:
            messagebox.showerror("Open CSV Error", str(exc))
            self.set_status(f"ERROR: {exc}")

    def measure_worker(self, duration_s: int):
        mode = self.mode_var.get().upper()
        person = self.person_var.get().strip() or "unknown"
        port = self.port_var.get()

        try:
            self.set_status(f"Mo {port}...")
            with serial.Serial(port, BAUD_RATE, timeout=1.0) as ser:
                self.serial_obj = ser
                time.sleep(0.3)
                ser.reset_input_buffer()

                board_mode = "BOTH" if mode == "BOTH" else ("ECG" if mode == "ECG" else "PPG")
                ser.write((board_mode + "\n").encode("utf-8"))
                time.sleep(0.1)
                ser.write((f"START {duration_s}\n").encode("utf-8"))
                self.log(f"> {board_mode}")
                self.log(f"> START {duration_s}")
                self.set_status("Dang do tren ESP32, du lieu se gui sau khi do xong...")

                rows = self.read_sync_block(ser, timeout_s=duration_s + 25)
                if self.stop_event.is_set():
                    self.set_status("Da dung.")
                    return
                if not rows:
                    raise RuntimeError("Khong nhan duoc du lieu CSV tu ESP32.")

                raw_file = self.save_raw_csv(rows, person, mode)
                filtered_file = self.save_filtered_csv(rows, person, mode)
                quality = summarize_signal_quality(rows, duration_s)
                self.latest_raw_file = raw_file
                self.latest_filtered_file = filtered_file
                self.root.after(0, lambda: self.plot_rows(rows, raw_file.name))
                self.set_status(f"Da luu raw: {raw_file.name} | filtered: {filtered_file.name} | {quality}")
        except Exception as exc:
            self.set_status(f"ERROR: {exc}")
            self.root.after(0, lambda: messagebox.showerror("UART Error", str(exc)))
        finally:
            self.serial_obj = None
            self.root.after(0, lambda: self.progress.configure(value=0))

    def read_sync_block(self, ser: serial.Serial, timeout_s: float) -> list[SyncRow]:
        deadline = time.time() + timeout_s
        in_block = False
        rows: list[SyncRow] = []

        while time.time() < deadline and not self.stop_event.is_set():
            raw = ser.readline()
            if not raw:
                continue
            line = raw.decode("utf-8", errors="ignore").strip()
            if not line:
                continue
            self.log(line)

            upper = line.upper()
            if upper.startswith("BEGIN_SYNC_CSV"):
                in_block = True
                rows.clear()
                continue
            if upper.startswith("END_SYNC_CSV"):
                return normalize_sync_rows(rows)
            if not in_block:
                continue
            if upper.startswith("TIME_MS"):
                continue

            row = parse_sync_csv_line(line)
            if row is not None:
                rows.append(row)

        raise TimeoutError("Het thoi gian cho block BEGIN_SYNC_CSV/END_SYNC_CSV.")

    def make_file_base(self, person: str, mode: str) -> str:
        ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        return f"{safe_filename(person)}_{mode}_sync_{ts}"

    def save_raw_csv(self, rows: list[SyncRow], person: str, mode: str) -> Path:
        rows = normalize_sync_rows(rows)
        path = RAW_DIR / f"{self.make_file_base(person, mode)}_raw.csv"
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["person_name", "time_ms", "ecg_raw", "ppg_red_raw", "ppg_ir_raw"])
            for row in rows:
                writer.writerow([
                    person,
                    row.time_ms,
                    "" if np.isnan(row.ecg_raw) else f"{row.ecg_raw:.0f}",
                    "" if np.isnan(row.ppg_red_raw) else f"{row.ppg_red_raw:.0f}",
                    "" if np.isnan(row.ppg_ir_raw) else f"{row.ppg_ir_raw:.0f}",
                ])
        return path

    def save_filtered_csv(self, rows: list[SyncRow], person: str, mode: str) -> Path:
        rows = normalize_sync_rows(rows)
        path = FILTERED_DIR / f"{self.make_file_base(person, mode)}_wavelet.csv"
        ecg_filtered, ppg_filtered = self.compute_filtered(rows)

        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "person_name", "time_ms",
                "ecg_raw", f"ecg_centered_bandpass_wavelet_{WAVELET_NAME}_level{WAVELET_LEVEL}",
                "ppg_ir_raw", f"ppg_ir_ac_bandpass_wavelet_{WAVELET_NAME}_level{WAVELET_LEVEL}",
                "ppg_red_raw",
            ])
            for i, row in enumerate(rows):
                writer.writerow([
                    person,
                    row.time_ms,
                    "" if np.isnan(row.ecg_raw) else f"{row.ecg_raw:.0f}",
                    "" if np.isnan(ecg_filtered[i]) else f"{ecg_filtered[i]:.6f}",
                    "" if np.isnan(row.ppg_ir_raw) else f"{row.ppg_ir_raw:.0f}",
                    "" if np.isnan(ppg_filtered[i]) else f"{ppg_filtered[i]:.6f}",
                    "" if np.isnan(row.ppg_red_raw) else f"{row.ppg_red_raw:.0f}",
                ])
        return path

    def compute_filtered(self, rows: list[SyncRow]) -> tuple[np.ndarray, np.ndarray]:
        rows = normalize_sync_rows(rows)
        ecg_filtered = np.full(len(rows), np.nan)
        ppg_filtered = np.full(len(rows), np.nan)

        ecg_idx = np.array([i for i, row in enumerate(rows) if not np.isnan(row.ecg_raw)], dtype=int)
        if len(ecg_idx):
            ecg_values = np.array([rows[i].ecg_raw for i in ecg_idx], dtype=float)
            ecg_filtered[ecg_idx] = ecg_denoise(ecg_values)

        ppg_idx = np.array([i for i, row in enumerate(rows) if not np.isnan(row.ppg_ir_raw)], dtype=int)
        if len(ppg_idx):
            ppg_values = np.array([rows[i].ppg_ir_raw for i in ppg_idx], dtype=float)
            ppg_time_ms = np.array([rows[i].time_ms for i in ppg_idx], dtype=float)
            ppg_filtered[ppg_idx] = ppg_denoise(ppg_values, ppg_time_ms)

        return ecg_filtered, ppg_filtered

    def plot_rows(self, rows: list[SyncRow], title: str):
        rows = normalize_sync_rows(rows)
        ecg_filtered, ppg_filtered = self.compute_filtered(rows)
        t = np.array([row.time_ms / 1000.0 for row in rows], dtype=float)
        ecg = np.array([row.ecg_raw for row in rows], dtype=float)
        ppg = np.array([row.ppg_ir_raw for row in rows], dtype=float)
        ecg_mask = np.isfinite(ecg)
        if ecg_mask.any():
            ecg_baseline = np.nanmedian(ecg[ecg_mask])
            ecg = ecg - ecg_baseline
            filtered_mask = np.isfinite(ecg_filtered)
            if filtered_mask.any():
                ecg_filtered = ecg_filtered - np.nanmedian(ecg_filtered[filtered_mask])

        self.ax_ecg.clear()
        self.ax_ppg.clear()
        self.style_axes()

        if ecg_mask.any():
            self.ax_ecg.plot(t[ecg_mask], ecg[ecg_mask], color="#8aa0b8", linewidth=0.85, alpha=0.72, label="ECG RAW")
            self.ax_ecg.plot(t[ecg_mask], ecg_filtered[ecg_mask], color="#fb7185", linewidth=1.2, label="ECG wavelet")
        self.ax_ecg.set_title("ECG", loc="left", color=TEXT, fontsize=11, fontweight="semibold", pad=6)
        self.ax_ecg.set_ylabel("ECG centered")
        self.ax_ecg.legend(loc="upper right", facecolor=PANEL, edgecolor=BORDER, labelcolor=TEXT)

        ppg_mask = np.isfinite(ppg)
        if ppg_mask.any():
            ppg_time_ms = np.array([row.time_ms for row in rows], dtype=float)
            ppg_ac = np.full(len(rows), np.nan)
            ppg_ac[ppg_mask] = ppg_ac_component(ppg[ppg_mask], ppg_time_ms[ppg_mask])
            self.ax_ppg.plot(t[ppg_mask], ppg_ac[ppg_mask], color="#8aa0b8", linewidth=0.85, alpha=0.72, label="PPG IR AC")
            self.ax_ppg.plot(t[ppg_mask], ppg_filtered[ppg_mask], color="#34d399", linewidth=1.2, label="PPG bandpass + wavelet")
        self.ax_ppg.set_title("PPG", loc="left", color=TEXT, fontsize=11, fontweight="semibold", pad=6)
        self.ax_ppg.set_xlabel("Time (s)")
        self.ax_ppg.set_ylabel("PPG IR AC")
        self.ax_ppg.legend(loc="upper right", facecolor=PANEL, edgecolor=BORDER, labelcolor=TEXT)

        self.figure.suptitle(title, color=TEXT, fontsize=11)
        self.figure.tight_layout()
        self.canvas.draw_idle()


def main():
    root = tk.Tk()
    SyncUARTMonitor(root)
    root.mainloop()


if __name__ == "__main__":
    main()
