"""Audiomorph — main scene builder.

Run via:
    blender --background --python build_scene.py -- \
        --features <features.json> \
        --audio <song.wav> \
        --out <scene.blend> \
        [--start 0] [--end -1] [--fps 30] [--res 1080]

The trailing `--` separates Blender's own args from this script's args;
argparse picks up only what comes after.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Make sibling modules importable when invoked from any CWD.
_HERE = Path(__file__).resolve().parent
_PARENT = _HERE.parent
if str(_PARENT) not in sys.path:
    sys.path.insert(0, str(_PARENT))

import bpy

from blender import scene_compositor, scene_geometry, scene_keyframes, scene_materials
from blender.feature_data import FeatureData


def _parse_args() -> argparse.Namespace:
    # Blender swallows everything before "--". We grab everything after.
    if "--" in sys.argv:
        argv = sys.argv[sys.argv.index("--") + 1:]
    else:
        argv = []
    p = argparse.ArgumentParser()
    p.add_argument("--features", type=Path, required=True)
    p.add_argument("--audio", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--start", type=int, default=0,
                   help="Start frame (relative to song start, video frames @ fps)")
    p.add_argument("--end", type=int, default=-1,
                   help="End frame inclusive; -1 means full song")
    p.add_argument("--fps", type=int, default=30)
    p.add_argument("--res", type=int, default=1080,
                   help="Vertical resolution; horizontal is 16:9")
    p.add_argument("--samples", type=int, default=24,
                   help="EEVEE TAA samples for render")
    return p.parse_args(argv)


def _setup_render(scene: bpy.types.Scene, *, vres: int, fps: int, samples: int) -> None:
    # Blender 5.x: the EEVEE Next renderer became the only EEVEE.
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x = int(vres * 16 / 9)
    scene.render.resolution_y = vres
    scene.render.resolution_percentage = 100
    scene.render.fps = fps
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGB"
    scene.render.image_settings.compression = 15

    # EEVEE 5 render settings - lean into volumetrics + raytracing.
    eevee = scene.eevee
    if hasattr(eevee, "taa_render_samples"):
        eevee.taa_render_samples = samples
    if hasattr(eevee, "volumetric_tile_size"):
        eevee.volumetric_tile_size = "4"   # finer = better godray detail
    if hasattr(eevee, "volumetric_samples"):
        eevee.volumetric_samples = 128
    if hasattr(eevee, "volumetric_ray_depth"):
        eevee.volumetric_ray_depth = 16
    if hasattr(eevee, "use_volumetric_shadows"):
        eevee.use_volumetric_shadows = True
    if hasattr(eevee, "volumetric_shadow_samples"):
        eevee.volumetric_shadow_samples = 16
    if hasattr(eevee, "volumetric_sample_distribution"):
        eevee.volumetric_sample_distribution = 0.85
    if hasattr(eevee, "volumetric_start"):
        eevee.volumetric_start = 0.05
    if hasattr(eevee, "volumetric_end"):
        eevee.volumetric_end = 50.0
    if hasattr(eevee, "use_raytracing"):
        eevee.use_raytracing = True

    # Color management: filmic gives that cinematic dynamic range.
    scene.view_settings.view_transform = "AgX"
    scene.view_settings.look = "AgX - Punchy"
    scene.view_settings.exposure = 0.0
    scene.view_settings.gamma = 1.0


def main() -> int:
    args = _parse_args()

    print(f"[build] features={args.features}")
    print(f"[build] audio   ={args.audio}")
    print(f"[build] out     ={args.out}")

    fd = FeatureData.load(args.features)
    if fd.fps != args.fps:
        print(f"[build] WARNING: feature fps={fd.fps} but cli fps={args.fps}; using {fd.fps}")
        args.fps = fd.fps

    start = max(0, args.start)
    end = (fd.n_frames - 1) if args.end < 0 else min(args.end, fd.n_frames - 1)
    print(f"[build] frame range {start}..{end}  ({(end-start+1)/args.fps:.1f}s)")

    scene = bpy.context.scene
    scene_geometry.clear_scene()
    scene_materials.make_world_volume(scene.world)

    so = scene_geometry.build_all()
    comp = scene_compositor.setup()

    # Add the audio track to the sequencer so the .blend remembers it.
    if scene.sequence_editor is None:
        scene.sequence_editor_create()
    try:
        scene.sequence_editor.strips.new_sound(
            name="AM_Audio",
            filepath=str(args.audio.resolve()),
            channel=1,
            frame_start=1,
        )
    except Exception as e:
        print(f"[build] could not embed audio: {e}")

    _setup_render(scene, vres=args.res, fps=args.fps, samples=args.samples)

    # Bake all reactive keyframes.
    # Frame range in Blender is 1-indexed by convention; we offset accordingly.
    blender_start = 1
    blender_end = end - start + 1
    scene_keyframes.bake_all(
        fd,
        so,
        comp,
        start_frame=blender_start,
        end_frame=blender_end,
    )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(args.out.resolve()))
    print(f"[build] saved {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
