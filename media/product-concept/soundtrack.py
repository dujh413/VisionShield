"""Original, deterministic 30-second product-film score; no sampled audio.

Edit CHORDS, ARPEGGIO, or TRANSITIONS below, then run this file again.
Only numpy and Python's standard library are required.
"""

from __future__ import annotations

import argparse
import math
import wave
from pathlib import Path

import numpy as np


DURATION = 30.0
SAMPLE_RATE = 48_000
SEED = 413

# Start / duration / harmony / bass. Notes use scientific pitch notation.
CHORDS = [
    (0.0, 8.5, ["D3", "A3", "F#4", "C#5", "E5"], "D2"),
    (7.5, 8.5, ["B2", "F#3", "A3", "D4", "F#4"], "B1"),
    (15.0, 8.5, ["G2", "D3", "F#3", "A3", "B4"], "G1"),
    (22.5, 7.5, ["D3", "A3", "F#4", "C#5", "E5"], "D2"),
]
ARPEGGIO = {
    "starts": [2.0, 8.0, 15.5, 23.0],
    "phrases": [
        ["F#5", "A5", "E5", "D5", "A5", "C#6", "E5", "F#5"],
        ["F#5", "D5", "A5", "B5", "F#5", "A5", "D6", "B5"],
        ["B5", "A5", "F#5", "D5", "A5", "B5", "F#5", "E5"],
        ["F#5", "A5", "E5", "D5", "A5", "F#5", "E5", "D5"],
    ],
    "step": 0.625,
    "gain": 0.085,
}
TRANSITIONS = [5.0, 10.0, 17.0, 24.0]


def hz(note: str) -> float:
    pitch = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
    sharp = 1 if "#" in note else 0
    midi = 12 * (int(note[-1]) + 1) + pitch[note[0]] + sharp
    return 440.0 * 2.0 ** ((midi - 69) / 12.0)


def envelope(t: np.ndarray, duration: float, attack: float, release: float) -> np.ndarray:
    rise = np.sin(np.clip(t / attack, 0, 1) * np.pi / 2) ** 2
    fall = np.sin(np.clip((duration - t) / release, 0, 1) * np.pi / 2) ** 2
    return rise * fall


def place(mix: np.ndarray, mono: np.ndarray, start: float, gain: float, pan: float) -> None:
    """Mix with constant-power stereo panning; crop tails at the film boundary."""
    first = round(start * SAMPLE_RATE)
    last = min(first + len(mono), len(mix))
    source_start = max(0, -first)
    first = max(first, 0)
    if last <= first:
        return
    angle = (pan + 1) * math.pi / 4
    signal = mono[source_start:source_start + last - first] * gain
    mix[first:last, 0] += signal * math.cos(angle)
    mix[first:last, 1] += signal * math.sin(angle)


def glass(note: str, duration: float = 2.6) -> np.ndarray:
    t = np.arange(round(duration * SAMPLE_RATE), dtype=np.float64) / SAMPLE_RATE
    frequency = hz(note)
    phase = 2 * np.pi * frequency * t
    signal = np.sin(phase) + 0.26 * np.sin(phase * 2.006) + 0.075 * np.sin(phase * 3.991)
    attack = np.sin(np.clip(t / 0.014, 0, 1) * np.pi / 2) ** 2
    return signal * attack * np.exp(-t / 0.75) * envelope(t, duration, 0.014, 0.3)


def build_score() -> np.ndarray:
    rng = np.random.default_rng(SEED)
    mix = np.zeros((round(DURATION * SAMPLE_RATE), 2), dtype=np.float64)

    for start, duration, notes, bass in CHORDS:
        t = np.arange(round(duration * SAMPLE_RATE), dtype=np.float64) / SAMPLE_RATE
        env = envelope(t, duration, 1.8, 2.3)
        for index, note in enumerate(notes):
            frequency = hz(note)
            detune = 2.0 ** (2.5 / 1200)
            pad = (
                np.sin(2 * np.pi * frequency * t)
                + 0.42 * np.sin(2 * np.pi * frequency * detune * t + 0.2)
                + 0.15 * np.sin(2 * np.pi * frequency * 2 * t)
            )
            breath = 0.91 + 0.09 * np.sin(2 * np.pi * 0.21 * t + index)
            place(mix, pad * env * breath, start, 0.028, (index - 2) * 0.28)
        low = np.sin(2 * np.pi * hz(bass) * t) + 0.12 * np.sin(4 * np.pi * hz(bass) * t)
        place(mix, low * env * (0.78 + 0.22 * np.cos(2 * np.pi * t / 2.5)), start, 0.10, 0)

    for start, phrase in zip(ARPEGGIO["starts"], ARPEGGIO["phrases"]):
        for index, note in enumerate(phrase):
            at = start + index * ARPEGGIO["step"]
            pan = -0.35 if index % 2 == 0 else 0.35
            struck = glass(note)
            gain = ARPEGGIO["gain"] * (0.78 if index % 2 else 1.0)
            place(mix, struck, at, gain, pan)
            place(mix, struck, at + 0.27, gain * 0.18, -pan)
            place(mix, struck, at + 0.54, gain * 0.08, pan)

    for index, at in enumerate(TRANSITIONS):
        duration = 1.0
        length = round(duration * SAMPLE_RATE)
        t = np.arange(length, dtype=np.float64) / SAMPLE_RATE
        noise = rng.standard_normal(length)
        frequencies = np.fft.rfftfreq(length, 1 / SAMPLE_RATE)
        band = np.exp(-0.5 * (np.log(np.maximum(frequencies, 1) / 2400) / 0.68) ** 2)
        air = np.fft.irfft(np.fft.rfft(noise) * band, n=length)
        air /= max(float(np.sqrt(np.mean(air * air))), 1e-9)
        swell = np.exp(-0.5 * ((t - 0.64) / 0.18) ** 2) * envelope(t, duration, 0.25, 0.22)
        place(mix, air * swell, at - 0.64, 0.023, (-1 if index % 2 else 1) * 0.45)

    # A final high D quietly resolves the film; the global fade removes all tails.
    place(mix, glass("D6", 3.1), 26.9, 0.045, 0)
    time = np.arange(len(mix), dtype=np.float64) / SAMPLE_RATE
    mix *= envelope(time, DURATION, 1.35, 2.1)[:, None]
    mix = np.tanh(mix * 1.15)
    mix *= 0.76 / max(float(np.max(np.abs(mix))), 1e-9)
    return mix.astype(np.float32)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(__file__).parent / "output" / "score.wav")
    args = parser.parse_args()
    score = build_score()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    pcm = np.rint(score * 32767).astype("<i2")
    with wave.open(str(args.output), "wb") as stream:
        stream.setnchannels(2)
        stream.setsampwidth(2)
        stream.setframerate(SAMPLE_RATE)
        stream.writeframes(pcm.tobytes())
    peak = float(np.max(np.abs(score)))
    rms = float(np.sqrt(np.mean(score * score)))
    print(f"Saved {args.output}: {DURATION:.1f}s / {SAMPLE_RATE} Hz / stereo / peak={peak:.4f} / RMS={rms:.4f} ({20 * math.log10(rms):.1f} dBFS)")


if __name__ == "__main__":
    main()
