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

import matplotlib
matplotlib.use("TkAgg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure


BG = "#f8fafc"
PANEL = "#ffffff"
PANEL_ALT = "#eef2f7"
SURFACE = "#e5e7eb"
BORDER = "#cbd5e1"
TEXT = "#111827"
MUTED = "#64748b"
ACCENT = "#2563eb"
ACCENT_DARK = "#1d4ed8"
DANGER = "#ef4444"
PLOT_BG = "#ffffff"
GRID = "#dbe3ef"

BAUD_RATE = 115200
ECG_SAMPLE_RATE_HZ = 400.0
ECG_HIGHPASS_HZ = 0.5
ECG_LOWPASS_HZ = 45.0
ECG_CLIP_LOW_THRESHOLD = 20.0
ECG_CLIP_HIGH_THRESHOLD = 4075.0
PPG_FALLBACK_SAMPLE_RATE_HZ = 400.0
PPG_HIGHPASS_HZ = 0.5
PPG_LOWPASS_HZ = 8.0
MAX30102_ADC_MAX = 262143.0
PTT_MIN_MS = 80.0
PTT_MAX_MS = 600.0
BASE_DIR = Path("data_csv") / "SYNC"
RAW_DIR = BASE_DIR / "raw"
FILTERED_DIR = BASE_DIR / "filtered"
RAW_DIR.mkdir(parents=True, exist_ok=True)
FILTERED_DIR.mkdir(parents=True, exist_ok=True)


def safe_filename(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"[^a-zA-Z0-9_-]+", "_", text)
    return text.strip("_") or "unknown"


def estimate_sample_rate_hz(time_ms: np.ndarray, fallback_hz: float = PPG_FALLBACK_SAMPLE_RATE_HZ) -> float:
    time_ms = np.asarray(time_ms, dtype=float)
    if len(time_ms) < 2:
        return fallback_hz

    dt_ms = np.diff(time_ms)
    dt_ms = dt_ms[np.isfinite(dt_ms) & (dt_ms > 0)]
    if len(dt_ms) == 0:
        return fallback_hz

    return 1000.0 / float(np.nanmedian(dt_ms))


def fft_bandpass(values: np.ndarray, sample_rate_hz: float, highpass_hz: float, lowpass_hz: float) -> np.ndarray:
    values = np.asarray(values, dtype=float)
    if len(values) < 8 or sample_rate_hz <= 0:
        return values.copy()

    spectrum = np.fft.rfft(values)
    freqs = np.fft.rfftfreq(len(values), d=1.0 / sample_rate_hz)
    lowpass_hz = min(lowpass_hz, sample_rate_hz * 0.45)
    keep = (freqs >= highpass_hz) & (freqs <= lowpass_hz)
    spectrum[~keep] = 0

    return np.fft.irfft(spectrum, n=len(values))


def ecg_bandpass(values: np.ndarray, time_ms: np.ndarray) -> np.ndarray:
    sample_rate_hz = estimate_sample_rate_hz(time_ms, ECG_SAMPLE_RATE_HZ)
    return fft_bandpass(values, sample_rate_hz, ECG_HIGHPASS_HZ, ECG_LOWPASS_HZ)


def ppg_bandpass(values: np.ndarray, time_ms: np.ndarray) -> np.ndarray:
    sample_rate_hz = estimate_sample_rate_hz(time_ms, PPG_FALLBACK_SAMPLE_RATE_HZ)
    return fft_bandpass(values, sample_rate_hz, PPG_HIGHPASS_HZ, PPG_LOWPASS_HZ)


def summarize_signal_quality(rows: list["SyncRow"], duration_s: int) -> str:
    ecg = np.array([row.ecg_raw for row in rows if np.isfinite(row.ecg_raw)], dtype=float)
    ppg_rows = [row for row in rows if np.isfinite(row.ppg_ir_raw)]
    ppg = np.array([row.ppg_ir_raw for row in ppg_rows], dtype=float)
    ppg_time = np.array([row.time_us / 1000.0 for row in ppg_rows], dtype=float)
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
        ir_ac = ppg_bandpass(ppg, ppg_time)
        ir_ac_rms = float(np.sqrt(np.nanmean(np.square(ir_ac)))) if len(ir_ac) else 0.0
        ir_acdc_percent = 100.0 * ir_ac_rms / max(abs(ir_dc), 1.0)
        saturated = int(np.count_nonzero(ppg >= MAX30102_ADC_MAX * 0.95))
        notes.append(f"PPG n={len(ppg)} Fs={rate:.1f}Hz IR_AC/DC={ir_acdc_percent:.2f}%")
        if saturated:
            notes.append(f"PPG saturated={saturated}")

    return " | ".join(notes)


@dataclass
class SyncRow:
    time_us: int
    ecg_raw: float
    ppg_red_raw: float
    ppg_ir_raw: float


@dataclass
class DerivedMetrics:
    instant_bpm: float = np.nan
    sdnn_ms: float = np.nan
    rmssd_ms: float = np.nan
    ptt_ms: float = np.nan
    spo2_percent: float = np.nan
    perfusion_index_percent: float = np.nan
    ecg_peak_count: int = 0
    ppg_peak_count: int = 0
    ptt_pair_count: int = 0
    pulse_source: str = "--"


def parse_float_or_nan(text: str) -> float:
    text = text.strip()
    if not text:
        return np.nan
    return float(text)


def parse_sync_csv_line(line: str, time_unit: str = "us") -> SyncRow | None:
    parts = [p.strip() for p in line.split(",")]
    if len(parts) < 4:
        return None
    try:
        time_value = float(parts[0])
        time_us = int(round(time_value * 1000.0)) if time_unit == "ms" else int(round(time_value))
        return SyncRow(
            time_us=time_us,
            ecg_raw=parse_float_or_nan(parts[1]),
            ppg_red_raw=parse_float_or_nan(parts[2]),
            ppg_ir_raw=parse_float_or_nan(parts[3]),
        )
    except ValueError:
        return None


def normalize_sync_rows(rows: list[SyncRow]) -> list[SyncRow]:
    return [row for _, row in sorted(enumerate(rows), key=lambda item: (item[1].time_us, item[0]))]


def rows_time_ms(rows: list[SyncRow]) -> np.ndarray:
    return np.array([row.time_us / 1000.0 for row in rows], dtype=float)


def load_sync_rows_from_file(path: Path) -> list[SyncRow]:
    rows: list[SyncRow] = []
    in_uart_block = False
    saw_uart_marker = False
    uart_time_unit = "us"

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
            if upper.startswith("TIME_US"):
                uart_time_unit = "us"
                continue
            if upper.startswith("TIME_MS"):
                uart_time_unit = "ms"
                continue

            if saw_uart_marker and not in_uart_block:
                continue

            parts = [p.strip() for p in line.split(",")]
            lower_parts = [p.lower() for p in parts]
            if "time_us" in lower_parts or "time_ms" in lower_parts:
                continue
            if len(parts) >= 8:
                line = ",".join([parts[1], parts[3], parts[7], parts[5]])
                row = parse_sync_csv_line(line, "us")
            elif len(parts) >= 7:
                line = ",".join([parts[1], parts[2], parts[6], parts[4]])
                row = parse_sync_csv_line(line, "ms")
            elif len(parts) >= 6:
                line = ",".join([parts[1], parts[3], parts[4], parts[5]])
                row = parse_sync_csv_line(line, "us")
            elif len(parts) >= 5:
                line = ",".join(parts[1:5])
                row = parse_sync_csv_line(line, "ms")
            else:
                row = parse_sync_csv_line(line, uart_time_unit)

            if row is not None:
                rows.append(row)

    return normalize_sync_rows(rows)


def finite_std(values: np.ndarray, ddof: int = 0) -> float:
    values = np.asarray(values, dtype=float)
    values = values[np.isfinite(values)]
    if len(values) <= ddof:
        return np.nan
    return float(np.std(values, ddof=ddof))


def rms(values: np.ndarray) -> float:
    values = np.asarray(values, dtype=float)
    values = values[np.isfinite(values)]
    if len(values) == 0:
        return np.nan
    return float(np.sqrt(np.mean(np.square(values))))


def robust_mad(values: np.ndarray) -> float:
    values = np.asarray(values, dtype=float)
    values = values[np.isfinite(values)]
    if len(values) == 0:
        return np.nan
    median = float(np.median(values))
    mad = float(np.median(np.abs(values - median)))
    return 1.4826 * mad


def compact_peak_candidates(candidate_idx: np.ndarray, score: np.ndarray, min_distance_samples: int) -> np.ndarray:
    if len(candidate_idx) == 0:
        return np.array([], dtype=int)

    min_distance_samples = max(1, int(min_distance_samples))
    selected: list[int] = []
    for idx in sorted(candidate_idx, key=lambda i: score[i], reverse=True):
        if all(abs(idx - chosen) >= min_distance_samples for chosen in selected):
            selected.append(int(idx))
    return np.array(sorted(selected), dtype=int)


def detect_peaks(
    time_ms: np.ndarray,
    values: np.ndarray,
    *,
    min_distance_s: float,
    threshold_scale: float,
    use_abs: bool = False,
) -> np.ndarray:
    time_ms = np.asarray(time_ms, dtype=float)
    values = np.asarray(values, dtype=float)
    mask = np.isfinite(time_ms) & np.isfinite(values)
    time_ms = time_ms[mask]
    values = values[mask]
    if len(values) < 5:
        return np.array([], dtype=float)

    signal = np.abs(values) if use_abs else values.copy()
    signal = signal - np.nanmedian(signal)
    scale = robust_mad(signal)
    if not np.isfinite(scale) or scale <= 1e-9:
        scale = finite_std(signal)
    if not np.isfinite(scale) or scale <= 1e-9:
        return np.array([], dtype=float)

    threshold = max(float(np.nanmedian(signal) + threshold_scale * scale), float(np.nanpercentile(signal, 70)))
    candidate_mask = (signal[1:-1] >= signal[:-2]) & (signal[1:-1] > signal[2:]) & (signal[1:-1] > threshold)
    candidate_idx = np.flatnonzero(candidate_mask) + 1
    if len(candidate_idx) == 0:
        return np.array([], dtype=float)

    sample_rate_hz = estimate_sample_rate_hz(time_ms)
    min_distance_samples = int(round(min_distance_s * sample_rate_hz))
    peak_idx = compact_peak_candidates(candidate_idx, signal, min_distance_samples)
    return time_ms[peak_idx]


def choose_ppg_peak_times(time_ms: np.ndarray, values: np.ndarray, expected_count: int | None = None) -> np.ndarray:
    positive = detect_peaks(time_ms, values, min_distance_s=0.35, threshold_scale=0.45, use_abs=False)
    negative = detect_peaks(time_ms, -np.asarray(values, dtype=float), min_distance_s=0.35, threshold_scale=0.45, use_abs=False)

    if expected_count and expected_count > 0:
        return min((positive, negative), key=lambda peaks: abs(len(peaks) - expected_count))
    return positive if len(positive) >= len(negative) else negative


def valid_rr_intervals_ms(peak_times_ms: np.ndarray) -> np.ndarray:
    peak_times_ms = np.asarray(peak_times_ms, dtype=float)
    rr_ms = np.diff(peak_times_ms)
    return rr_ms[np.isfinite(rr_ms) & (rr_ms >= 300.0) & (rr_ms <= 2000.0)]


def compute_derived_metrics(rows: list[SyncRow], ecg_filtered: np.ndarray, ppg_filtered: np.ndarray) -> DerivedMetrics:
    rows = normalize_sync_rows(rows)
    metrics = DerivedMetrics()
    if not rows:
        return metrics

    time_ms = rows_time_ms(rows)
    ecg_filtered = np.asarray(ecg_filtered, dtype=float)
    ppg_filtered = np.asarray(ppg_filtered, dtype=float)

    ecg_mask = np.isfinite(ecg_filtered)
    if np.count_nonzero(ecg_mask) >= 5:
        ecg_peak_times = detect_peaks(
            time_ms[ecg_mask],
            ecg_filtered[ecg_mask],
            min_distance_s=0.28,
            threshold_scale=2.8,
            use_abs=True,
        )
    else:
        ecg_peak_times = np.array([], dtype=float)
    metrics.ecg_peak_count = int(len(ecg_peak_times))

    ppg_mask = np.isfinite(ppg_filtered)
    if np.count_nonzero(ppg_mask) >= 5:
        ppg_peak_times = choose_ppg_peak_times(
            time_ms[ppg_mask],
            ppg_filtered[ppg_mask],
            expected_count=len(ecg_peak_times) if len(ecg_peak_times) else None,
        )
    else:
        ppg_peak_times = np.array([], dtype=float)
    metrics.ppg_peak_count = int(len(ppg_peak_times))

    rr_ms = valid_rr_intervals_ms(ecg_peak_times)
    if len(rr_ms):
        metrics.instant_bpm = 60000.0 / float(rr_ms[-1])
        metrics.pulse_source = "ECG"
    else:
        ppg_rr_ms = valid_rr_intervals_ms(ppg_peak_times)
        if len(ppg_rr_ms):
            metrics.instant_bpm = 60000.0 / float(ppg_rr_ms[-1])
            metrics.pulse_source = "PPG"

    if len(rr_ms) >= 2:
        metrics.sdnn_ms = float(np.std(rr_ms, ddof=1))
        metrics.rmssd_ms = float(np.sqrt(np.mean(np.square(np.diff(rr_ms)))))

    if len(ecg_peak_times) and len(ppg_peak_times):
        ptt_values: list[float] = []
        for ecg_time in ecg_peak_times:
            start = np.searchsorted(ppg_peak_times, ecg_time + PTT_MIN_MS)
            if start >= len(ppg_peak_times):
                continue
            ptt_ms = ppg_peak_times[start] - ecg_time
            if PTT_MIN_MS <= ptt_ms <= PTT_MAX_MS:
                ptt_values.append(float(ptt_ms))
        if ptt_values:
            metrics.ptt_ms = float(np.median(ptt_values))
            metrics.ptt_pair_count = len(ptt_values)

    ppg_raw_mask = np.array([
        np.isfinite(row.ppg_red_raw) and np.isfinite(row.ppg_ir_raw)
        for row in rows
    ], dtype=bool)
    if np.count_nonzero(ppg_raw_mask) >= 5:
        ppg_time_ms = time_ms[ppg_raw_mask]
        red_raw = np.array([row.ppg_red_raw for row, keep in zip(rows, ppg_raw_mask) if keep], dtype=float)
        ir_raw = np.array([row.ppg_ir_raw for row, keep in zip(rows, ppg_raw_mask) if keep], dtype=float)

        red_dc = float(np.nanmean(red_raw))
        ir_dc = float(np.nanmean(ir_raw))
        red_ac_rms = rms(ppg_bandpass(red_raw, ppg_time_ms))
        ir_ac_rms = rms(ppg_bandpass(ir_raw, ppg_time_ms))

        if red_dc > 0 and ir_dc > 0 and np.isfinite(red_ac_rms) and np.isfinite(ir_ac_rms) and ir_ac_rms > 0:
            ratio = (red_ac_rms / red_dc) / (ir_ac_rms / ir_dc)
            metrics.spo2_percent = float(np.clip(110.0 - 25.0 * ratio, 70.0, 100.0))
        if ir_dc > 0 and np.isfinite(ir_ac_rms):
            metrics.perfusion_index_percent = 100.0 * ir_ac_rms / ir_dc

    return metrics


def format_metric(value: float, unit: str = "", decimals: int = 1) -> str:
    if not np.isfinite(value):
        return "--"
    return f"{value:.{decimals}f}{unit}"


class SyncUARTMonitor:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("ECG + PPG BOTH Sync Monitor")
        self.root.geometry("1360x840")
        self.root.minsize(1120, 720)
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
        self.metric_defs = [
            ("instant_bpm", "BPM (nhip tim)", "bpm", 1),
            ("sdnn_ms", "SDNN (do lech RR)", "ms", 1),
            ("rmssd_ms", "RMSSD (bien thien RR)", "ms", 1),
            ("ptt_ms", "PTT (ECG->PPG)", "ms", 0),
            ("spo2_percent", "SpO2 (oxy mau)", "%", 1),
            ("perfusion_index_percent", "PI (tuoi mau)", "%", 2),
        ]
        self.metric_vars = {key: tk.StringVar(value="--") for key, _, _, _ in self.metric_defs}
        self.metric_source_var = tk.StringVar(value="Nguon BPM: --")
        self.metric_count_var = tk.StringVar(value="ECG peaks: 0 | PPG peaks: 0 | PTT pairs: 0")

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
        self.style.configure("MetricName.TLabel", background=PANEL, foreground=MUTED, font=("Segoe UI", 9))
        self.style.configure("MetricValue.TLabel", background=PANEL, foreground=TEXT, font=("Segoe UI Semibold", 12))

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
            background=[("active", "#dbeafe"), ("pressed", "#bfdbfe"), ("disabled", "#e5e7eb")],
            foreground=[("disabled", "#94a3b8")],
        )
        self.style.configure("Accent.TButton", background=ACCENT_DARK, foreground="#ffffff", bordercolor=ACCENT_DARK)
        self.style.map("Accent.TButton", background=[("active", "#2563eb"), ("pressed", "#1e40af")])
        self.style.configure("Danger.TButton", background="#dc2626", foreground="#ffffff", bordercolor="#dc2626")
        self.style.map("Danger.TButton", background=[("active", "#b91c1c"), ("pressed", "#991b1b")])

        for widget in ("TEntry", "TCombobox"):
            self.style.configure(
                widget,
                fieldbackground="#ffffff",
                background="#ffffff",
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
                fieldbackground=[("readonly", "#ffffff"), ("disabled", "#f1f5f9")],
                foreground=[("readonly", TEXT), ("disabled", "#94a3b8")],
                bordercolor=[("focus", ACCENT), ("active", ACCENT)],
            )

        self.root.option_add("*TCombobox*Listbox.background", "#ffffff")
        self.root.option_add("*TCombobox*Listbox.foreground", TEXT)
        self.root.option_add("*TCombobox*Listbox.selectBackground", "#dbeafe")
        self.root.option_add("*TCombobox*Listbox.selectForeground", TEXT)

        self.style.configure(
            "TProgressbar",
            troughcolor="#e5e7eb",
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
        ttk.Label(title_group, text="ECG + PPG BOTH Sync Monitor", style="Title.TLabel").pack(anchor="w")
        ttk.Label(title_group, text="UART logger, synchronized 400 Hz capture, four-panel bandpass preview", style="Muted.TLabel").pack(anchor="w", pady=(2, 0))

        body = ttk.PanedWindow(shell, orient="horizontal")
        body.pack(fill="both", expand=True, pady=(8, 0))

        log_frame = ttk.Frame(body, style="Panel.TFrame", padding=10, width=340)
        body.add(log_frame, weight=2)

        controls_frame = ttk.Frame(log_frame, style="Panel.TFrame")
        controls_frame.pack(fill="x", pady=(0, 12))
        ttk.Label(controls_frame, text="Capture controls", style="Section.TLabel").pack(anchor="w", pady=(0, 8))

        ttk.Label(controls_frame, text="COM PORT", style="Field.TLabel").pack(anchor="w")
        port_row = ttk.Frame(controls_frame, style="Panel.TFrame")
        port_row.pack(fill="x", pady=(4, 8))
        self.port_combo = ttk.Combobox(port_row, textvariable=self.port_var, width=18, state="readonly")
        self.port_combo.pack(side="left", fill="x", expand=True, padx=(0, 8))
        ttk.Button(port_row, text="Refresh", command=self.refresh_ports).pack(side="left")

        ttk.Label(controls_frame, text="NGUOI DO", style="Field.TLabel").pack(anchor="w")
        ttk.Entry(controls_frame, textvariable=self.person_var).pack(fill="x", pady=(4, 8))

        mode_duration = ttk.Frame(controls_frame, style="Panel.TFrame")
        mode_duration.pack(fill="x", pady=(0, 8))
        mode_duration.columnconfigure(1, weight=1)
        ttk.Label(mode_duration, text="MODE", style="Field.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(mode_duration, text="THOI GIAN (S)", style="Field.TLabel").grid(row=0, column=1, sticky="w", padx=(16, 0))
        ttk.Label(mode_duration, text="BOTH", style="Section.TLabel").grid(row=1, column=0, sticky="w", pady=(4, 0))
        ttk.Entry(mode_duration, textvariable=self.duration_var, width=10).grid(row=1, column=1, sticky="ew", padx=(16, 0), pady=(4, 0))

        actions = ttk.Frame(controls_frame, style="Panel.TFrame")
        actions.pack(fill="x", pady=(2, 8))
        ttk.Button(actions, text="Start", style="Accent.TButton", command=self.start_measurement).pack(fill="x", pady=(0, 6))
        ttk.Button(actions, text="Stop", style="Danger.TButton", command=self.stop_measurement).pack(fill="x", pady=(0, 6))
        ttk.Button(actions, text="Open CSV", command=self.open_csv_file).pack(fill="x")

        ttk.Label(controls_frame, text="TIEN TRINH", style="Field.TLabel").pack(anchor="w")
        self.progress = ttk.Progressbar(controls_frame, mode="determinate", length=220)
        self.progress.pack(fill="x", pady=(4, 8))
        ttk.Label(controls_frame, textvariable=self.status_var, style="Status.TLabel").pack(fill="x")

        metrics_frame = ttk.Frame(log_frame, style="Panel.TFrame")
        metrics_frame.pack(fill="x", pady=(0, 12))
        ttk.Label(metrics_frame, text="Derived metrics", style="Section.TLabel").pack(anchor="w", pady=(0, 8))

        metrics_grid = ttk.Frame(metrics_frame, style="Panel.TFrame")
        metrics_grid.pack(fill="x")
        metrics_grid.columnconfigure(1, weight=1)
        for row, (key, label, _, _) in enumerate(self.metric_defs):
            ttk.Label(metrics_grid, text=label, style="MetricName.TLabel").grid(row=row, column=0, sticky="w", pady=2)
            ttk.Label(metrics_grid, textvariable=self.metric_vars[key], style="MetricValue.TLabel").grid(row=row, column=1, sticky="e", pady=2)
        ttk.Label(metrics_frame, textvariable=self.metric_source_var, style="Muted.TLabel").pack(anchor="w", pady=(8, 0))
        ttk.Label(metrics_frame, textvariable=self.metric_count_var, style="Muted.TLabel").pack(anchor="w", pady=(2, 0))

        ttk.Label(log_frame, text="UART log", style="Section.TLabel").pack(anchor="w", pady=(0, 8))
        self.log_text = tk.Text(
            log_frame,
            height=10,
            wrap="none",
            bg="#ffffff",
            fg=TEXT,
            insertbackground=TEXT,
            selectbackground="#dbeafe",
            selectforeground=TEXT,
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

        plot_frame = ttk.Frame(body, style="Panel.TFrame", padding=2)
        body.add(plot_frame, weight=7)

        self.figure = Figure(figsize=(9.2, 7.0), dpi=100, facecolor=PLOT_BG)
        self.ax_ecg_raw = self.figure.add_subplot(411)
        self.ax_ecg_filtered = self.figure.add_subplot(412, sharex=self.ax_ecg_raw)
        self.ax_ppg_raw = self.figure.add_subplot(413, sharex=self.ax_ecg_raw)
        self.ax_ppg_filtered = self.figure.add_subplot(414, sharex=self.ax_ecg_raw)
        self.style_axes()
        self.figure.subplots_adjust(left=0.095, right=0.995, top=0.985, bottom=0.055, hspace=0.42)
        self.canvas = FigureCanvasTkAgg(self.figure, master=plot_frame)
        canvas_widget = self.canvas.get_tk_widget()
        canvas_widget.configure(bg=PLOT_BG, highlightthickness=0)
        canvas_widget.pack(fill="both", expand=True)

    def style_axes(self):
        for ax in (self.ax_ecg_raw, self.ax_ecg_filtered, self.ax_ppg_raw, self.ax_ppg_filtered):
            ax.set_facecolor(PLOT_BG)
            ax.tick_params(colors=MUTED, labelsize=9, pad=4)
            ax.xaxis.label.set_color(TEXT)
            ax.yaxis.label.set_color(TEXT)
            ax.title.set_color(TEXT)
            ax.yaxis.labelpad = 10
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

    def reset_metrics_panel(self):
        for key in self.metric_vars:
            self.metric_vars[key].set("--")
        self.metric_source_var.set("Nguon BPM: --")
        self.metric_count_var.set("ECG peaks: 0 | PPG peaks: 0 | PTT pairs: 0")

    def update_metrics_panel(self, metrics: DerivedMetrics):
        values = {
            "instant_bpm": metrics.instant_bpm,
            "sdnn_ms": metrics.sdnn_ms,
            "rmssd_ms": metrics.rmssd_ms,
            "ptt_ms": metrics.ptt_ms,
            "spo2_percent": metrics.spo2_percent,
            "perfusion_index_percent": metrics.perfusion_index_percent,
        }
        for key, _, unit, decimals in self.metric_defs:
            spacer = " " if unit in ("bpm", "ms") else ""
            self.metric_vars[key].set(format_metric(values[key], f"{spacer}{unit}", decimals))
        self.metric_source_var.set(f"Nguon BPM: {metrics.pulse_source}")
        self.metric_count_var.set(
            f"ECG peaks: {metrics.ecg_peak_count} | PPG peaks: {metrics.ppg_peak_count} | PTT pairs: {metrics.ptt_pair_count}"
        )

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
        self.reset_metrics_panel()
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
                raise ValueError("Khong tim thay dong time_us/time_ms,ecg_raw,ppg_red_raw,ppg_ir_raw hop le.")
            self.plot_rows(rows, path.name)
            self.set_status(f"Da mo file: {path}")
            self.log(f"[OPEN] {path}")
        except Exception as exc:
            messagebox.showerror("Open CSV Error", str(exc))
            self.set_status(f"ERROR: {exc}")

    def measure_worker(self, duration_s: int):
        mode = "BOTH"
        person = self.person_var.get().strip() or "unknown"
        port = self.port_var.get()

        try:
            self.set_status(f"Mo {port}...")
            with serial.Serial(port, BAUD_RATE, timeout=1.0) as ser:
                self.serial_obj = ser
                time.sleep(0.3)
                ser.reset_input_buffer()

                board_mode = "BOTH"
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
        time_unit = "us"
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
            if upper.startswith("TIME_US"):
                time_unit = "us"
                continue
            if upper.startswith("TIME_MS"):
                time_unit = "ms"
                continue

            row = parse_sync_csv_line(line, time_unit)
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
            writer.writerow(["person_name", "time_us", "time_ms", "ecg_raw", "ppg_red_raw", "ppg_ir_raw"])
            for row in rows:
                writer.writerow([
                    person,
                    row.time_us,
                    f"{row.time_us / 1000.0:.3f}",
                    "" if np.isnan(row.ecg_raw) else f"{row.ecg_raw:.0f}",
                    "" if np.isnan(row.ppg_red_raw) else f"{row.ppg_red_raw:.0f}",
                    "" if np.isnan(row.ppg_ir_raw) else f"{row.ppg_ir_raw:.0f}",
                ])
        return path

    def save_filtered_csv(self, rows: list[SyncRow], person: str, mode: str) -> Path:
        rows = normalize_sync_rows(rows)
        path = FILTERED_DIR / f"{self.make_file_base(person, mode)}_bandpass.csv"
        ecg_filtered, ppg_filtered = self.compute_filtered(rows)

        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "person_name", "time_us", "time_ms",
                "ecg_raw", f"ecg_bandpass_{ECG_HIGHPASS_HZ:g}_{ECG_LOWPASS_HZ:g}Hz",
                "ppg_ir_raw", f"ppg_ir_bandpass_{PPG_HIGHPASS_HZ:g}_{PPG_LOWPASS_HZ:g}Hz",
                "ppg_red_raw",
            ])
            for i, row in enumerate(rows):
                writer.writerow([
                    person,
                    row.time_us,
                    f"{row.time_us / 1000.0:.3f}",
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
            ecg_time_ms = np.array([rows[i].time_us / 1000.0 for i in ecg_idx], dtype=float)
            ecg_filtered[ecg_idx] = ecg_bandpass(ecg_values, ecg_time_ms)

        ppg_idx = np.array([i for i, row in enumerate(rows) if not np.isnan(row.ppg_ir_raw)], dtype=int)
        if len(ppg_idx):
            ppg_values = np.array([rows[i].ppg_ir_raw for i in ppg_idx], dtype=float)
            ppg_time_ms = np.array([rows[i].time_us / 1000.0 for i in ppg_idx], dtype=float)
            ppg_filtered[ppg_idx] = ppg_bandpass(ppg_values, ppg_time_ms)

        return ecg_filtered, ppg_filtered

    def plot_rows(self, rows: list[SyncRow], title: str):
        rows = normalize_sync_rows(rows)
        ecg_filtered, ppg_filtered = self.compute_filtered(rows)
        metrics = compute_derived_metrics(rows, ecg_filtered, ppg_filtered)
        t = np.array([row.time_us / 1000000.0 for row in rows], dtype=float)
        ecg = np.array([row.ecg_raw for row in rows], dtype=float)
        ppg = np.array([row.ppg_ir_raw for row in rows], dtype=float)
        ecg_mask = np.isfinite(ecg)
        ppg_mask = np.isfinite(ppg)

        for ax in (self.ax_ecg_raw, self.ax_ecg_filtered, self.ax_ppg_raw, self.ax_ppg_filtered):
            ax.clear()
        self.style_axes()

        if ecg_mask.any():
            self.ax_ecg_raw.plot(t[ecg_mask], ecg[ecg_mask], color="#000000", linewidth=0.9, label="ECG raw")
            self.ax_ecg_filtered.plot(t[ecg_mask], ecg_filtered[ecg_mask], color="#dc2626", linewidth=1.15, label="ECG bandpass")
        if ppg_mask.any():
            self.ax_ppg_raw.plot(t[ppg_mask], ppg[ppg_mask], color="#000000", linewidth=0.9, label="PPG IR raw")
            self.ax_ppg_filtered.plot(t[ppg_mask], ppg_filtered[ppg_mask], color="#dc2626", linewidth=1.15, label="PPG IR bandpass")

        self.ax_ecg_raw.set_title("ECG raw", loc="center", color=TEXT, fontsize=11, fontweight="semibold", pad=6)
        self.ax_ecg_raw.set_ylabel("ADC count")
        self.ax_ecg_filtered.set_title("ECG bandpass", loc="center", color=TEXT, fontsize=11, fontweight="semibold", pad=6)
        self.ax_ecg_filtered.set_ylabel("Count")
        self.ax_ppg_raw.set_title("PPG IR raw", loc="center", color=TEXT, fontsize=11, fontweight="semibold", pad=6)
        self.ax_ppg_raw.set_ylabel("Optical count")
        self.ax_ppg_filtered.set_title("PPG IR bandpass", loc="center", color=TEXT, fontsize=11, fontweight="semibold", pad=6)
        self.ax_ppg_filtered.set_xlabel("Time (s)")
        self.ax_ppg_filtered.set_ylabel("Count")

        for ax in (self.ax_ecg_raw, self.ax_ecg_filtered, self.ax_ppg_raw, self.ax_ppg_filtered):
            handles, labels = ax.get_legend_handles_labels()
            if handles:
                ax.legend(handles, labels, loc="upper right", facecolor=PANEL, edgecolor=BORDER, labelcolor=TEXT)

        self.figure.subplots_adjust(left=0.095, right=0.995, top=0.985, bottom=0.055, hspace=0.42)
        self.canvas.draw_idle()
        self.update_metrics_panel(metrics)


def main():
    root = tk.Tk()
    SyncUARTMonitor(root)
    root.mainloop()


if __name__ == "__main__":
    main()
