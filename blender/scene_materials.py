"""Material / shader graphs for Audiomorph.

All material creation goes through here so colours and shader response are
consistent across the scene. Materials expose named inputs that the
keyframe layer drives.
"""
from __future__ import annotations

import bpy


def _new_material(name: str) -> bpy.types.Material:
    mat = bpy.data.materials.get(name)
    if mat is not None:
        bpy.data.materials.remove(mat)
    mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    mat.node_tree.nodes.clear()
    return mat


def make_central_material() -> bpy.types.Material:
    """Iridescent / liquid-metal central form material.

    Strategy: a Principled BSDF with strong coat for the highlight + an
    emission shader whose colour comes from a Fresnel-driven ColorRamp
    (so the rim lights up in a different hue than the front face).
    Final mix between bsdf and emission is keyframed per frame.
    """
    mat = _new_material("AM_Central")
    nt = mat.node_tree
    nodes = nt.nodes
    links = nt.links

    out = nodes.new("ShaderNodeOutputMaterial")
    out.location = (1300, 0)

    mix = nodes.new("ShaderNodeMixShader")
    mix.location = (1000, 0)
    mix.inputs[0].default_value = 0.55

    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (700, 250)
    bsdf.inputs["Metallic"].default_value = 0.65
    bsdf.inputs["Roughness"].default_value = 0.28
    if "IOR" in bsdf.inputs:
        bsdf.inputs["IOR"].default_value = 1.55
    if "Coat Weight" in bsdf.inputs:
        bsdf.inputs["Coat Weight"].default_value = 0.5
        bsdf.inputs["Coat Roughness"].default_value = 0.10
    if "Anisotropic" in bsdf.inputs:
        bsdf.inputs["Anisotropic"].default_value = 0.4

    emit = nodes.new("ShaderNodeEmission")
    emit.location = (700, -200)
    emit.inputs["Strength"].default_value = 4.0

    # Fresnel for rim brightness.
    fresnel = nodes.new("ShaderNodeFresnel")
    fresnel.location = (-100, 250)
    fresnel.inputs["IOR"].default_value = 1.45

    # ColorRamp drives base colour from view angle: deep core, bright rim.
    ramp = nodes.new("ShaderNodeValToRGB")
    ramp.location = (200, 250)
    el = ramp.color_ramp.elements
    el[0].position = 0.0
    el[0].color = (0.04, 0.02, 0.10, 1.0)
    el[1].position = 1.0
    el[1].color = (0.85, 0.55, 1.0, 1.0)
    e2 = ramp.color_ramp.elements.new(0.45)
    e2.color = (0.20, 0.40, 0.95, 1.0)

    # Driven colour from chroma → goes to base + emit.
    emit_colour = nodes.new("ShaderNodeRGB")
    emit_colour.location = (200, -200)
    emit_colour.outputs[0].default_value = (0.6, 0.3, 1.0, 1.0)
    emit_colour.name = "AM_EmitColour"

    # Mix the ramp output with the chroma colour so base shifts with key.
    base_mix = nodes.new("ShaderNodeMixRGB")
    base_mix.location = (450, 250)
    base_mix.blend_type = "MULTIPLY"
    base_mix.inputs[0].default_value = 0.55

    # Boost emission via fresnel: rim glows hotter.
    rim_boost = nodes.new("ShaderNodeMath")
    rim_boost.operation = "MULTIPLY"
    rim_boost.location = (450, -100)
    rim_boost.inputs[1].default_value = 4.0   # multiplier on the fresnel value

    emit_strength_add = nodes.new("ShaderNodeMath")
    emit_strength_add.operation = "ADD"
    emit_strength_add.location = (650, -100)
    emit_strength_add.inputs[1].default_value = 2.0   # base emission strength

    links.new(fresnel.outputs["Fac"], ramp.inputs["Fac"])
    links.new(ramp.outputs["Color"], base_mix.inputs[1])
    links.new(emit_colour.outputs["Color"], base_mix.inputs[2])
    links.new(base_mix.outputs["Color"], bsdf.inputs["Base Color"])

    links.new(emit_colour.outputs["Color"], emit.inputs["Color"])

    links.new(fresnel.outputs["Fac"], rim_boost.inputs[0])
    links.new(rim_boost.outputs[0], emit_strength_add.inputs[0])
    links.new(emit_strength_add.outputs[0], emit.inputs["Strength"])

    links.new(bsdf.outputs[0], mix.inputs[1])
    links.new(emit.outputs[0], mix.inputs[2])
    links.new(mix.outputs[0], out.inputs[0])

    return mat


