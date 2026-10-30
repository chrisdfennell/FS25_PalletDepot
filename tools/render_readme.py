"""Renders the README images (EEVEE, sun, sky and a grass ground) of build/depot.blend into docs/images/.

    blender --background build/depot.blend --python tools/render_readme.py -- [out_dir] [width]

Cameras are given in i3d coordinates (x along the front wall, y up, +z out of the loading front), as in
render_preview.py. JPEG output keeps the repository small.
"""
import math
import os
import sys

import bpy
from mathutils import Vector

HERE = os.path.dirname(os.path.abspath(bpy.data.filepath))
ROOT = os.path.dirname(HERE)
argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
OUT = os.path.abspath(argv[0]) if argv else os.path.join(ROOT, "docs", "images")
WIDTH = int(argv[1]) if len(argv) > 1 else 1600
os.makedirs(OUT, exist_ok=True)


def b3(p):
    return Vector((p[0], -p[2], p[1]))


for obj in bpy.data.objects:      # full LOD0 with every pallet, no helpers
    obj.hide_render = bool(obj.get("i3D_nonRenderable", False)) or obj.name in ("lod1", "lod2")
    if obj.name.startswith("stock"):
        obj.hide_render = False

scene = bpy.context.scene
scene.render.engine = "BLENDER_EEVEE"
scene.render.resolution_x = WIDTH
scene.render.film_transparent = False
scene.render.image_settings.file_format = "JPEG"
scene.render.image_settings.quality = 88
eevee = scene.eevee
eevee.taa_render_samples = 96
for attr, value in (("use_shadows", True), ("use_raytracing", True), ("shadow_ray_count", 2),
                    ("use_fast_gi", True)):
    if hasattr(eevee, attr):
        setattr(eevee, attr, value)
scene.view_settings.view_transform = "AgX"
try:
    scene.view_settings.look = "AgX - Medium High Contrast"
except TypeError:
    pass

# sky
world = bpy.data.worlds.new("readmeWorld")
scene.world = world
world.use_nodes = True
wn = world.node_tree.nodes
wl = world.node_tree.links
background = wn["Background"]
background.inputs["Strength"].default_value = 0.3
try:
    sky = wn.new("ShaderNodeTexSky")
    sky.sun_elevation = math.radians(28)
    sky.sun_rotation = math.radians(150)
    wl.new(sky.outputs["Color"], background.inputs["Color"])
except Exception:  # noqa: BLE001 - older/newer sky node variants: fall back to a flat blue
    background.inputs["Color"].default_value = (0.45, 0.62, 0.85, 1)
    background.inputs["Strength"].default_value = 1.0

# sun: afternoon light from the front right, so the left gable is in shade
sun = bpy.data.objects.new("readmeSun", bpy.data.lights.new("readmeSun", "SUN"))
scene.collection.objects.link(sun)
sun.data.energy = 5.0
sun.data.color = (1.0, 0.94, 0.84)
sun.data.angle = math.radians(1.5)
to_sun = b3((0.5, 0.6, 0.62)).normalized()
sun.rotation_euler = (-to_sun).to_track_quat("-Z", "Y").to_euler()

# soft fill inside the hall, otherwise the interior shots are black
fill = bpy.data.objects.new("readmeFill", bpy.data.lights.new("readmeFill", "AREA"))
scene.collection.objects.link(fill)
fill.data.shape = "RECTANGLE"
fill.data.size, fill.data.size_y = 26.0, 14.0
fill.data.energy = 4500
fill.data.color = (1.0, 0.97, 0.92)
fill.location = b3((0, 6.8, -1))
fill.rotation_euler = (0, 0, 0)     # area lights point down -Z

# grass ground with some variation
bpy.ops.mesh.primitive_plane_add(size=600, location=(0, 0, -0.06))
ground = bpy.context.active_object
mat = bpy.data.materials.new("readmeGrass")
mat.use_nodes = True
nodes, links = mat.node_tree.nodes, mat.node_tree.links
bsdf = nodes["Principled BSDF"]
bsdf.inputs["Roughness"].default_value = 0.95
noise = nodes.new("ShaderNodeTexNoise")
noise.inputs["Scale"].default_value = 0.08
noise.inputs["Detail"].default_value = 8
ramp = nodes.new("ShaderNodeValToRGB")
ramp.color_ramp.elements[0].color = (0.07, 0.13, 0.035, 1)
ramp.color_ramp.elements[1].color = (0.17, 0.24, 0.07, 1)
links.new(noise.outputs["Fac"], ramp.inputs["Fac"])
links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
ground.data.materials.append(mat)

cam = bpy.data.objects.new("readmeCam", bpy.data.cameras.new("readmeCam"))
scene.collection.objects.link(cam)
scene.camera = cam
cam.data.clip_end = 2000


def set_brand(brand):
    for node in bpy.data.materials["depot_brand"].node_tree.nodes:
        if node.type == "TEX_IMAGE" and "_diffuse" in node.image.filepath:
            node.image.filepath = os.path.join(ROOT, "textures", "depot_brand_%s_diffuse.dds" % brand)
            node.image.reload()


def shoot(name, eye_i3d, target_i3d, lens=32, brand="food", aspect=16 / 9):
    set_brand(brand)
    scene.render.resolution_y = round(WIDTH / aspect)
    eye, target = b3(eye_i3d), b3(target_i3d)
    cam.location = eye
    cam.rotation_euler = (target - eye).to_track_quat("-Z", "Y").to_euler()
    cam.data.lens = lens
    scene.render.filepath = os.path.join(OUT, name + ".jpg")
    bpy.ops.render.render(write_still=True)


only = set(argv[2:])
SHOTS = [
    ("banner", (-23, 5.5, 27), (1.5, 3.4, 2), 28, "food", 8 / 3),   # top of the README: hero_food without sky/grass
    ("hero_food", (-23, 5.5, 27), (1.5, 3.4, 2), 28, "food"),
    ("hero_goods", (24, 5, 26), (-1.5, 3.4, 2), 28, "goods"),
    ("back_lanes", (24, 10, -36), (-1, 1.5, -6), 28, "food"),
    ("inside_aisle", (0, 1.8, 10), (0, 2.4, -6), 22, "food"),
    ("inside_racks", (6, 3.2, 12), (-4, 2.2, -3), 22, "food"),
    ("workbench", (10, 1.9, 5), (14.5, 1.1, 2.5), 30, "food"),
]
for name, eye, target, lens, brand, *aspect in SHOTS:
    if not only or name in only:
        shoot(name, eye, target, lens, brand, *aspect)
print("README IMAGES DONE")
