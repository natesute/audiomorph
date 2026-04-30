"""
Per-frame audio feature extraction for music-reactive Blender visualization.

Outputs a JSON file with one entry per video frame containing normalised
features that drive scene parameters. Designed to run in a Python 3.11
venv with numpy + librosa + soundfile installed.

Usage:
    python analyze.py <input.wav> <output.json> [--fps 30]
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import librosa
import numpy as np
import soundfile as sf


# Frequency bands (Hz). Eight bands from sub to air, log-spaced where it
# matters perceptually. Names map to scene channels.
BANDS: list[tuple[str, float, float]] = [
    ("sub",     20.0,    60.0),
    ("bass",    60.0,   180.0),
    ("low",    180.0,   500.0),
    ("low_mid", 500.0,  1200.0),
    ("mid",   1200.0,  2800.0),
    ("high_mid", 2800.0, 5500.0),
    ("high",  5500.0, 10000.0),
    ("air",  10000.0, 18000.0),
]


def _smooth_attack_release(x: np.ndarray, attack: float, release: float) -> np.ndarray:
    """Envelope follower: fast attack, slower release.

    Both coefficients in [0, 1]; bigger = faster response.
    """
    out = np.zeros_like(x, dtype=np.float64)
    state = 0.0
    for i, v in enumerate(x):
        coeff = attack if v > state else release
        state += (v - state) * coeff
        out[i] = state
    return out


def _percentile_normalise(x: np.ndarray, lo: float = 5.0, hi: float = 99.0) -> np.ndarray:
    """Map x to [0, 1] using percentile clipping for robustness against outliers."""
    a = np.percentile(x, lo)
    b = np.percentile(x, hi)
    if b - a < 1e-9:
        return np.zeros_like(x)
    return np.clip((x - a) / (b - a), 0.0, 1.0)


def analyse(audio_path: Path, fps: int = 30) -> dict:
    print(f"[analyse] loading {audio_path.name}")
    # Load mono at native rate. WAV masters here are 48k/24-bit; librosa
    # converts to float32 mono automatically.
    y, sr = librosa.load(str(audio_path), sr=None, mono=True)
    duration = len(y) / sr
    n_frames = int(math.ceil(duration * fps))
    print(f"[analyse] sr={sr} duration={duration:.2f}s frames={n_frames} @ {fps}fps")

    # STFT params chosen so each STFT frame is roughly 1 video frame.
    hop_length = max(1, sr // fps)
    n_fft = 2048
    while n_fft < hop_length * 2:
        n_fft *= 2

    # Magnitude spectrogram for band energies.
    S = np.abs(librosa.stft(y, n_fft=n_fft, hop_length=hop_length, win_length=n_fft))
    freqs = librosa.fft_frequencies(sr=sr, n_fft=n_fft)
    n_stft = S.shape[1]

    # Power-weighted band energies, dB-scaled.
    band_energy: dict[str, np.ndarray] = {}
    for name, lo, hi in BANDS:
        mask = (freqs >= lo) & (freqs < hi)
        if not mask.any():
            band_energy[name] = np.zeros(n_stft)
            continue
        e = (S[mask] ** 2).sum(axis=0)
        e = librosa.power_to_db(e + 1e-10, ref=np.max)
        band_energy[name] = e

    # RMS loudness (in dB).
    rms = librosa.feature.rms(y=y, frame_length=n_fft, hop_length=hop_length)[0]
    rms_db = librosa.amplitude_to_db(rms + 1e-9, ref=np.max)

    # Onset envelope - smoothed peak picker for transients.
    onset_env = librosa.onset.onset_strength(
        y=y, sr=sr, hop_length=hop_length, aggregate=np.median
    )

    # Beat positions (frame indices in STFT-frame space).
    tempo, beat_frames = librosa.beat.beat_track(
        onset_envelope=onset_env, sr=sr, hop_length=hop_length
    )
    tempo_val = float(tempo[0]) if hasattr(tempo, "__len__") else float(tempo)
    print(f"[analyse] tempo {tempo_val:.1f} bpm, {len(beat_frames)} beats")

    # Spectral centroid - "brightness" of sound, drives camera/colour.
    centroid = librosa.feature.spectral_centroid(
        y=y, sr=sr, n_fft=n_fft, hop_length=hop_length
    )[0]

    # Spectral flatness - "noisiness" 0..1, drives glitch/grain intensity.
    flatness = librosa.feature.spectral_flatness(
        y=y, n_fft=n_fft, hop_length=hop_length
    )[0]

    # Chroma - 12 pitch classes. Drives colour rotation.
    chroma = librosa.feature.chroma_stft(
        S=S, sr=sr, n_fft=n_fft, hop_length=hop_length
    )

    # Resample everything to per-video-frame.
    def to_frames(arr: np.ndarray) -> np.ndarray:
        if arr.shape[-1] == n_frames:
            return arr
        old = arr.shape[-1]
        idx = np.linspace(0, old - 1, n_frames)
        if arr.ndim == 1:
            return np.interp(idx, np.arange(old), arr)
        # 2D: resample each row.
        out = np.zeros((arr.shape[0], n_frames))
        for i in range(arr.shape[0]):
            out[i] = np.interp(idx, np.arange(old), arr[i])
        return out

    rms_f = to_frames(rms_db)
    onset_f = to_frames(onset_env)
    centroid_f = to_frames(centroid)
    flatness_f = to_frames(flatness)
    chroma_f = to_frames(chroma)
    bands_f = {name: to_frames(arr) for name, arr in band_energy.items()}

    # Normalise each band with envelope-followed smoothing.
    bands_norm = {}
    for name, arr in bands_f.items():
        n = _percentile_normalise(arr, lo=5.0, hi=99.0)
        # Faster attack on highs to feel snappier.
        attack = 0.85 if "high" in name or name == "air" else 0.55
        release = 0.12 if "high" in name or name == "air" else 0.08
        bands_norm[name] = _smooth_attack_release(n, attack, release).tolist()

    rms_norm = _percentile_normalise(rms_f, lo=5.0, hi=99.0)
    rms_norm = _smooth_attack_release(rms_norm, 0.6, 0.08)

    onset_norm = _percentile_normalise(onset_f, lo=20.0, hi=99.5)
    # Hard attack, fast release - feels like a flash trigger.
    onset_norm = _smooth_attack_release(onset_norm, 0.95, 0.25)

    centroid_norm = _percentile_normalise(centroid_f, lo=5.0, hi=99.0)
    flatness_norm = np.clip(flatness_f, 0.0, 1.0)

    # Beat track in video-frame indices.
    beat_times = librosa.frames_to_time(beat_frames, sr=sr, hop_length=hop_length)
    beat_video_frames = (beat_times * fps).astype(int).tolist()

    # Per-frame "beat phase" 0..1 between consecutive beats (useful for
    # smooth interpolation rather than spike-only triggers).
    beat_phase = np.zeros(n_frames)
    if len(beat_video_frames) >= 2:
        for i in range(len(beat_video_frames) - 1):
            a = beat_video_frames[i]
            b = beat_video_frames[i + 1]
            if 0 <= a < n_frames and a < b:
                length = max(1, b - a)
                end = min(b, n_frames)
                phase = (np.arange(end - a)) / length
                beat_phase[a:end] = phase

    # Dominant chroma class per frame (0=C, 11=B). Hue rotates with this.
    chroma_argmax = chroma_f.argmax(axis=0).tolist()
    chroma_strength = chroma_f.max(axis=0).tolist()

    # Pre-built section detection via cumulative band-energy variance.
    # Identify "drop" candidates: high bass + sub jumps.
    sub = np.array(bands_norm["sub"])
    bass = np.array(bands_norm["bass"])
    bass_combined = (sub + bass) * 0.5
    bass_d = np.diff(bass_combined, prepend=bass_combined[0])
    drop_score = _smooth_attack_release(np.maximum(bass_d, 0.0), 0.9, 0.05)
    drop_score = _percentile_normalise(drop_score, lo=50.0, hi=99.5)

    return {
        "meta": {
            "source": str(audio_path.name),
            "sample_rate": int(sr),
            "duration": float(duration),
            "fps": int(fps),
            "n_frames": int(n_frames),
            "tempo": tempo_val,
            "n_beats": len(beat_video_frames),
        },
        "frames": {
            "rms": rms_norm.tolist(),
            "onset": onset_norm.tolist(),
            "centroid": centroid_norm.tolist(),
            "flatness": flatness_norm.tolist(),
            "drop": drop_score.tolist(),
            "beat_phase": beat_phase.tolist(),
            "chroma_class": chroma_argmax,
            "chroma_strength": chroma_strength,
            "bands": bands_norm,
        },
        "events": {
            "beats": beat_video_frames,
        },
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("input", type=Path, help="Path to WAV/MP3 file")
    p.add_argument("output", type=Path, help="Path to write JSON features")
    p.add_argument("--fps", type=int, default=30)
    args = p.parse_args()

    data = analyse(args.input, fps=args.fps)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data))
    print(f"[analyse] wrote {args.output}  ({args.output.stat().st_size / 1024:.1f} KB)")


if __name__ == "__main__":
    main()
