"""Renders the shop images (512 x 512, transparent) for both buildings and the mod icon (256 x 256) from
build/depot.blend, then converts them to .dds with GIANTS' textureTool.

    blender --background build/depot.blend --python tools/render_store.py
"""
import math
import os
import subprocess
import sys

import bpy
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Vector

HERE = os.path.dirname(os.path.abspath(bpy.data.filepath))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import layout as L  # noqa: E402

TEXTURE_TOOL = r"C:\Program Files\GIANTS Software\GIANTS_Editor_10.0.14\tools\textureTool.exe"
SRC = os.path.join(ROOT, "src", "store")

for obj in bpy.data.objects:      # full LOD0 with every pallet, no helpers
    obj.hide_render = bool(obj.get("i3D_nonRenderable", False)) or obj.name in ("lod1", "lod2")
    if obj.name.startswith("stock"):
        obj.hide_render = False

scene = bpy.context.scene
scene.render.engine = "BLENDER_WORKBENCH"
shading = scene.display.shading
shading.light = "STUDIO"
shading.color_type = "TEXTURE"
shading.show_shadows = True
shading.shadow_intensity = 0.35
shading.show_cavity = True
scene.view_settings.view_transform = "Standard"

cam = bpy.data.objects.new("storeCam", bpy.data.cameras.new("storeCam"))
scene.collection.objects.link(cam)
scene.camera = cam
cam.data.lens = 50


def b3(p):
    return Vector((p[0], -p[2], p[1]))


# silhouette points: walls up to the eaves, ridge, canopy with sign (i3d coordinates)
_X, _Z = L.HALL_X + 0.4, L.HALL_Z + 0.5
CORNERS = ([b3((x, y, z)) for x in (-_X, _X) for y in (0.0, L.EAVE_Y) for z in (-_Z, _Z)]
           + [b3((x, L.RIDGE_Y + 0.2, 0.0)) for x in (-_X, _X)]
           + [b3((x, y, L.CANOPY_Z[1] + 0.1)) for x in L.CANOPY_X for y in (L.CANOPY_Y_TIP - 0.4, L.SIGN_Y[1])])


def frame(direction_i3d, margin):
    """Places the camera along direction (from the building) so the building fills the frame up to margin."""
    d = b3(direction_i3d).normalized()
    target = sum(CORNERS, Vector()) / len(CORNERS)
    for _ in range(6):
        lo, hi = 10.0, 400.0
        for _ in range(40):                       # distance at which the corners just fit
            mid = (lo + hi) / 2
            cam.location = target + d * mid
            cam.rotation_euler = (-d).to_track_quat("-Z", "Y").to_euler()
            bpy.context.view_layer.update()
            pts = [world_to_camera_view(scene, cam, c) for c in CORNERS]
            span = max(max(p.x for p in pts) - min(p.x for p in pts), max(p.y for p in pts) - min(p.y for p in pts))
            lo, hi = (lo, mid) if span < 1 - 2 * margin else (mid, hi)
        cx = (max(p.x for p in pts) + min(p.x for p in pts)) / 2 - 0.5
        cy = (max(p.y for p in pts) + min(p.y for p in pts)) / 2 - 0.5
        right = cam.matrix_world.to_3x3() @ Vector((1, 0, 0))
        up = cam.matrix_world.to_3x3() @ Vector((0, 1, 0))
        target = target + (right * cx + up * cy) * hi * 0.7   # re-centre the projected box


def set_brand(brand):
    for node in bpy.data.materials["depot_brand"].node_tree.nodes:
        if node.type == "TEX_IMAGE" and "_diffuse" in node.image.filepath:
            node.image.filepath = os.path.join(ROOT, "textures", "depot_brand_%s_diffuse.dds" % brand)
            node.image.reload()


def render(path, size, transparent):
    scene.render.resolution_x = scene.render.resolution_y = size
    scene.render.film_transparent = transparent
    scene.render.image_settings.color_mode = "RGBA" if transparent else "RGB"
    scene.render.filepath = path
    bpy.ops.render.render(write_still=True)


def convert(png, dds):
    r = subprocess.run([TEXTURE_TOOL, "-inputs", png, "-targetFile", dds, "-ignoreTimestamp", "-silent"],
                       capture_output=True, text=True)
    if r.returncode != 0 or not os.path.exists(dds):
        sys.exit("textureTool failed for %s:\n%s%s" % (png, r.stdout, r.stderr))


os.makedirs(SRC, exist_ok=True)
os.makedirs(os.path.join(ROOT, "store"), exist_ok=True)
frame((-0.55, 0.42, 0.72), 0.04)            # front-left, looking at the sign and the open front
for brand in L.BRANDS:
    set_brand(brand)
    png = os.path.join(SRC, "store_depot_%s.png" % brand)
    render(png, 512, True)
    convert(png, os.path.join(ROOT, "store", "store_depot_%s.dds" % brand))

set_brand("food")
scene.world = scene.world or bpy.data.worlds.new("world")
scene.world.color = (0.32, 0.42, 0.36)
shading.background_type = "WORLD"
frame((-0.55, 0.42, 0.72), 0.03)
png = os.path.join(SRC, "icon_palletDepot.png")
render(png, 256, False)
convert(png, os.path.join(ROOT, "icon_palletDepot.dds"))
print("STORE IMAGES DONE")