def make_ring_material(name: str, base_hue: float = 0.62) -> bpy.types.Material:
    """Pure emissive ring material with an exposed strength + colour."""
    mat = _new_material(name)
    nt = mat.node_tree
    nodes = nt.nodes
    links = nt.links

    out = nodes.new("ShaderNodeOutputMaterial")
    out.location = (600, 0)

    emit = nodes.new("ShaderNodeEmission")
    emit.location = (300, 0)
    emit.inputs["Strength"].default_value = 4.0

    rgb = nodes.new("ShaderNodeRGB")
    rgb.location = (0, 0)
    rgb.name = "AM_RingColour"
    # Default sets a cool blue; feature_data writes new values per frame.
    rgb.outputs[0].default_value = (0.3, 0.6, 1.0, 1.0)

    links.new(rgb.outputs["Color"], emit.inputs["Color"])
    links.new(emit.outputs[0], out.inputs["Surface"])

    return mat


def make_particle_material() -> bpy.types.Material:
    mat = _new_material("AM_Particle")
    nt = mat.node_tree
    nodes = nt.nodes
    links = nt.links

    out = nodes.new("ShaderNodeOutputMaterial")
    out.location = (600, 0)

    emit = nodes.new("ShaderNodeEmission")
    emit.location = (300, 0)
    emit.inputs["Strength"].default_value = 6.0

    rgb = nodes.new("ShaderNodeRGB")
    rgb.location = (0, 0)
    rgb.name = "AM_ParticleColour"
    rgb.outputs[0].default_value = (0.85, 0.95, 1.0, 1.0)

    links.new(rgb.outputs["Color"], emit.inputs["Color"])
    links.new(emit.outputs[0], out.inputs["Surface"])
    return mat


def make_floor_material() -> bpy.types.Material:
    """Subtle grid-reflection floor (only used if floor enabled)."""
    mat = _new_material("AM_Floor")
    nt = mat.node_tree
    nodes = nt.nodes
    links = nt.links

    out = nodes.new("ShaderNodeOutputMaterial")
    out.location = (600, 0)
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (300, 0)
    bsdf.inputs["Base Color"].default_value = (0.02, 0.02, 0.03, 1.0)
    bsdf.inputs["Metallic"].default_value = 0.7
    bsdf.inputs["Roughness"].default_value = 0.25
    links.new(bsdf.outputs[0], out.inputs["Surface"])
    return mat


def make_world_volume(world: bpy.types.World) -> None:
    """Light, even volumetric atmosphere set up on the world."""
    world.use_nodes = True
    nt = world.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputWorld")
    out.location = (600, 0)

    bg = nt.nodes.new("ShaderNodeBackground")
    bg.location = (300, 200)
    bg.inputs["Color"].default_value = (0.005, 0.005, 0.012, 1.0)
    bg.inputs["Strength"].default_value = 0.4

    vol = nt.nodes.new("ShaderNodeVolumeScatter")
    vol.location = (300, -200)
    vol.inputs["Density"].default_value = 0.35
    vol.inputs["Anisotropy"].default_value = 0.75
    vol.name = "AM_WorldVolume"

    nt.links.new(bg.outputs[0], out.inputs["Surface"])
    nt.links.new(vol.outputs[0], out.inputs["Volume"])
