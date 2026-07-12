"""Synthesize an original, royalty-free ambient-tech bed for the Hyper Brain film.

No samples, no external audio: everything here is generated with numpy so the track is
ours to ship in a public repo. The scene cuts are passed in so the music breathes with the
edit (a soft riser leans into each cut, a low impact lands on it). Output is a dry WAV;
ffmpeg then adds space (reverb), fades, and encodes to mp3 in the sibling shell step.

Run with the repo venv:  ./.venv/Scripts/python.exe video/audio/make_soundtrack.py <out.wav>
"""

from __future__ import annotations

import struct
import sys
import wave

import numpy as np

SR = 44100
BPM = 68
BAR = 60.0 / BPM * 4  # 4/4 bar in seconds

# Must match TIMELINE in src/HyperBrainPromo.tsx (frames @ 30fps).
FRAMES = [135, 110, 140, 150, 165, 140, 260, 170, 165, 140, 140]
DUR = sum(FRAMES) / 30.0
# Cut times = end of each scene except the last (a riser leads into the next scene).
CUTS = np.cumsum(FRAMES[:-1]) / 30.0

N = int(SR * DUR)
t = np.arange(N) / SR
out = np.zeros((N, 2), dtype=np.float64)


def add(sig: np.ndarray, start: float, pan: float = 0.0, gain: float = 1.0) -> None:
    """Mix a mono signal into the stereo bus at a start time, with equal-power pan."""
    i0 = int(start * SR)
    i1 = min(N, i0 + len(sig))
    if i0 >= N or i1 <= 0:
        return
    s = sig[: i1 - i0] * gain
    lg = np.cos((pan + 1) * np.pi / 4)
    rg = np.sin((pan + 1) * np.pi / 4)
    out[i0:i1, 0] += s * lg
    out[i0:i1, 1] += s * rg


def hann(n: int) -> np.ndarray:
    return 0.5 - 0.5 * np.cos(2 * np.pi * np.arange(n) / max(1, n - 1))


# Note frequencies (Hz).
A3, C4, E4, F4, G4 = 220.00, 261.63, 329.63, 349.23, 392.00
A4, B3, C5, D4, G3 = 440.00, 246.94, 523.25, 293.66, 196.00
F3 = 174.61
# Warm A-minor progression: Am - F - C - G, voiced mid-register.
PROG = [
    ([A3, C4, E4, A4], 55.00),   # Am
    ([F3, A3, C4, F4], 43.65),   # F
    ([C4, E4, G4, C5], 65.41),   # C
    ([G3, B3, D4, G4], 49.00),   # G
]


def pad_voice(freq: float, dur: float) -> np.ndarray:
    """A warm, slightly detuned additive pad note (a few harmonics, chorused)."""
    n = int(dur * SR)
    tt = np.arange(n) / SR
    voice = np.zeros(n)
    for detune in (-0.0016, 0.0, 0.0016):
        f = freq * (1 + detune)
        for h, amp in ((1, 1.0), (2, 0.35), (3, 0.14)):
            voice += amp * np.sin(2 * np.pi * f * h * tt)
    return voice / 6.0


# ---- Pads: one chord per bar, crossfaded via overlapping Hann windows.
overlap = 0.6
num_bars = int(np.ceil(DUR / BAR)) + 1
for i in range(num_bars):
    freqs, _ = PROG[i % len(PROG)]
    seg = BAR + overlap
    n = int(seg * SR)
    w = hann(n)
    chord = np.zeros(n)
    for f in freqs:
        chord += pad_voice(f, seg)
    chord *= w / len(freqs)
    # Slow swell: sparse at the open, fuller through the middle, easing at the end.
    center = (i * BAR + seg / 2) / DUR
    energy = 0.45 + 0.55 * np.sin(np.clip(center, 0, 1) * np.pi)
    add(chord, i * BAR, pan=-0.12 if i % 2 else 0.12, gain=0.34 * energy)

