"""Bake feature data into keyframes on every reactive parameter.

The function `bake_all` is called once after geometry, materials and
compositor are built. It iterates frames and writes keyframes on every
target. The Blender file becomes self-contained: render or scrub without
re-running analysis.
"""
from __future__ import annotations

import math
from typing import Iterable

import bpy
from mathutils import Vector

from .feature_data import FeatureData
from .scene_geometry import SceneObjects


def _set_kf(obj, data_path: str, value, frame: int, index: int = -1) -> None:
    """Helper: set a value and insert a keyframe at the given frame."""
    if index >= 0:
        # Indexed prop (e.g. rotation_euler)
        if hasattr(obj, "path_resolve"):
            arr = obj.path_resolve(data_path)
            arr[index] = value
        obj.keyframe_insert(data_path=data_path, index=index, frame=frame)
    else:
        # Use exec on the object to set arbitrary path; safer than path_resolve
        # for nested attributes. Most callers pass simple paths.
        try:
            *parts, last = data_path.split(".")
            target = obj
            for p in parts:
                target = getattr(target, p)
            setattr(target, last, value)
        except Exception:
            pass
        obj.keyframe_insert(data_path=data_path, frame=frame)


def _band_mix(fd: FeatureData, f: int, weights: dict[str, float]) -> float:
    return sum(fd.band(name, f) * w for name, w in weights.items())


