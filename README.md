# audiomorph

Audio-reactive Blender music visualiser, built around the Blender 5.x
Python API. The pipeline turns a song into a procedurally generated 3D
scene whose every reactive element — geometry displacement, ring scales,
volumetric god-rays, spark field, camera, post-FX — is keyframed from
features extracted by [librosa](https://librosa.org).

The look is intentionally experimental, leaning toward klsr.av /
sakrmusic territory: a single morphing organic form at the centre,
concentric tilted rings reading individual frequency bands, a volumetric
atmosphere that pulses with the bass, a complementary spark field, and a
filmic post stack (bloom, anamorphic streaks, chromatic aberration,
AgX‑Punchy grade).

## Pipeline

```
audio.wav  ──►  analyse.py  ──►  features.json
                                       │
                                       ▼
                              build_scene.py (Blender 5)
                                       │
                                       ▼
                                  scene.blend
                                       │
                                       ▼
                              EEVEE render → frames/*.png
                                       │
                                       ▼
                                ffmpeg mux ──► song.mp4
```

A single shell script glues all four stages together:

```bash
./scripts/visualise.sh "/path/to/song.wav"
```

For a full directory of stems / songs:

```bash
./scripts/visualise_all.sh "/path/to/folder"
```

## What's reactive

| Audio feature                | Drives                                        |
|------------------------------|-----------------------------------------------|
| RMS loudness                 | central scale, camera shake, saturation       |
| Sub (20–60 Hz)               | low-frequency displacement lobes, volume      |
| Bass (60–180 Hz)             | volumetric density, bass-ring scale + light   |
| Low-mid / Mid                | medium displacement noise, mid spotlight      |
| High-mid / High / Air        | fine surface chatter, sparks, chromatic-ab    |
| Onset envelope               | scale spikes, streak strength, lens wobble    |
| Spectral flatness            | "noisier" sound → more glitch, emission lift  |
| Drop score (bass deltas)     | volumetric density bursts, lens distortion    |
| Beat phase (0..1 between)    | rotation easing on rings + central form       |
| Chroma class (musical key)   | global hue rotation across rings/lights/form  |
| Beat positions (frame list)  | embedded as event list for downstream cuts    |

All features are produced once per video frame and baked into the .blend
as keyframes — so the .blend file is self-contained: scrubbing,
re-rendering at a different resolution, or hand-tweaking the result is
all possible without re-running analysis.

## Quick start

```bash
# 1. Blender 5.x must be installed (assumed at /Applications/Blender.app
#    on macOS — override with $BLENDER env var on Linux / custom paths).
brew install --cask blender

# 2. Audio analysis venv (Python 3.11).
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 3. Run the pipeline on a song.
./scripts/visualise.sh "/path/to/Beat 25.wav"
```

Output is written to `output/<song-slug>/`:
```
output/beat-25/
├── features.json     # per-frame feature data
├── scene.blend       # built Blender scene with audio embedded
├── frames/           # PNG sequence
└── beat-25.mp4       # final muxed video
```

### Common options

```bash
# Render only a 30-second window (60s..90s).
./scripts/visualise.sh song.wav --start 60 --end 90

# Lower-res preview (faster).
./scripts/visualise.sh song.wav --res 720 --samples 16

# Re-render an existing .blend without re-doing analysis or build.
./scripts/visualise.sh song.wav --skip-analyse --skip-build
```

## Project layout

```
audiomorph/
├── README.md
├── requirements.txt
├── analysis/
│   └── analyze.py            # librosa pipeline → features JSON
├── blender/
│   ├── build_scene.py        # entry: orchestrates everything in Blender
│   ├── feature_data.py       # JSON loader + helpers (HSV, smoothing)
│   ├── scene_geometry.py     # central form, rings, sparks, lights, camera
│   ├── scene_materials.py    # iridescent shader, ring emission, world vol
│   ├── scene_compositor.py   # Glare bloom + streaks, Lensdist, grade
│   └── scene_keyframes.py    # bakes feature data → keyframes per frame
├── scripts/
│   ├── visualise.sh          # full pipeline for one song
│   ├── visualise_all.sh      # iterate the full pipeline over a folder
│   └── render_frames.sh      # render-only helper for an existing .blend
└── output/
    └── <song-slug>/...
```

## Notes on Blender 5.x

The 5.0 / 5.1 release reorganised quite a few APIs. This project
already accounts for them, but they're worth knowing if you extend it:

- The compositor is now a `NodeGroup` assigned to
  `scene.compositing_node_group`. `scene.node_tree` is gone.
- `CompositorNodeMix`, `CompositorNodeMixRGB`, `CompositorNodeTexture`,
  and `CompositorNodeComposite` were removed. The compositor output is
  the node group's `NodeGroupOutput`.
- Most node configuration moved from RNA properties to socket inputs:
  `Glare.Type`, `ColorBalance.Lift`/`Gain`, `BrightContrast.Brightness`
  etc. are all `inputs[…].default_value` now.
- `BLENDER_EEVEE_NEXT` no longer exists — the renamed engine is just
  `BLENDER_EEVEE`.
- `SequenceEditor.sequences` is now `.strips`.
- World volume scattering still works, but a bounded volume cube (a
  Volume Domain object) gives more reliable god-rays in EEVEE 5.

## Sound sources used in this repo

The demo render was driven by `Beat 25 [48kHz 24-bit master].wav` from
a personal stems archive. Replace the audio path in the visualise script
with any 16/24-bit WAV or MP3 — analysis runs on whatever librosa can
load.