# ---- Sub bass: chord root, one soft sine per bar.
for i in range(num_bars):
    _, root = PROG[i % len(PROG)]
    seg = BAR + overlap
    n = int(seg * SR)
    tt = np.arange(n) / SR
    sub = (np.sin(2 * np.pi * root * tt) + 0.4 * np.sin(2 * np.pi * root * 2 * tt))
    sub *= hann(n)
    add(sub, i * BAR, gain=0.22)

# ---- Pulse: a soft half-note heartbeat through the body of the film.
kick_int = 2 * 60.0 / BPM
kick_start, kick_end = 8.2, DUR - 5.0
kt = kick_start
k = 0
kicks = int((kick_end - kick_start) / kick_int) + 1
while kt < kick_end:
    n = int(0.30 * SR)
    tt = np.arange(n) / SR
    pitch = 48 + 62 * np.exp(-tt * 26)          # quick downward chirp
    body = np.sin(2 * np.pi * np.cumsum(pitch) / SR)
    body *= np.exp(-tt * 9)
    # Fade the pulse in over the first bars and out toward the end.
    g = min(1.0, (kt - kick_start) / 3.5) * min(1.0, (kick_end - kt) / 4.0)
    add(body, kt, gain=0.5 * max(0.0, g))
    kt += kick_int
    k += 1

# ---- Bells: sparse pentatonic shimmer for lift (reverb tail added by ffmpeg).
PENTA = [880.00, 1046.50, 1174.66, 1318.51, 1567.98]
bell_times = [12.9, 17.9, 23.4, 28.1, 33.0, 38.7, 44.0, 49.2]
for j, bt in enumerate(bell_times):
    f = PENTA[j % len(PENTA)]
    n = int(1.6 * SR)
    tt = np.arange(n) / SR
    bell = (np.sin(2 * np.pi * f * tt) + 0.5 * np.sin(2 * np.pi * f * 2.01 * tt))
    bell *= np.exp(-tt * 3.2)
    add(bell, bt, pan=(-0.5 if j % 2 else 0.5), gain=0.13)

# ---- Scene transitions: a noise riser leaning into each cut + a low impact on it.
rng = np.random.default_rng(7)
for tc in CUTS:
    # Riser (0.7s of rising, high-passed noise, panning across).
    rn = int(0.7 * SR)
    env = (np.arange(rn) / rn) ** 2
    noise = rng.standard_normal(rn)
    noise = np.diff(noise, prepend=noise[0])  # crude high-pass -> "air"
    riser = noise * env * 0.10
    i0 = int((tc - 0.7) * SR)
    if i0 > 0:
        i1 = min(N, i0 + rn)
        s = riser[: i1 - i0]
        pan = np.linspace(-0.6, 0.6, len(s))
        out[i0:i1, 0] += s * np.cos((pan + 1) * np.pi / 4)
        out[i0:i1, 1] += s * np.sin((pan + 1) * np.pi / 4)
    # Impact (low sine thump on the cut).
    n = int(0.45 * SR)
    tt = np.arange(n) / SR
    imp = np.sin(2 * np.pi * 46 * tt) * np.exp(-tt * 7) * 0.22
    add(imp, float(tc))

# ---- Master: gentle soft-clip, normalize with headroom.
out = np.tanh(out * 1.1)
peak = np.max(np.abs(out)) or 1.0
out = out / peak * 0.89

# Write 16-bit stereo WAV.
path = sys.argv[1] if len(sys.argv) > 1 else "soundtrack.wav"
data = (out * 32767).astype(np.int16)
with wave.open(path, "w") as w:
    w.setnchannels(2)
    w.setsampwidth(2)
    w.setframerate(SR)
    w.writeframes(struct.pack("<" + "h" * data.size, *data.flatten()))

print(f"wrote {path}  dur={DUR:.2f}s  cuts={[round(float(c), 2) for c in CUTS]}")