def bake_all(
    fd: FeatureData,
    so: SceneObjects,
    compositor: dict,
    *,
    start_frame: int,
    end_frame: int,
) -> None:
    """Bake keyframes for all reactive parameters between start..end (inclusive)."""
    scene = bpy.context.scene
    scene.frame_start = start_frame
    scene.frame_end = end_frame
    scene.render.fps = fd.fps

    central = so.central
    wire = so.central_wire
    rings = so.rings
    spots = so.spotlights
    cam = so.camera
    pivot = so.rig

    # Find displacement modifier strengths to drive.
    disp_low = central.modifiers.get("DispLow")
    disp_mid = central.modifiers.get("DispMid")
    disp_high = central.modifiers.get("DispHigh")

    # Resolve material nodes ahead of the loop so we don't re-lookup.
    central_mat = central.data.materials[0]
    central_emit_colour = central_mat.node_tree.nodes.get("AM_EmitColour")
    central_mix = next((n for n in central_mat.node_tree.nodes if n.type == "MIX_SHADER"), None)
    # Math node that adds base emission strength to the fresnel-driven rim.
    central_emit_add = None
    for n in central_mat.node_tree.nodes:
        if n.type == "MATH" and getattr(n, "operation", "") == "ADD":
            central_emit_add = n
            break

    wire_mat = wire.data.materials[0]
    wire_rgb = wire_mat.node_tree.nodes.get("AM_RingColour")
    wire_emit = next((n for n in wire_mat.node_tree.nodes if n.type == "EMISSION"), None)

    ring_mats = []
    for r in rings:
        rm = r.data.materials[0]
        rgb_node = rm.node_tree.nodes.get("AM_RingColour")
        emit_node = next((n for n in rm.node_tree.nodes if n.type == "EMISSION"), None)
        ring_mats.append((rm, rgb_node, emit_node))

    # Spark host + spark instance — the instance object's material emission
    # is what controls the scattered copies' brightness.
    host = so.particles[0]
    instance = so.particles[1]
    p_mat = instance.data.materials[0]
    p_rgb = p_mat.node_tree.nodes.get("AM_ParticleColour")
    p_emit = next((n for n in p_mat.node_tree.nodes if n.type == "EMISSION"), None)

    # Compositor handles (Blender 5.x: Glare 'Strength' replaces old mix nodes).
    bloom = compositor["bloom"]
    streak = compositor["streak"]
    lens = compositor["lens"]
    hsv_node = compositor["hsv"]

    # World volume + bounded domain volume (the domain reads more reliably
    # in EEVEE 5; we drive both for layered density).
    world_nt = bpy.context.scene.world.node_tree
    vol_node = world_nt.nodes.get("AM_WorldVolume")

    domain_vol_node = None
    if so.volume_domain is not None and so.volume_domain.data.materials:
        dm_nt = so.volume_domain.data.materials[0].node_tree
        domain_vol_node = dm_nt.nodes.get("AM_DomainVolume")

    # Map ring index → primary band so each ring has its own personality.
    ring_band_map = ["bass", "low", "low_mid", "mid", "high_mid", "high", "air"]

    print(f"[bake] keyframing frames {start_frame}..{end_frame}")
    n = end_frame - start_frame + 1
    progress_step = max(1, n // 20)

    for f in range(start_frame, end_frame + 1):
        if (f - start_frame) % progress_step == 0:
            pct = 100.0 * (f - start_frame) / max(1, n - 1)
            print(f"[bake] frame {f}  {pct:5.1f}%")

        # Per-frame feature reads (frame index in feature space == video frame).
        rms = fd.rms(f)
        onset = fd.onset(f)
        centroid = fd.centroid(f)
        flatness = fd.flatness(f)
        drop = fd.drop(f)
        beat_phase = fd.beat_phase(f)
        chroma_idx = fd.chroma_class(f)
        chroma_str = fd.chroma_strength(f)

        sub = fd.band("sub", f)
        bass = fd.band("bass", f)
        low_mid = fd.band("low_mid", f)
        mid = fd.band("mid", f)
        high_mid = fd.band("high_mid", f)
        high = fd.band("high", f)
        air = fd.band("air", f)

        # ------- Central form: scale + displacement -------
        scale = 1.0 + 0.18 * sub + 0.08 * rms + 0.05 * onset
        central.scale = (scale, scale, scale)
        central.keyframe_insert(data_path="scale", frame=f)

        # Displacement strengths: layered noise driven by sub+bass (big lobes),
        # mids (medium ripple), highs (fine surface chatter).
        if disp_low:
            disp_low.strength = 0.20 + 1.30 * (sub * 0.7 + bass * 0.3)
            disp_low.keyframe_insert(data_path="strength", frame=f)
        if disp_mid:
            disp_mid.strength = 0.08 + 0.55 * (low_mid * 0.5 + mid * 0.5)
            disp_mid.keyframe_insert(data_path="strength", frame=f)
        if disp_high:
            disp_high.strength = 0.02 + 0.18 * (high * 0.5 + air * 0.5 + onset * 0.3)
            disp_high.keyframe_insert(data_path="strength", frame=f)

        # Slow rotation, with a kick on each beat (use beat_phase to shape).
        rot_z = (f / fd.fps) * 0.08 + 0.4 * (1.0 - beat_phase) * onset * 0.3
        rot_y = (f / fd.fps) * 0.04
        central.rotation_euler = (0.0, rot_y, rot_z)
        central.keyframe_insert(data_path="rotation_euler", frame=f)

        # Wire overlay: scale slightly larger, brightness pulses with onset+highs.
        wscale = scale * 1.04 + 0.04 * onset
        wire.scale = (wscale, wscale, wscale)
        wire.rotation_euler = (rot_y * 0.5, rot_z * 0.6, -rot_z * 0.4)
        wire.keyframe_insert(data_path="scale", frame=f)
        wire.keyframe_insert(data_path="rotation_euler", frame=f)
        if wire_emit is not None:
            wire_emit.inputs["Strength"].default_value = 1.0 + 6.0 * (high * 0.6 + onset * 0.6)
            wire_emit.inputs["Strength"].keyframe_insert(data_path="default_value", frame=f)
        if wire_rgb is not None:
            hue = fd.chroma_to_hue(chroma_idx)
            r, g, b = fd.hsv_to_rgb(hue, 0.5, 1.0)
            wire_rgb.outputs[0].default_value = (r, g, b, 1.0)
            wire_rgb.outputs[0].keyframe_insert(data_path="default_value", frame=f)

        # Central emission colour shifts with chroma.
        if central_emit_colour is not None:
            hue = fd.chroma_to_hue(chroma_idx)
            r, g, b = fd.hsv_to_rgb(hue, 0.7, 1.0)
            central_emit_colour.outputs[0].default_value = (r, g, b, 1.0)
            central_emit_colour.outputs[0].keyframe_insert(data_path="default_value", frame=f)

        # Mix factor between bsdf and emission; emission dominates on flatness/onset.
        if central_mix is not None:
            mix_val = max(0.20, min(0.85, 0.40 + 0.3 * onset + 0.2 * flatness - 0.15 * (1.0 - rms)))
            central_mix.inputs[0].default_value = mix_val
            central_mix.inputs[0].keyframe_insert(data_path="default_value", frame=f)

        # Pump base emission strength with rms + bass.
        if central_emit_add is not None:
            central_emit_add.inputs[1].default_value = 1.5 + 4.0 * (rms * 0.5 + bass * 0.5) + 2.0 * onset
            central_emit_add.inputs[1].keyframe_insert(data_path="default_value", frame=f)

        # ------- Spectral rings -------
        for i, (ring, (rm, rgb_node, emit_node)) in enumerate(zip(rings, ring_mats)):
            band_name = ring_band_map[i % len(ring_band_map)]
            v = fd.band(band_name, f)
            base = 1.0 + 0.05 * i
            ring_scale = base + 0.18 * v + 0.08 * onset
            ring.scale = (ring_scale, ring_scale, ring_scale)
            ring.keyframe_insert(data_path="scale", frame=f)

            # Each ring rotates at a different rate; faster on higher bands.
            spin = (f / fd.fps) * (0.05 + 0.05 * i)
            tilt = math.sin((f / fd.fps) * (0.2 + 0.05 * i)) * 0.05
            ring.rotation_euler = (
                ring.rotation_euler[0] + tilt * 0.0,  # no-op preserves base tilt
                ring.rotation_euler[1],
                ring.rotation_euler[2] + spin * 0.0,  # blender keyframes need real assignment
            )
            # Use additive offsets via rotation delta:
            ring.delta_rotation_euler = (0.0, 0.0, spin + tilt * 0.5)
            ring.keyframe_insert(data_path="delta_rotation_euler", frame=f)

            if emit_node is not None:
                emit_node.inputs["Strength"].default_value = 1.0 + 12.0 * v + 4.0 * onset
                emit_node.inputs["Strength"].keyframe_insert(data_path="default_value", frame=f)

            if rgb_node is not None:
                hue = (fd.chroma_to_hue(chroma_idx) + 0.04 * i) % 1.0
                r, g, b = fd.hsv_to_rgb(hue, 0.85, 1.0)
                rgb_node.outputs[0].default_value = (r, g, b, 1.0)
                rgb_node.outputs[0].keyframe_insert(data_path="default_value", frame=f)

        # ------- Spark field -------
        # Emission strength propagates to all GN-realised copies via the
        # shared material on the instance object.
        if p_emit is not None:
            p_emit.inputs["Strength"].default_value = 2.0 + 14.0 * (high * 0.6 + onset * 0.7)
            p_emit.inputs["Strength"].keyframe_insert(data_path="default_value", frame=f)
        if p_rgb is not None:
            hue = (fd.chroma_to_hue(chroma_idx) + 0.5) % 1.0  # complement of central
            r, g, b = fd.hsv_to_rgb(hue, 0.4, 1.0)
            p_rgb.outputs[0].default_value = (r, g, b, 1.0)
            p_rgb.outputs[0].keyframe_insert(data_path="default_value", frame=f)

        # Spark host shell expands / contracts with bass — sparks ride
        # outward on bass kicks since the GN distribution scales with it.
        es = 1.0 + 0.18 * (bass * 0.5 + sub * 0.5)
        host.scale = (es, es, es)
        host.keyframe_insert(data_path="scale", frame=f)

        # ------- Volumetric spotlights -------
        # Each spotlight binds to a different band so beams pulse at
        # different rates, then mixes its base colour toward the chroma
        # hue so the whole stage shifts with the song key.
        spot_band_pairs = [
            (sub * 0.6 + bass * 0.4),
            (mid * 0.6 + low_mid * 0.4),
            (high * 0.6 + air * 0.4),
            (low_mid * 0.5 + mid * 0.5),
        ]
        spot_base_cols = [
            (0.55, 0.25, 1.0),
            (0.15, 0.55, 1.0),
            (1.0, 0.30, 0.45),
            (0.25, 1.0, 0.85),
        ]
        for i, light in enumerate(spots):
            v = spot_band_pairs[i % len(spot_band_pairs)]
            light.data.energy = 1800 + 6000 * v + 2500 * onset
            light.data.keyframe_insert(data_path="energy", frame=f)

            base_col = spot_base_cols[i % len(spot_base_cols)]
            hue = fd.chroma_to_hue(chroma_idx)
            cr, cg, cb = fd.hsv_to_rgb(hue, 0.7, 1.0)
            mix_t = 0.30 * chroma_str
            col = (
                base_col[0] * (1 - mix_t) + cr * mix_t,
                base_col[1] * (1 - mix_t) + cg * mix_t,
                base_col[2] * (1 - mix_t) + cb * mix_t,
            )
            light.data.color = col
            light.data.keyframe_insert(data_path="color", frame=f)

        # ------- Volumetric density (world + bounded domain) -------
        if vol_node is not None:
            vol_node.inputs["Density"].default_value = 0.05 + 0.10 * (sub * 0.5 + bass * 0.5)
            vol_node.inputs["Density"].keyframe_insert(data_path="default_value", frame=f)
        if domain_vol_node is not None:
            domain_vol_node.inputs["Density"].default_value = 0.30 + 0.40 * (sub * 0.5 + bass * 0.5) + 0.20 * drop
            domain_vol_node.inputs["Density"].keyframe_insert(data_path="default_value", frame=f)

        # ------- Camera orbit + reactive shake -------
        # Slow continuous orbit.
        orbit_speed = 0.04
        orbit_angle = (f / fd.fps) * orbit_speed
        # Add a small reactive offset jitter.
        jitter_x = math.sin(f * 0.31) * 0.04 * rms
        jitter_y = math.cos(f * 0.17) * 0.04 * rms
        # On hard onsets, a quick orbit nudge.
        nudge = 0.04 * onset
        pivot.rotation_euler = (jitter_y, jitter_x, orbit_angle + nudge)
        pivot.keyframe_insert(data_path="rotation_euler", frame=f)

        # Camera FOV pulse with sub bass + drops.
        cam.data.lens = 38 + 6 * (sub * 0.5 + drop * 0.7) - 4 * onset
        cam.data.keyframe_insert(data_path="lens", frame=f)
        # DOF aperture pulses subtly with rms (lower fstop = more blur).
        cam.data.dof.aperture_fstop = max(1.6, 3.2 - 1.0 * rms)
        cam.data.dof.keyframe_insert(data_path="aperture_fstop", frame=f)

        # ------- Compositor reactivity -------
        # Bloom strength rises with overall energy + onset spikes.
        bloom.inputs["Strength"].default_value = 0.4 + 0.55 * rms + 0.4 * onset
        bloom.inputs["Strength"].keyframe_insert(data_path="default_value", frame=f)

        streak.inputs["Strength"].default_value = 0.18 + 0.6 * (high * 0.6 + onset * 0.7)
        streak.inputs["Strength"].keyframe_insert(data_path="default_value", frame=f)

        # Chromatic aberration via lens dispersion: reacts to onset + air + flatness.
        lens.inputs["Dispersion"].default_value = 0.005 + 0.05 * (onset * 0.7 + air * 0.5 + flatness * 0.4)
        lens.inputs["Dispersion"].keyframe_insert(data_path="default_value", frame=f)
        lens.inputs["Distortion"].default_value = 0.0 + 0.025 * drop
        lens.inputs["Distortion"].keyframe_insert(data_path="default_value", frame=f)

        # Saturation breathing: dip on quiet, bloom on intense moments.
        hsv_node.inputs["Saturation"].default_value = 1.0 + 0.18 * rms + 0.12 * onset
        hsv_node.inputs["Saturation"].keyframe_insert(data_path="default_value", frame=f)
