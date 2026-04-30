"""Geometry construction for Audiomorph.

Each helper returns the created Blender objects so the keyframer can
attach them to feature channels.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

import bmesh
import bpy
from mathutils import Vector

from . import scene_materials


@dataclass
class SceneObjects:
    central: bpy.types.Object | None = None
    central_wire: bpy.types.Object | None = None
    rings: list[bpy.types.Object] = field(default_factory=list)
    particles: list[bpy.types.Object] = field(default_factory=list)
    spotlights: list[bpy.types.Object] = field(default_factory=list)
    camera: bpy.types.Object | None = None
    rig: bpy.types.Object | None = None  # camera target / orbit pivot
    volume_domain: bpy.types.Object | None = None


def clear_scene() -> None:
    """Clear default cube etc. and reset world."""
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for coll in [bpy.data.meshes, bpy.data.materials, bpy.data.lights, bpy.data.cameras]:
        for item in list(coll):
            if item.users == 0:
                coll.remove(item)


def add_central_form(name: str = "AM_Central") -> tuple[bpy.types.Object, bpy.types.Object]:
    """Subdivided icosphere with displacement modifiers tied to noise textures.

    Returns (solid_form, wireframe_overlay). The wireframe is a much
    smaller halo strung *outside* the form, behaving as an additional
    reactive ring rather than a grid mask.
    """
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=4, radius=1.0, location=(0, 0, 0))
    obj = bpy.context.active_object
    obj.name = name
    bpy.ops.object.shade_smooth()

    # --- Low frequency displacement (sub/bass): big slow lobes.
    tex_low = bpy.data.textures.new("AM_DispLow", type="VORONOI")
    if hasattr(tex_low, "noise_scale"):
        tex_low.noise_scale = 1.4
    if hasattr(tex_low, "distance_metric"):
        tex_low.distance_metric = "DISTANCE"
    mod_low = obj.modifiers.new(name="DispLow", type="DISPLACE")
    mod_low.texture = tex_low
    mod_low.strength = 0.0
    mod_low.mid_level = 0.4

    # --- Mid: medium ripple.
    tex_mid = bpy.data.textures.new("AM_DispMid", type="CLOUDS")
    if hasattr(tex_mid, "noise_scale"):
        tex_mid.noise_scale = 0.5
    mod_mid = obj.modifiers.new(name="DispMid", type="DISPLACE")
    mod_mid.texture = tex_mid
    mod_mid.strength = 0.0
    mod_mid.mid_level = 0.5

    # --- High: fine chatter.
    tex_high = bpy.data.textures.new("AM_DispHigh", type="DISTORTED_NOISE")
    if hasattr(tex_high, "noise_scale"):
        tex_high.noise_scale = 0.18
    if hasattr(tex_high, "distortion"):
        tex_high.distortion = 1.5
    mod_high = obj.modifiers.new(name="DispHigh", type="DISPLACE")
    mod_high.texture = tex_high
    mod_high.strength = 0.0
    mod_high.mid_level = 0.5

    sub = obj.modifiers.new(name="Subsurf", type="SUBSURF")
    sub.levels = 3
    sub.render_levels = 3

    mat = scene_materials.make_central_material()
    if obj.data.materials:
        obj.data.materials[0] = mat
    else:
        obj.data.materials.append(mat)

    # --- Optional wireframe shell (pulse-only). Disabled by render
    # default — kept as an object so keyframes still resolve, but very
    # small and dim so it doesn't dominate the form.
    bpy.ops.object.duplicate()
    wire = bpy.context.active_object
    wire.name = name + "_Wire"
    for mod_name in ["DispLow", "DispMid", "DispHigh", "Subsurf"]:
        m = wire.modifiers.get(mod_name)
        if m:
            wire.modifiers.remove(m)
    wire.scale = (1.7, 1.7, 1.7)
    wf = wire.modifiers.new(name="Wireframe", type="WIREFRAME")
    wf.thickness = 0.005
    wf.use_replace = True

    wire_mat = scene_materials.make_ring_material("AM_Wire", base_hue=0.6)
    if wire.data.materials:
        wire.data.materials[0] = wire_mat
    else:
        wire.data.materials.append(wire_mat)

    # Default-hide. The wireframe shell exists only for users who want
    # to re-enable it; current look favours the displaced surface alone.
    wire.hide_render = True
    wire.hide_viewport = True

    bpy.context.view_layer.objects.active = obj

    return obj, wire


def add_spectral_rings(count: int = 5) -> list[bpy.types.Object]:
    """Concentric tilted glowing rings around the central form."""
    rings: list[bpy.types.Object] = []
    rng = random.Random(42)
    base_radii = [1.6, 2.1, 2.7, 3.4, 4.2][:count]
    minor_radii = [0.015, 0.018, 0.014, 0.020, 0.012][:count]

    for i, radius in enumerate(base_radii):
        bpy.ops.mesh.primitive_torus_add(
            major_radius=radius,
            minor_radius=minor_radii[i],
            major_segments=160,
            minor_segments=12,
            location=(0, 0, 0),
        )
        ring = bpy.context.active_object
        ring.name = f"AM_Ring_{i}"
        # Tilt each ring on a different axis combo for visual depth.
        ring.rotation_euler = (
            rng.uniform(-0.9, 0.9),
            rng.uniform(-0.9, 0.9),
            rng.uniform(0, 6.28),
        )
        bpy.ops.object.shade_smooth()
        mat = scene_materials.make_ring_material(f"AM_Ring_{i}_Mat", base_hue=0.55 + 0.05 * i)
        if ring.data.materials:
            ring.data.materials[0] = mat
        else:
            ring.data.materials.append(mat)
        rings.append(ring)

    return rings


def add_spark_field(count: int = 800, radius: float = 4.5) -> list[bpy.types.Object]:
    """Geometry Nodes scatter: an ico-sphere instanced on points scattered
    on the surface of an invisible host sphere. The instance object's
    emission strength + scale is keyframed for reactivity.
    """
    # Host sphere — surface gets sampled.
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=4, radius=radius, location=(0, 0, 0))
    host = bpy.context.active_object
    host.name = "AM_SparkHost"
    host.display_type = "WIRE"
    host.hide_select = True

    # Spark template — tiny icosphere with emissive material.
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=1, radius=0.04, location=(40, 0, 0))
    spark = bpy.context.active_object
    spark.name = "AM_SparkInstance"
    bpy.ops.object.shade_smooth()
    spark.hide_render = False
    p_mat = scene_materials.make_particle_material()
    if spark.data.materials:
        spark.data.materials[0] = p_mat
    else:
        spark.data.materials.append(p_mat)
    # Park instance off-screen — only the GN scatter copies render.
    spark.hide_render = True

    # Build a Geometry Nodes group on the host: distribute points + instance.
    gnt = bpy.data.node_groups.new("AM_SparkGN", "GeometryNodeTree")
    gnt.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    gnt.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    gnt.interface.new_socket("Density", in_out="INPUT", socket_type="NodeSocketFloat")
    gnt.interface.new_socket("Spark Size", in_out="INPUT", socket_type="NodeSocketFloat")

    nodes = gnt.nodes
    links = gnt.links

    grp_in = nodes.new("NodeGroupInput")
    grp_in.location = (-800, 0)
    grp_out = nodes.new("NodeGroupOutput")
    grp_out.location = (800, 0)

    distribute = nodes.new("GeometryNodeDistributePointsOnFaces")
    distribute.location = (-400, 100)
    distribute.distribute_method = "RANDOM"
    distribute.inputs["Density"].default_value = float(count) / (4 * 3.14159 * radius * radius)

    instance_on = nodes.new("GeometryNodeInstanceOnPoints")
    instance_on.location = (0, 100)

    obj_info = nodes.new("GeometryNodeObjectInfo")
    obj_info.location = (-200, -200)
    obj_info.inputs["Object"].default_value = spark

    rand_scale = nodes.new("FunctionNodeRandomValue")
    rand_scale.location = (-200, -50)
    rand_scale.data_type = "FLOAT"
    rand_scale.inputs["Min"].default_value = 0.4
    rand_scale.inputs["Max"].default_value = 1.6

    realize = nodes.new("GeometryNodeRealizeInstances")
    realize.location = (400, 100)

    links.new(grp_in.outputs["Geometry"], distribute.inputs["Mesh"])
    links.new(distribute.outputs["Points"], instance_on.inputs["Points"])
    links.new(obj_info.outputs["Geometry"], instance_on.inputs["Instance"])
    links.new(rand_scale.outputs["Value"], instance_on.inputs["Scale"])
    links.new(instance_on.outputs["Instances"], realize.inputs["Geometry"])
    links.new(realize.outputs["Geometry"], grp_out.inputs["Geometry"])

    # Attach the GN modifier to the host.
    bpy.context.view_layer.objects.active = host
    mod = host.modifiers.new(name="SparkScatter", type="NODES")
    mod.node_group = gnt

    return [host, spark]


def add_volumetric_lighting() -> list[bpy.types.Object]:
    """Four coloured spotlights raking the scene from behind so god-rays
    pass between camera and central form. Each light has a small target
    offset from origin so the beams aren't all collinear.
    """
    spots: list[bpy.types.Object] = []
    layout = [
        # (light pos,                target offset,            color)
        ((6, 8, 5),  (-0.6, -0.4, 0.0), (0.55, 0.25, 1.0)),    # top-back violet
        ((-7, 8, 3), ( 0.4, -0.5, 0.5), (0.15, 0.55, 1.0)),    # top-back blue
        ((4, 7, -2), (-0.3,  0.2, 0.8), (1.0, 0.30, 0.45)),    # back-low magenta
        ((-2, 9, 7), ( 0.0,  0.4, -0.5),(0.25, 1.0, 0.85)),    # high back teal
    ]
    for i, (loc, target_offset, col) in enumerate(layout):
        bpy.ops.object.light_add(type="SPOT", location=loc)
        light = bpy.context.active_object
        light.name = f"AM_Spot_{i}"
        ld = light.data
        ld.energy = 3500.0
        ld.color = col
        ld.spot_size = math.radians(28)     # tighter cone = sharper beams
        ld.spot_blend = 0.40
        ld.use_shadow = True
        ld.shadow_soft_size = 0.3

        bpy.ops.object.empty_add(type="PLAIN_AXES", location=target_offset)
        target = bpy.context.active_object
        target.name = f"AM_SpotTarget_{i}"
        constraint = light.constraints.new(type="TRACK_TO")
        constraint.target = target
        constraint.track_axis = "TRACK_NEGATIVE_Z"
        constraint.up_axis = "UP_Y"
        spots.append(light)
    return spots


def add_volume_domain() -> bpy.types.Object | None:
    """A large bounded volume cube produces more reliable god-rays in
    EEVEE 5 than relying on the world volume alone. The cube is invisible
    apart from its volume contribution.
    """
    bpy.ops.mesh.primitive_cube_add(size=20.0, location=(0, 0, 0))
    obj = bpy.context.active_object
    obj.name = "AM_VolumeDomain"
    obj.display_type = "WIRE"
    obj.hide_select = True
    # No surface render: only volume contributes.
    mat = bpy.data.materials.new("AM_VolumeMat")
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    vol = nt.nodes.new("ShaderNodeVolumeScatter")
    vol.inputs["Density"].default_value = 0.25
    vol.inputs["Anisotropy"].default_value = 0.75
    vol.name = "AM_DomainVolume"
    nt.links.new(vol.outputs[0], out.inputs["Volume"])
    obj.data.materials.append(mat)
    return obj


def add_camera() -> tuple[bpy.types.Object, bpy.types.Object]:
    """Camera on an empty rig that orbits a central pivot.

    Returns (camera, orbit_empty).
    """
    bpy.ops.object.empty_add(type="PLAIN_AXES", location=(0, 0, 0))
    pivot = bpy.context.active_object
    pivot.name = "AM_CameraPivot"

    bpy.ops.object.camera_add(location=(0, -5.6, 0.6))
    cam = bpy.context.active_object
    cam.name = "AM_Camera"
    cam.parent = pivot
    cam.data.lens = 50
    cam.data.dof.use_dof = True
    cam.data.dof.focus_distance = 5.6
    cam.data.dof.aperture_fstop = 2.4

    # Track-to centre so it always frames the form even when we displace.
    bpy.ops.object.empty_add(type="PLAIN_AXES", location=(0, 0, 0))
    target = bpy.context.active_object
    target.name = "AM_CameraTarget"
    constraint = cam.constraints.new(type="TRACK_TO")
    constraint.target = target
    constraint.track_axis = "TRACK_NEGATIVE_Z"
    constraint.up_axis = "UP_Y"

    bpy.context.scene.camera = cam
    return cam, pivot


def build_all() -> SceneObjects:
    so = SceneObjects()
    central, wire = add_central_form()
    so.central = central
    so.central_wire = wire
    so.rings = add_spectral_rings()
    so.particles = add_spark_field()
    so.spotlights = add_volumetric_lighting()
    so.volume_domain = add_volume_domain()
    cam, pivot = add_camera()
    so.camera = cam
    so.rig = pivot
    return so
