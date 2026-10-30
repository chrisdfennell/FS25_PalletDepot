"""Renders preview images of build/depot.blend (all stock shown), for checking the model and for store images.

    blender --background build/depot.blend --python tools/render_preview.py -- <out_dir> [size]
"""
import math
import os
import sys

import bpy
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:]
OUT = argv[0]
SIZE = int(argv[1]) if len(argv) > 1 else 1200
os.makedirs(OUT, exist_ok=True)

for obj in bpy.data.objects:                 # show stock, hide non-rendering helpers and the lower LODs
    obj.hide_render = obj.get("i3D_nonRenderable", False) or obj.name in ("lod1", "lod2")
    if obj.name.startswith("stock"):
        obj.hide_render = False

scene = bpy.context.scene
scene.render.engine = "BLENDER_WORKBENCH"
scene.display.shading.light = "STUDIO"
scene.display.shading.color_type = "TEXTURE"
scene.display.shading.show_shadows = True
scene.display.shading.show_cavity = True
scene.render.resolution_x = SIZE
scene.render.resolution_y = SIZE * 9 // 16
scene.render.film_transparent = False
scene.world = scene.world or bpy.data.worlds.new("world")

cam = bpy.data.objects.new("previewCam", bpy.data.cameras.new("previewCam"))
scene.collection.objects.link(cam)
scene.camera = cam
cam.data.lens = 35


def shoot(name, eye_i3d, target_i3d):
    eye = Vector((eye_i3d[0], -eye_i3d[2], eye_i3d[1]))
    target = Vector((target_i3d[0], -target_i3d[2], target_i3d[1]))
    cam.location = eye
    cam.rotation_euler = (target - eye).to_track_quat("-Z", "Y").to_euler()
    scene.render.filepath = os.path.join(OUT, name + ".png")
    bpy.ops.render.render(write_still=True)


shoot("front", (-26, 14, 34), (0, 3, 4))
shoot("back", (24, 13, -38), (0, 2, -8))
shoot("inside", (6, 3.2, 12), (-4, 2.2, -3))
shoot("canopy", (2, 2.5, 20), (0, 5.5, 8))
shoot("aisle", (0, 1.8, 10), (0, 2.4, -6))            # from the pad through the open front to the back door
shoot("backdoor", (-9, 2.2, -13), (0, 1.0, -6.5))     # outside the back door: pallets
shoot("skip", (17, 4, -15), (10, 1, -8))              # back right corner: skip
shoot("corner", (5, 3, 3), (-13, 1, 5))               # inside front left corner: pallet stack, extinguisher
shoot("frontright", (18, 3, 13), (11.5, 0.6, 6.5))    # bench and bins outside the front right
shoot("backleft", (-9, 3, -13), (-12, 0.6, -7))         # IBC tank and barrels behind the hall
shoot("workbench", (8, 2.2, 4), (14.5, 1.2, 3))        # workbench and pallet jack inside
shoot("frontleft", (-8, 2.6, 14), (-12, 0.8, 7))        # front left outside: leaning pallet and stack
