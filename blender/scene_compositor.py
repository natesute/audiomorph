"""Compositor / post-processing for Audiomorph (Blender 5.x).

Blender 5.0 reorganised the compositor: it is a NodeGroup assigned to
`scene.compositing_node_group`, several node configs moved from properties
to socket inputs, and several legacy nodes were removed. We use only
nodes that exist in 5.x:
    Glare         — bloom + streaks via 'Strength' input
    Lensdist      — chromatic aberration via 'Dispersion'
    ColorBalance  — Lift/Gamma/Gain via colour sockets
    BrightContrast / HueSat — final tonal lift
"""
from __future__ import annotations

import bpy


def _build_node_group() -> bpy.types.NodeTree:
    name = "AM_Compositor"
    existing = bpy.data.node_groups.get(name)
    if existing is not None:
        bpy.data.node_groups.remove(existing)
    nt = bpy.data.node_groups.new(name, "CompositorNodeTree")
    bpy.context.scene.compositing_node_group = nt
    return nt


def _ensure_image_output(nt: bpy.types.NodeTree) -> None:
    """Ensure the node group has a single 'Image' output socket."""
    has_out = any(
        s.in_out == "OUTPUT" and s.socket_type == "NodeSocketColor"
        for s in nt.interface.items_tree
        if getattr(s, "item_type", "") == "SOCKET"
    )
    if not has_out:
        nt.interface.new_socket(name="Image", in_out="OUTPUT", socket_type="NodeSocketColor")


def setup() -> dict:
    nt = _build_node_group()
    _ensure_image_output(nt)
    nodes = nt.nodes
    links = nt.links

    rl = nodes.new("CompositorNodeRLayers")
    rl.location = (-1400, 0)

    # --- Bloom (Fog Glow): adds soft halo to bright areas.
    bloom = nodes.new("CompositorNodeGlare")
    bloom.location = (-1100, 200)
    bloom.inputs["Type"].default_value = "Fog Glow"
    bloom.inputs["Quality"].default_value = "High"
    bloom.inputs["Threshold"].default_value = 0.6
    bloom.inputs["Size"].default_value = 8
    bloom.inputs["Strength"].default_value = 0.6
    bloom.name = "AM_Bloom"

    # --- Streaks: anamorphic-feeling streaks on hot pixels.
    streak = nodes.new("CompositorNodeGlare")
    streak.location = (-800, 200)
    streak.inputs["Type"].default_value = "Streaks"
    streak.inputs["Quality"].default_value = "High"
    streak.inputs["Threshold"].default_value = 0.85
    streak.inputs["Iterations"].default_value = 3
    streak.inputs["Streaks"].default_value = 4
    streak.inputs["Fade"].default_value = 0.85
    streak.inputs["Strength"].default_value = 0.35
    streak.name = "AM_Streak"

    # --- Lens distortion → 'Dispersion' = chromatic aberration.
    lens = nodes.new("CompositorNodeLensdist")
    lens.location = (-500, 200)
    lens.inputs["Distortion"].default_value = 0.0
    lens.inputs["Dispersion"].default_value = 0.012
    lens.inputs["Fit"].default_value = True
    lens.name = "AM_Lens"

    # --- Color grade: lift toward teal, gain warm.
    cb = nodes.new("CompositorNodeColorBalance")
    cb.location = (-200, 200)
    cb.inputs["Type"].default_value = "Lift/Gamma/Gain"
    # NOTE: there are two sockets named 'Lift' (factor + colour); set the
    # colour one which is the second socket (index 4).
    cb.inputs[4].default_value = (0.96, 1.00, 1.06, 1.0)   # Lift colour
    cb.inputs[8].default_value = (1.05, 1.00, 0.96, 1.0)   # Gain colour
    cb.name = "AM_Grade"

    # --- Mild contrast bump.
    bcs = nodes.new("CompositorNodeBrightContrast")
    bcs.location = (100, 200)
    bcs.inputs["Brightness"].default_value = -0.02
    bcs.inputs["Contrast"].default_value = 0.10

    # --- Saturation lift.
    hsv = nodes.new("CompositorNodeHueSat")
    hsv.location = (350, 200)
    hsv.inputs["Saturation"].default_value = 1.10

    # --- Group output.
    out = nodes.new("NodeGroupOutput")
    out.location = (700, 200)

    # --- Wire it.
    links.new(rl.outputs["Image"], bloom.inputs["Image"])
    links.new(bloom.outputs["Image"], streak.inputs["Image"])
    links.new(streak.outputs["Image"], lens.inputs["Image"])
    links.new(lens.outputs["Image"], cb.inputs["Image"])
    links.new(cb.outputs["Image"], bcs.inputs["Image"])
    links.new(bcs.outputs["Image"], hsv.inputs["Image"])
    links.new(hsv.outputs["Image"], out.inputs[0])

    return {
        "bloom": bloom,
        "streak": streak,
        "lens": lens,
        "grade": cb,
        "hsv": hsv,
    }
