# Hyper Brain — product film

A ~54 second product film for Hyper Brain, built with [Remotion](https://remotion.dev).
Colours and type are taken straight from the app's dark theme so the film reads as one
identity with the product.

## Run

```bash
cd video
npm install
npm run studio     # live preview + scrubbing at http://localhost:3000
npm run render     # writes out/hyper-brain-promo.mp4 (1920x1080, 30fps, h264)
npm run still      # writes out/poster.png (a single frame, for a thumbnail)
```

## Structure

- `src/Root.tsx` — registers the `HyperBrainPromo` composition (1920x1080, 30fps).
- `src/HyperBrainPromo.tsx` — the scene running order, per-scene lengths, and the audio track.
- `src/scenes.tsx` — the eleven scenes: open, problem, one-brain-for-the-company, connected
  graph, cited answers, scoped access, **Studio draft-from-URL** (the centerpiece — a live
  OKF article building itself from a link), Open Knowledge Format, no-install / in-tenant
  GCP, agent team, outro.
- `src/ui.tsx` — the shared backdrop, scene fade wrapper, and small brand primitives.
- `src/theme.ts` / `src/fonts.ts` — palette and fonts, mirrored from `ui/styles.css`.

To change the length or order, edit `TIMELINE` in `HyperBrainPromo.tsx`; the composition
duration is derived from it automatically.

## Audio

The soundtrack is an original, royalty-free ambient-tech bed synthesised with numpy — no
licensed samples — so it is safe to ship in a public repo. It is regenerated in two steps:

```bash
./.venv/Scripts/python.exe video/audio/make_soundtrack.py video/scratch.wav   # synth (dry)
ffmpeg -y -i video/scratch.wav -af "highpass=f=28,lowpass=f=15500,\
aecho=0.75:0.85:53|97:0.28|0.18,afade=t=in:st=0:d=1.2,afade=t=out:st=55.4:d=1.7,\
loudnorm=I=-16:TP=-1.5:LRA=11" -c:a libmp3lame -q:a 3 video/public/soundtrack.mp3
```

The scene cut list in `make_soundtrack.py` is kept in lock-step with `TIMELINE`, so a soft
riser leans into each cut and a low impact lands on it. If you re-time the film, update both.
