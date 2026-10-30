"""Builds the Pallet Depot building in Blender and exports it with the GIANTS I3D exporter (FS25, 10.0.x).

    blender --background --factory-startup --python tools/build_warehouse.py -- [out.i3d]

Every position comes from tools/layout.py. Geometry in this file is written in i3d coordinates
(x along the front wall, y up, +z out of the loading front) and converted to Blender's z-up axes
(x, -z, y) only when an object is created; the exporter's "bake transforms" converts it back.

Headless export needs two workarounds, applied from here so GIANTS' files stay untouched:
  * dccBlender.isNodeVisible asks the 3D viewport, which background mode lacks. We replace it and read
    visibility from the custom property "i3d_hidden" (the exporter unhides everything before exporting).
  * The exporter swallows errors unless verbose is on, so verbose is on and its action log is printed.
"""
import importlib
import math
import os
import random
import sys

import addon_utils
import bpy
from mathutils import Matrix, Vector

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import layout as L  # noqa: E402

ROOT = os.path.dirname(HERE)
EXPORTER = "io_export_i3d_10_0_2"
GAME_DIR = "C:/Program Files (x86)/Steam/steamapps/common/Farming Simulator 25/"   # trailing slash: the
TEXTURES = os.path.join(ROOT, "textures")                                          # exporter appends to it
BUILDING_SHADER = "$data/shaders/buildingShader.xml"

PITCH = math.radians(L.ROOF_PITCH_DEG)
T = math.tan(PITCH)
ROOF_OFF = L.ROOF_THICK / math.cos(PITCH)       # vertical thickness of the roof sheets

# collision groups and masks as used by base-game placeables
COL_BUILDING = ("0x1034", "0xfffffbff")
COL_TIP = ("0x8", "0x1")
COL_PLAYER_TRIGGER = ("0x20000000", "0x100000")
COL_PALLET_TRIGGER = ("0x20000000", "0x10000")
COL_EXACT_FILL = ("0x40000000", "0x20000000")
COL_DOOR_TRIGGER = ("0x20000000", "0x110000")      # as base-game garage doors: player and vehicles

# The occluder flag must be flushed into the .shapes geometry by GIANTS Editor (load + save the i3d);
# the exporter cannot do it and the editor has no scriptable save, so an exported occluder only logs
# "needs to be marked as an occluder by the editor" on every load. Off until that step exists.
WITH_OCCLUDER = False


# --- materials --------------------------------------------------------------------------------------
# name: (diffuse, normal, specular, buildingShader, tile size in metres or None for atlas materials)
MATERIALS = {
    "depot_wall": ("depot_wall_diffuse", "depot_wall_normal", "depot_wall_specular", True, L.TILE["wall"]),
    "depot_roof": ("depot_roof_diffuse", "depot_roof_normal", "depot_roof_specular", True, L.TILE["roof"]),
    "depot_concrete": ("depot_concrete_diffuse", "depot_concrete_normal", "depot_concrete_specular", True,
                       L.TILE["concrete"]),
    "depot_window": ("depot_window_diffuse", "depot_window_normal", "depot_window_specular", True,
                     L.TILE["window"]),
    "depot_door": ("depot_door_diffuse", "depot_door_normal", "depot_door_specular", True, (1.0, 1.0)),
    "depot_paint": ("depot_paint_diffuse", None, "depot_paint_specular", True, None),
    "depot_brand": ("depot_brand_food_diffuse", None, "depot_brand_specular", True, None),
    "depot_stock": ("depot_stock_diffuse", None, "depot_stock_specular", True, None),
    "depot_decals": ("depot_decals_diffuse", None, "depot_decals_specular", False, None),
}


def P(name):
    """Painted part: a swatch of the paint atlas."""
    return ("depot_paint", L.PAINT_SWATCHES[name])


SIGN = ("depot_brand", L.BRAND_SIGN)
ACCENT = ("depot_brand", L.BRAND_ACCENT)


def make_materials():
    blend_dir = os.path.dirname(bpy.data.filepath)
    for name, (diffuse, normal, specular, building, _) in MATERIALS.items():
        mat = bpy.data.materials.new(name)
        mat.use_nodes = True
        nodes, links = mat.node_tree.nodes, mat.node_tree.links
        bsdf = nodes["Principled BSDF"]
        bsdf.inputs["Emission Color"].default_value = (0.0, 0.0, 0.0, 1.0)   # else exported as emissive white

        def image(tex):
            img = bpy.data.images.new(tex, 4, 4)
            img.source = "FILE"
            img.filepath = os.path.join(TEXTURES, tex + ".dds")
            node = nodes.new("ShaderNodeTexImage")
            node.image = img
            return node

        links.new(image(diffuse).outputs["Color"], bsdf.inputs["Base Color"])
        links.new(image(specular).outputs["Color"], bsdf.inputs["Roughness"])          # -> Glossmap
        if normal:
            nm = nodes.new("ShaderNodeNormalMap")
            links.new(image(normal).outputs["Color"], nm.inputs["Color"])
            links.new(nm.outputs["Normal"], bsdf.inputs["Normal"])
        if building:
            mat["customShader"] = BUILDING_SHADER
            mat["customParameter_dirtMossMix"] = "1.0 1.0"
            mat["customParameter_dirtMossSmoothness"] = "0.12 0.12"
            mat["customParameter_dirtMossTint"] = "0.0 0.0 0.8"
            mat["customTexture_mDirtDiffuse"] = "$data/maps/textures/shared/mapDirt_diffuse.png"
            mat["customTexture_mMossDiffuse"] = "$data/maps/textures/shared/mapMoss_diffuse.png"
            # the exporter resolves non-$ custom textures relative to the saved .blend
            mat["customTexture_mMaskMap"] = os.path.relpath(os.path.join(TEXTURES, "depot_mask.dds"), blend_dir)


# --- mesh building ----------------------------------------------------------------------------------
def to_blender(p):
    return (p[0], -p[2], p[1])


def newell(pts):
    n = Vector((0.0, 0.0, 0.0))
    for a, b in zip(pts, pts[1:] + pts[:1]):
        n.x += (a.y - b.y) * (a.z + b.z)
        n.y += (a.z - b.z) * (a.x + b.x)
        n.z += (a.x - b.x) * (a.y + b.y)
    return n.normalized() if n.length > 1e-12 else Vector((0.0, 1.0, 0.0))


def planar(p, n):
    """2D coordinates of p on the plane facing n, oriented as seen from outside (no mirroring)."""
    ax = max(range(3), key=lambda i: abs(n[i]))
    if ax == 1:
        return (p.x, -p.z) if n.y > 0 else (p.x, p.z)
    if ax == 0:
        return (-p.z, p.y) if n.x > 0 else (p.z, p.y)
    return (p.x, p.y) if n.z > 0 else (-p.x, p.y)


def mask_uv(p, n):
    """Second UV set: buildingShader reads dirt/moss here and only wets/snows faces with u > 0."""
    h = p.z if abs(n.x) > 0.7 else p.x
    u = 0.02 + 0.96 * min(1.0, max(0.0, (h + 16.0) / 32.0))
    v = min(0.998, max(0.002, p.y / 9.5))
    return (u, v)


class Mesh:
    """Polygon soup in i3d coordinates with two UV sets and a material per polygon.

    A material is a name from MATERIALS (tiling, planar-projected UVs) or a (name, region) tuple
    (atlas: each polygon is fitted into the region).
    """

    def __init__(self):
        self.polys = []          # (points, uv0, uv1, material name, outdoor)

    def poly(self, pts, mat, normal=None, uv=None, outdoor=True):
        pts = [Vector(p) for p in pts]
        n = newell(pts)
        if normal is not None and n.dot(Vector(normal)) < 0:
            pts.reverse()
            uv = list(reversed(uv)) if uv else uv
            n = -n
        name, region = (mat, None) if isinstance(mat, str) or mat is None else mat
        if uv is None and name is None:          # physics only, no material
            uv = [(0.0, 0.0)] * len(pts)
        elif uv is None:
            flat = [planar(p, n) for p in pts]
            if region is None:
                tu, tv = MATERIALS[name][4]
                uv = [(a / tu, b / tv) for a, b in flat]
            else:
                uv = fit(flat, region)
        uv1 = [mask_uv(p, n) for p in pts] if outdoor else [(0.0, 0.5)] * len(pts)
        self.polys.append((pts, uv, uv1, name, outdoor))

    def add_transformed(self, other, transform):
        """Copies other's polygons through transform (Vector -> Vector, a rotation plus offset)."""
        for pts, uv, uv1, name, outdoor in other.polys:
            moved = [transform(p) for p in pts]
            n = newell(moved)
            self.polys.append((moved, uv, [mask_uv(p, n) for p in moved] if outdoor else uv1, name, outdoor))

    def box(self, lo, hi, mat, outdoor=True, skip=()):
        (x0, y0, z0), (x1, y1, z1) = lo, hi
        faces = {
            "+x": ([(x1, y0, z0), (x1, y1, z0), (x1, y1, z1), (x1, y0, z1)], (1, 0, 0)),
            "-x": ([(x0, y0, z0), (x0, y1, z0), (x0, y1, z1), (x0, y0, z1)], (-1, 0, 0)),
            "+y": ([(x0, y1, z0), (x1, y1, z0), (x1, y1, z1), (x0, y1, z1)], (0, 1, 0)),
            "-y": ([(x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1)], (0, -1, 0)),
            "+z": ([(x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)], (0, 0, 1)),
            "-z": ([(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0)], (0, 0, -1)),
        }
        for key, (pts, n) in faces.items():
            if key not in skip:
                self.poly(pts, mat, n, outdoor=outdoor)

    def beam(self, a, b, w, h, mat, outdoor=False, up=(0, 1, 0)):
        """Rectangular bar from a to b (w across, h in the 'up' plane)."""
        a, b = Vector(a), Vector(b)
        d = (b - a).normalized()
        side = d.cross(Vector(up))
        if side.length < 1e-6:
            side = d.cross(Vector((1, 0, 0)))
        side = side.normalized() * (w / 2)
        u = side.normalized().cross(d).normalized() * (h / 2)
        ring = [side + u, -side + u, -side - u, side - u]
        ca, cb = [a + r for r in ring], [b + r for r in ring]
        for i in range(4):
            j = (i + 1) % 4
            mid = (ring[i] + ring[j])
            self.poly([ca[i], ca[j], cb[j], cb[i]], mat, mid, outdoor=outdoor)
        self.poly(ca, mat, -d, outdoor=outdoor)
        self.poly(cb, mat, d, outdoor=outdoor)

    def cylinder(self, cx, y0, cz, radius, height, mat, outdoor=True, segments=14, top_mat=None):
        """Upright cylinder with a top cap (the bottom stands on something)."""
        ring = [(cx + radius * math.cos(2 * math.pi * i / segments), cz + radius * math.sin(2 * math.pi * i / segments))
                for i in range(segments)]
        for i in range(segments):
            (xa, za), (xb, zb) = ring[i], ring[(i + 1) % segments]
            mid = Vector(((xa + xb) / 2 - cx, 0, (za + zb) / 2 - cz))
            self.poly([(xa, y0, za), (xb, y0, zb), (xb, y0 + height, zb), (xa, y0 + height, za)], mat, mid, outdoor=outdoor)
        self.poly([(x, y0 + height, z) for x, z in ring], top_mat or mat, (0, 1, 0), outdoor=outdoor)

    def lathe(self, cx, cz, profile, mat, outdoor=True, segments=16):
        """Round body around the vertical axis at (cx, cz). profile: [(y, radius)] from the bottom up, closed
        at the top. mat: a material, or a function (band index, segment centre angle) -> material."""
        def at(r, y, a):
            return (cx + r * math.cos(a), y, cz + r * math.sin(a))
        for k, ((ya, ra), (yb, rb)) in enumerate(zip(profile, profile[1:])):
            for i in range(segments):
                a0, a1 = 2 * math.pi * i / segments, 2 * math.pi * (i + 1) / segments
                am = (a0 + a1) / 2
                pts = [at(ra, ya, a0), at(ra, ya, a1), at(rb, yb, a1), at(rb, yb, a0)]
                if ra == 0.0:
                    pts = pts[1:]
                elif rb == 0.0:
                    pts = pts[:3]
                normal = (math.cos(am) * (yb - ya), ra - rb, math.sin(am) * (yb - ya))
                self.poly(pts, mat(k, am) if callable(mat) else mat, normal, outdoor=outdoor)
        y, r = profile[-1]
        if r > 0.0:
            top = [at(r, y, 2 * math.pi * i / segments) for i in range(segments)]
            self.poly(top, mat(len(profile) - 1, 0.0) if callable(mat) else mat, (0, 1, 0), outdoor=outdoor)

    def wheel(self, cx, cy, cz, radius, width, tyre, hub, outdoor=False, segments=12):
        """Wheel turning about the z axis: tyre tread and sidewalls, hub discs on both sides."""
        w, hr = width / 2, radius * 0.55
        tmp = Mesh()
        tmp.lathe(0.0, 0.0, [(-w, 0.0), (-w, hr), (-w, radius), (w, radius), (w, hr), (w, 0.0)],
                  lambda band, _: hub if band in (0, 4) else tyre, outdoor, segments)
        rot = Matrix.Rotation(math.radians(90.0), 3, "X")       # lathe axis (y) -> z
        offset = Vector((cx, cy, cz))
        self.add_transformed(tmp, lambda p: rot @ p + offset)

    def hexa(self, corners, mat, outdoor=True):
        """Convex block from 8 corners: the bottom four in order, then the top four above them."""
        centre = sum((Vector(c) for c in corners), Vector()) / 8
        for face in ((0, 1, 2, 3), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)):
            pts = [corners[i] for i in face]
            mid = sum((Vector(p) for p in pts), Vector()) / 4
            self.poly(pts, mat, mid - centre, outdoor=outdoor)

    def to_object(self, name, parent, location=(0.0, 0.0, 0.0)):
        loc = Vector(location)
        verts, faces = [], []
        for pts, _, _, _, _ in self.polys:
            faces.append(list(range(len(verts), len(verts) + len(pts))))
            verts += [to_blender(p - loc) for p in pts]
        me = bpy.data.meshes.new(name)
        me.from_pydata(verts, [], faces)
        mats = []
        for _, _, _, m, _ in self.polys:
            if m not in mats:
                mats.append(m)
        for m in mats:
            me.materials.append(bpy.data.materials.get(m) if m else None)
        uv0, uv1 = me.uv_layers.new(name="uv0"), me.uv_layers.new(name="uv1")
        for poly, (_, a, b, m, _) in zip(me.polygons, self.polys):
            poly.material_index = mats.index(m)
            for li, ua, ub in zip(poly.loop_indices, a, b):
                uv0.data[li].uv = ua
                uv1.data[li].uv = ub
        me.validate()
        me.update()
        return add_object(name, me, parent, location)


def fit(flat, region, inset=0.03):
    u0, v0, u1, v1 = region
    du, dv = (u1 - u0) * inset, (v1 - v0) * inset
    xs, ys = [p[0] for p in flat], [p[1] for p in flat]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    sx, sy = (x1 - x0) or 1.0, (y1 - y0) or 1.0
    return [(u0 + du + (x - x0) / sx * (u1 - u0 - 2 * du), v0 + dv + (y - y0) / sy * (v1 - v0 - 2 * dv))
            for x, y in flat]


# --- scene nodes ------------------------------------------------------------------------------------
def add_object(name, data, parent, location=(0.0, 0.0, 0.0), rot_y=0.0):
    obj = bpy.data.objects.new(name, data)
    assert obj.name == name, "duplicate node name " + name
    bpy.context.scene.collection.objects.link(obj)
    obj.parent = parent
    obj.location = to_blender(location)
    obj.rotation_euler = (0.0, 0.0, math.radians(rot_y))   # i3d y rotation == Blender z rotation
    return obj


def node(name, parent=None, location=(0.0, 0.0, 0.0), rot_y=0.0):
    """Empty -> i3d TransformGroup."""
    obj = add_object(name, None, parent, location, rot_y)
    obj.empty_display_size = 0.3
    return obj


def attrs(obj, **kw):
    for k, v in kw.items():
        obj["i3D_" + k] = v
    return obj


def box_shape(name, parent, center, size, **kw):
    """Box shape centred on its own node (triggers, collisions)."""
    m = Mesh()
    hx, hy, hz = (s / 2 for s in size)
    m.box((-hx, -hy, -hz), (hx, hy, hz), None, outdoor=False)
    obj = m.to_object(name, parent)
    obj.location = to_blender(center)
    return attrs(obj, castsShadows=False, receiveShadows=False, **kw)


def trigger(name, parent, center, size, group_mask, kinematic=False):
    kind = dict(kinematic=True, compound=True) if kinematic else dict(static=True)
    return box_shape(name, parent, center, size, trigger=True, nonRenderable=True,
                     collisionFilterGroup=group_mask[0], collisionFilterMask=group_mask[1], **kind)


def area(parent, prefix, index, x, z, second, third=None):
    """Placement area as Start node with offset children (base-game convention)."""
    start = node("%sStart%02d" % (prefix, index), parent, (x[0], 0.0, z[0]))
    if third is None:      # Start/End box (test, tip occlusion)
        node("%sEnd%02d" % (prefix, index), start, second)
    else:                  # Start/Width/Height rectangle (clear, level, paint, indoor)
        node("%sWidth%02d" % (prefix, index), start, second)
        node("%sHeight%02d" % (prefix, index), start, third)
    return start


# --- building geometry ------------------------------------------------------------------------------
def roof_under(z):
    """Underside of the roof sheets above position z."""
    return L.EAVE_Y + (L.HALL_Z - abs(z)) * T


IN = L.HALL_Z - L.WALL_THICK
WALLS = {   # outer face plane, outward normal, axis along the wall, extent along the wall
    "front": dict(n=(0, 0, 1), axis="x", plane=L.HALL_Z, s=(-L.HALL_X, L.HALL_X)),
    "back": dict(n=(0, 0, -1), axis="x", plane=-L.HALL_Z, s=(-L.HALL_X, L.HALL_X)),
    "left": dict(n=(-1, 0, 0), axis="z", plane=-L.HALL_X, s=(-IN, IN)),
    "right": dict(n=(1, 0, 0), axis="z", plane=L.HALL_X, s=(-IN, IN)),
}


def wpt(wall, s, y, d=0.0):
    """Point on a wall: s along it, y up, d outwards from the outer face."""
    w = WALLS[wall]
    if w["axis"] == "x":
        return (s, y, w["plane"] + w["n"][2] * d)
    return (w["plane"] + w["n"][0] * d, y, s)


def wbox(m, wall, s0, s1, y0, y1, d0, d1, mat, outdoor=True, skip=()):
    a, b = Vector(wpt(wall, s0, y0, d0)), Vector(wpt(wall, s1, y1, d1))
    lo = tuple(min(a[i], b[i]) for i in range(3))
    hi = tuple(max(a[i], b[i]) for i in range(3))
    m.box(lo, hi, mat, outdoor, skip)


def wdir(wall):
    return (1, 0, 0) if WALLS[wall]["axis"] == "x" else (0, 0, 1)


def wskip(wall, *names):
    """Box face keys on a wall: 'out', 'in', 's0', 's1', 'top', 'bottom'."""
    w = WALLS[wall]
    ax = w["axis"]
    sign = (w["n"][2] if ax == "x" else w["n"][0])
    nrm = "z" if ax == "x" else "x"
    keys = {"out": ("+" if sign > 0 else "-") + nrm, "in": ("-" if sign > 0 else "+") + nrm,
            "s0": "-" + ax, "s1": "+" + ax, "top": "+y", "bottom": "-y"}
    return tuple(keys[k] for k in names)


def openings(wall, detail):
    ops = []
    if wall == "front":
        ops.append((-L.FRONT_OPEN_X, L.FRONT_OPEN_X, 0.0, L.FRONT_OPEN_Y, "open"))
    if detail < 2:
        ops += [(c - w / 2, c + w / 2, 0.0, h, "door") for wl, c, w, h in L.DOORS if wl == wall]
        ops += [(c - w / 2, c + w / 2, y, y + h, "window") for wl, c, y, w, h in L.WINDOWS if wl == wall]
    return ops


def build_walls(m, detail):
    for wall, w in WALLS.items():
        n = Vector(w["n"])
        s0, s1 = w["s"]
        ops = openings(wall, detail)
        ss = sorted({s0, s1} | {o[0] for o in ops} | {o[1] for o in ops})
        ys = sorted({L.PLINTH_Y, L.EAVE_Y} | {max(o[2], L.PLINTH_Y) for o in ops} | {o[3] for o in ops})
        for a, b in zip(ss, ss[1:]):
            for c, d in zip(ys, ys[1:]):
                if any(o[0] < (a + b) / 2 < o[1] and o[2] < (c + d) / 2 < o[3] for o in ops):
                    continue
                quad = [(a, c), (b, c), (b, d), (a, d)]
                m.poly([wpt(wall, s, y) for s, y in quad], "depot_wall", n)
                # inside, the cladding runs down to the slab (outside, the plinth covers the bottom)
                inner = [(s, L.FLOOR_Y if y == L.PLINTH_Y else y) for s, y in quad]
                m.poly([wpt(wall, s, y, -L.WALL_THICK) for s, y in inner], "depot_wall", -n, outdoor=False)
        if w["axis"] == "z":                      # gable triangles up to the roof
            for tri in ([(s0, L.EAVE_Y), (0.0, L.EAVE_Y), (0.0, roof_under(0.0))],
                        [(0.0, L.EAVE_Y), (s1, L.EAVE_Y), (0.0, roof_under(0.0))]):
                tri = [(s, y if y <= L.EAVE_Y else roof_under(s)) for s, y in tri]
                tri = [(s, roof_under(s) if s in (s0, s1) and y > L.EAVE_Y else y) for s, y in tri]
                m.poly([wpt(wall, s, y) for s, y in tri], "depot_wall", n)
                m.poly([wpt(wall, s, y, -L.WALL_THICK) for s, y in tri], "depot_wall", -n, outdoor=False)
        else:                                     # wall ends at the corners
            for s, sgn in ((s0, -1), (s1, 1)):
                pts = [wpt(wall, s, L.PLINTH_Y, 0), wpt(wall, s, L.PLINTH_Y, -L.WALL_THICK),
                       wpt(wall, s, L.EAVE_Y, -L.WALL_THICK), wpt(wall, s, L.EAVE_Y, 0)]
                m.poly(pts, "depot_wall", (sgn, 0, 0))
        if detail < 2:                            # reveals around the openings
            sd = Vector(wdir(wall))
            for o0, o1, y0, y1, kind in ops:
                yb = max(y0, L.PLINTH_Y)
                for s, nn in ((o0, sd), (o1, -sd)):
                    m.poly([wpt(wall, s, yb, 0), wpt(wall, s, y1, 0), wpt(wall, s, y1, -L.WALL_THICK),
                            wpt(wall, s, yb, -L.WALL_THICK)], P("trim"), nn)
                m.poly([wpt(wall, o0, y1, 0), wpt(wall, o1, y1, 0), wpt(wall, o1, y1, -L.WALL_THICK),
                        wpt(wall, o0, y1, -L.WALL_THICK)], P("trim"), (0, -1, 0))
                if y0 > L.PLINTH_Y:
                    m.poly([wpt(wall, o0, y0, 0), wpt(wall, o1, y0, 0), wpt(wall, o1, y0, -L.WALL_THICK),
                            wpt(wall, o0, y0, -L.WALL_THICK)], P("trim"), (0, 1, 0))
        build_plinth_and_band(m, wall, detail)


def build_plinth_and_band(m, wall, detail):
    w = WALLS[wall]
    s0, s1 = w["s"]
    ext = 0.03 if w["axis"] == "x" else 0.0      # front/back strips cover the corners
    floor_ops = sorted((o[0], o[1]) for o in openings(wall, detail) if o[2] == 0.0)
    cuts, start = [], s0 - ext
    for a, b in floor_ops:
        cuts.append((start, a))
        start = b
    cuts.append((start, s1 + ext))
    for a, b in cuts:
        skip = wskip(wall, "in", "bottom")
        if a == s0 - ext and ext == 0.0:
            skip += wskip(wall, "s0")
        if b == s1 + ext and ext == 0.0:
            skip += wskip(wall, "s1")
        wbox(m, wall, a, b, 0.0, L.PLINTH_Y, -L.WALL_THICK, 0.03, "depot_concrete", skip=skip)
    by0, by1 = L.ACCENT_BAND_Y
    e = 0.025 if w["axis"] == "x" else 0.0
    wbox(m, wall, s0 - e, s1 + e, by0, by1, 0.0, 0.025, ACCENT, skip=wskip(wall, "in"))


def build_corners(m):
    for sx in (-1, 1):
        for sz in (-1, 1):
            x, z = sx * L.HALL_X, sz * L.HALL_Z
            m.box((min(x, x - sx * 0.2), L.PLINTH_Y, min(z, z + sz * 0.02)),
                  (max(x, x - sx * 0.2), L.EAVE_Y, max(z, z + sz * 0.02)), P("trim"))
            m.box((min(x, x + sx * 0.02), L.PLINTH_Y, min(z, z - sz * 0.2)),
                  (max(x, x + sx * 0.02), L.EAVE_Y, max(z, z - sz * 0.2)), P("trim"))


def build_floor(m):
    m.box((-L.HALL_X, -0.3, -L.HALL_Z), (L.HALL_X, L.FLOOR_Y, L.HALL_Z), "depot_concrete", outdoor=False,
          skip=("-y", "-x", "+x", "-z", "+z"))
    m.poly([(-L.FRONT_OPEN_X, -0.05, L.HALL_Z), (L.FRONT_OPEN_X, -0.05, L.HALL_Z),
            (L.FRONT_OPEN_X, L.FLOOR_Y, L.HALL_Z), (-L.FRONT_OPEN_X, L.FLOOR_Y, L.HALL_Z)],
           "depot_concrete", (0, 0, 1))


def build_roof(m, detail):
    xe, ze = L.HALL_X + L.GABLE_OVERHANG, L.HALL_Z + L.EAVE_OVERHANG
    ye, yr = roof_under(ze), roof_under(0.0)
    for s in (1, -1):
        up = (0, 1, s * T)
        m.poly([(-xe, ye + ROOF_OFF, s * ze), (xe, ye + ROOF_OFF, s * ze), (xe, yr + ROOF_OFF, 0),
                (-xe, yr + ROOF_OFF, 0)], "depot_roof", up)
        m.poly([(-xe, ye, s * ze), (xe, ye, s * ze), (xe, yr, 0), (-xe, yr, 0)], "depot_roof",
               (0, -1, -s * T), outdoor=False)
        m.poly([(-xe, ye, s * ze), (xe, ye, s * ze), (xe, ye + ROOF_OFF, s * ze), (-xe, ye + ROOF_OFF, s * ze)],
               P("trim"), (0, 0, s))
        for x in (-xe, xe):
            m.poly([(x, ye, s * ze), (x, ye + ROOF_OFF, s * ze), (x, yr + ROOF_OFF, 0), (x, yr, 0)],
                   P("trim"), (x, 0, 0))
        if detail < 2:                            # ridge cap
            m.poly([(-xe, roof_under(0.25) + ROOF_OFF + 0.01, s * 0.25),
                    (xe, roof_under(0.25) + ROOF_OFF + 0.01, s * 0.25),
                    (xe, yr + ROOF_OFF + 0.05, 0), (-xe, yr + ROOF_OFF + 0.05, 0)], P("galv"), up)
            if detail == 0:
                for x in (-xe, xe):
                    m.poly([(x, roof_under(0.25) + ROOF_OFF + 0.01, s * 0.25), (x, yr + ROOF_OFF + 0.05, 0),
                            (x, yr + ROOF_OFF, 0), (x, roof_under(0.25) + ROOF_OFF, s * 0.25)], P("galv"), (x, 0, 0))


def build_gutters(m, detail):
    xe, ze = L.HALL_X + L.GABLE_OVERHANG, L.HALL_Z + L.EAVE_OVERHANG
    ye = roof_under(ze)
    for s in (1, -1):
        z0, z1 = sorted((s * (ze - 0.04), s * (ze + 0.14)))
        m.box((-xe, ye - 0.14, z0), (xe, ye - 0.01, z1), P("galv"))
        if detail > 0:
            continue
        for x in (-(L.HALL_X - 0.35), L.HALL_X - 0.35):          # down pipes with swan neck and shoe
            zp = s * (L.HALL_Z + 0.09)
            m.box((x - 0.05, 0.12, zp - 0.05), (x + 0.05, ye - 0.55, zp + 0.05), P("galv"))
            m.beam((x, ye - 0.58, zp), (x, ye - 0.1, s * (ze + 0.05)), 0.1, 0.1, P("galv"), True)
            m.beam((x, 0.3, zp), (x, 0.08, zp + s * 0.25), 0.1, 0.1, P("galv"), True)
            for y in (1.5, 3.5, 5.5):                             # brackets
                m.box((x - 0.07, y, min(zp, s * L.HALL_Z)), (x + 0.07, y + 0.04, max(zp, s * L.HALL_Z)),
                      P("galv"))


def build_frame(m, detail):
    zc = L.HALL_Z - L.COLUMN_INSET
    h = L.COLUMN / 2
    for fx in L.FRAME_XS:
        x = max(-L.HALL_X + L.COLUMN_INSET, min(L.HALL_X - L.COLUMN_INSET, fx))
        sides = [-1] + ([1] if abs(fx) >= L.FRONT_OPEN_X else [])
        for s in sides:
            z = s * zc
            m.box((x - h, L.FLOOR_Y, z - h), (x + h, roof_under(z) - 0.05, z + h), P("frame"), outdoor=False)
        if detail > 1:
            continue
        for s in (1, -1):                         # rafters, top flush with the roof sheets
            z = s * (L.HALL_Z - L.WALL_THICK)
            m.beam((x, roof_under(z) - 0.2, z), (x, roof_under(0.0) - 0.2, 0.0), 0.2, 0.4, P("frame"))
    if detail > 0:
        return
    # lintel behind the fascia over the loading front, eave struts, purlins
    m.box((-L.FRONT_OPEN_X - 0.2, L.FRONT_OPEN_Y, IN - 0.4), (L.FRONT_OPEN_X + 0.2, L.EAVE_Y - 0.05, IN),
          P("frame"), outdoor=False, skip=("+z",))
    for s in (1, -1):
        z0, z1 = sorted((s * (IN - 0.3), s * IN))
        m.box((-L.HALL_X + L.WALL_THICK, L.EAVE_Y - 0.3, z0), (L.HALL_X - L.WALL_THICK, L.EAVE_Y - 0.02, z1),
              P("frame"), outdoor=False)
        for zp in (1.2, 3.0, 4.8):
            z = s * zp
            m.box((-L.HALL_X + L.WALL_THICK, roof_under(z) - 0.17, z - 0.04),
                  (L.HALL_X - L.WALL_THICK, roof_under(z) - 0.01, z + 0.04), P("galv"), outdoor=False)
        # roof bracing in the end bays
        for xa, xb in ((-L.HALL_X + 0.3, -9.0), (9.0, L.HALL_X - 0.3)):
            za, zb = s * 1.2, s * 4.8
            m.beam((xa, roof_under(za) - 0.25, za), (xb, roof_under(zb) - 0.25, zb), 0.03, 0.03, P("galv"))
            m.beam((xa, roof_under(zb) - 0.25, zb), (xb, roof_under(za) - 0.25, za), 0.03, 0.03, P("galv"))


def build_canopy(m, detail):
    x0, x1 = L.CANOPY_X
    z0, z1 = L.CANOPY_Z
    yw, yt, th = L.CANOPY_Y_WALL, L.CANOPY_Y_TIP, L.CANOPY_THICK
    m.poly([(x0, yw, z0), (x1, yw, z0), (x1, yt, z1), (x0, yt, z1)], "depot_roof", (0, 1, 0))
    m.poly([(x0, yw - th, z0), (x1, yw - th, z0), (x1, yt - th, z1), (x0, yt - th, z1)], P("trim"), (0, -1, 0),
           outdoor=False)
    m.poly([(x0, yt - th, z1), (x1, yt - th, z1), (x1, yt, z1), (x0, yt, z1)], P("trim"), (0, 0, 1))
    for x, sgn in ((x0, -1), (x1, 1)):
        m.poly([(x, yw - th, z0), (x, yw, z0), (x, yt, z1), (x, yt - th, z1)], P("trim"), (sgn, 0, 0))
    # fascia board at the tip, the FOOD / GOODS sign stands on it
    m.box((x0 - 0.05, yt - th - 0.2, z1 - 0.02), (x1 + 0.05, L.SIGN_Y[0], z1 + 0.06), P("frame"))
    sx0, sx1 = L.SIGN_X
    sy0, sy1 = L.SIGN_Y
    m.poly([(sx0, sy0, z1 + 0.06), (sx1, sy0, z1 + 0.06), (sx1, sy1, z1 + 0.06), (sx0, sy1, z1 + 0.06)],
           SIGN, (0, 0, 1))
    m.box((sx0 - 0.04, sy0, z1 - 0.06), (sx1 + 0.04, sy1 + 0.04, z1 + 0.06), P("frame"), skip=("+z", "-y"))
    if detail > 1:
        return
    for x in L.CANOPY_BEAM_XS:                    # cantilever beams under the canopy and tie rods above
        xb = max(x0 + 0.1, min(x1 - 0.1, x))
        m.poly([(xb, yw - th, z0), (xb, yw - th - 0.2, z0), (xb, yt - th - 0.12, z1 - 0.02), (xb, yt - th, z1 - 0.02)],
               P("frame"), (1, 0, 0))
        if detail == 0:
            m.beam((xb, yw - th - 0.1, z0), (xb, yt - th - 0.06, z1 - 0.02), 0.16, 0.12, P("frame"))
            m.beam((xb, 6.35, L.HALL_Z + 0.03), (xb, yt + 0.08, z1 - 0.3), 0.04, 0.04, P("galv"), True)
    if detail == 0:
        for x in (sx0 + 0.6, sx1 - 0.6):          # sign struts
            m.beam((x, sy1 - 0.1, z1 - 0.07), (x, yt + 0.02, z1 - 0.9), 0.06, 0.06, P("frame"), True)
        for x, y, z in L.POINT_LIGHTS:            # lamp housings
            top = yw - th - (z - z0) / (z1 - z0) * (yw - yt) if z > L.HALL_Z else roof_under(z) - 0.2
            m.box((x - 0.4, y + 0.02, z - 0.12), (x + 0.4, y + 0.1, z + 0.12), P("trim"), outdoor=False)
            if z <= L.HALL_Z:
                m.box((x - 0.015, y + 0.1, z - 0.015), (x + 0.015, top, z + 0.015), P("galv"), outdoor=False)


def build_doors(m, detail):
    for wall, c, w, h in L.DOORS:
        n = Vector(WALLS[wall]["n"])
        a, b = c - w / 2, c + w / 2
        if detail == 2:                           # flat stand-in on the closed wall
            m.poly([wpt(wall, a, L.PLINTH_Y, 0.005), wpt(wall, b, L.PLINTH_Y, 0.005), wpt(wall, b, h, 0.005),
                    wpt(wall, a, h, 0.005)], "depot_door", n)
            continue
        # the curtain and its bottom bar move, see build_door_parts
        wbox(m, wall, a - 0.14, a, 0.0, h + 0.14, 0.0, 0.05, P("doorFrame"), skip=wskip(wall, "in"))
        wbox(m, wall, b, b + 0.14, 0.0, h + 0.14, 0.0, 0.05, P("doorFrame"), skip=wskip(wall, "in"))
        wbox(m, wall, a, b, h, h + 0.14, 0.0, 0.05, P("doorFrame"), skip=wskip(wall, "in"))
        if detail > 0:
            continue
        # coil box and guides inside
        wbox(m, wall, a - 0.15, b + 0.15, h + 0.05, h + 0.6, -L.WALL_THICK - 0.55, -L.WALL_THICK,
             P("doorFrame"), outdoor=False, skip=wskip(wall, "out"))
        for s0, s1 in ((a - 0.12, a + 0.02), (b - 0.02, b + 0.12)):
            wbox(m, wall, s0, s1, L.FLOOR_Y, h + 0.05, -L.WALL_THICK - 0.12, -L.WALL_THICK,
                 P("doorFrame"), outdoor=False, skip=wskip(wall, "out", "bottom"))
        for s in (a - 0.45, b + 0.45):            # yellow collision posts outside
            wbox(m, wall, s - 0.08, s + 0.08, 0.0, 1.2, 0.35, 0.51, P("yellow"), skip=wskip(wall, "bottom"))


def build_door_parts(parent):
    """Moving parts of the roller doors, opened by the placeable's animatedObjects (gen_placeables.py).

    Per door a group at the bottom centre of the opening, on the wall's middle plane, with:
      <name>Curtain  pivot at the top of the opening; scaled down in y, it rolls up into the coil box
      <name>Bar      bottom bar, rises with the curtain's lower edge
      <name>Col1..n  kinematic collision slices, each moves up until all stack above the opening
      <name>Trigger  player trigger on both sides of the door
    """
    doors = node("doors", parent)
    for wall, c, w, h in L.DOORS:
        name = L.door_name(wall)
        n = Vector(WALLS[wall]["n"])
        a, b = c - w / 2, c + w / 2
        d = -L.WALL_THICK / 2
        base = Vector(wpt(wall, c, 0.0, d))
        group = node(name, doors, base)

        def part(m, suffix, local):
            obj = m.to_object(name + suffix, group, base + Vector(local))
            obj.location = to_blender(local)
            return obj

        m = Mesh()
        curtain = [wpt(wall, a, 0.0, d), wpt(wall, b, 0.0, d), wpt(wall, b, h, d), wpt(wall, a, h, d)]
        m.poly(curtain, "depot_door", n)
        m.poly(curtain, "depot_door", -n, outdoor=False)
        attrs(part(m, "Curtain", (0.0, h, 0.0)), collision=False, clipDistance=250.0)

        m = Mesh()
        wbox(m, wall, a, b, 0.0, 0.05, d - 0.02, d + 0.02, P("rubber"), outdoor=False)
        attrs(part(m, "Bar", (0.0, 0.0, 0.0)), collision=False, clipDistance=120.0)

        step = h / L.DOOR_SLICES
        for i in range(L.DOOR_SLICES):
            m = Mesh()
            wbox(m, wall, a, b, i * step, (i + 1) * step, -0.2, 0.0, None, outdoor=False)
            attrs(part(m, "Col%d" % (i + 1), (0.0, i * step, 0.0)), kinematic=True, nonRenderable=True,
                  castsShadows=False, receiveShadows=False,
                  collisionFilterGroup=COL_BUILDING[0], collisionFilterMask=COL_BUILDING[1])

        along, across = w + 1.0, 6.0
        size = (along, 3.0, across) if WALLS[wall]["axis"] == "x" else (across, 3.0, along)
        trigger(name + "Trigger", group, (0.0, 1.5, 0.0), size, COL_DOOR_TRIGGER)


def build_windows(m, detail):
    for wall, c, y, w, h in L.WINDOWS:
        n = Vector(WALLS[wall]["n"])
        a, b = c - w / 2, c + w / 2
        if detail == 2:
            m.poly([wpt(wall, a, y, 0.005), wpt(wall, b, y, 0.005), wpt(wall, b, y + h, 0.005),
                    wpt(wall, a, y + h, 0.005)], "depot_window", n)
            continue
        d = -L.WALL_THICK / 2
        pane = [wpt(wall, a, y, d), wpt(wall, b, y, d), wpt(wall, b, y + h, d), wpt(wall, a, y + h, d)]
        m.poly(pane, "depot_window", n)
        m.poly(pane, "depot_window", -n, outdoor=False)
        wbox(m, wall, a - 0.06, b + 0.06, y - 0.05, y, 0.0, 0.07, P("galv"), skip=wskip(wall, "in"))
        if detail > 0:
            continue
        for s0, s1, y0, y1 in ((a - 0.06, a, y, y + h + 0.06), (b, b + 0.06, y, y + h + 0.06),
                               (a, b, y + h, y + h + 0.06)):
            wbox(m, wall, s0, s1, y0, y1, 0.0, 0.03, P("trim"), skip=wskip(wall, "in"))


def build_racks(m, detail):
    post = 0.08
    for _, front_z, segments in L.RACK_ROWS:
        zf, zb = front_z, front_z - L.RACK_DEPTH
        for x0, bays in segments:
            x1 = x0 + bays * L.RACK_BAY
            for k in range(bays + 1):
                x = x0 + k * L.RACK_BAY
                if detail == 1:
                    m.box((x - post / 2, L.FLOOR_Y, zb), (x + post / 2, L.RACK_HEIGHT, zf), P("rackPost"),
                          outdoor=False, skip=("-y",))
                    continue
                for z in (zf - post / 2, zb + post / 2):
                    m.box((x - post / 2, L.FLOOR_Y, z - post / 2), (x + post / 2, L.RACK_HEIGHT, z + post / 2),
                          P("rackPost"), outdoor=False, skip=("-y",))
                ys = [0.25, 1.4, 2.6, 3.9, L.RACK_HEIGHT - 0.2]
                for i, yb in enumerate(ys):        # bracing ladder between front and back posts
                    m.beam((x, yb, zf - post), (x, yb, zb + post), 0.03, 0.04, P("rackPost"))
                    if i + 1 < len(ys):
                        za, zc = (zf - post, zb + post) if i % 2 == 0 else (zb + post, zf - post)
                        m.beam((x, yb, za), (x, ys[i + 1], zc), 0.03, 0.03, P("rackPost"))
            for y in L.RACK_LEVELS_Y[1:] + [L.RACK_HEIGHT]:
                for za, zc in ((zf - 0.05, zf), (zb, zb + 0.05)):
                    if detail == 1:
                        m.box((x0, y - 0.12, za), (x1, y, zc), P("rackBeam"), outdoor=False)
                        continue
                    for k in range(bays):
                        bx = x0 + k * L.RACK_BAY
                        m.box((bx + post / 2, y - 0.12, za), (bx + L.RACK_BAY - post / 2, y, zc), P("rackBeam"),
                              outdoor=False)


# --- finishing details -----------------------------------------------------------------------------
PALLET_H = 0.144
WOOD = ("depot_stock", L.STOCK_REGIONS["pallet"])


def pallet(m, cx, y0, cz, along_x, outdoor):
    """Empty 1.2 x 1.0 m pallet like a Euro pallet: five top boards on three cross boards, nine blocks,
    three bottom boards."""
    def box(l0, l1, y_0, y_1, w0, w1):
        if along_x:
            m.box((cx + l0, y0 + y_0, cz + w0), (cx + l1, y0 + y_1, cz + w1), WOOD, outdoor)
        else:
            m.box((cx + w0, y0 + y_0, cz + l0), (cx + w1, y0 + y_1, cz + l1), WOOD, outdoor)
    for i in range(5):                                       # top boards along the length
        w = -0.43 + i * 0.215
        box(-0.6, 0.6, 0.122, PALLET_H, w - 0.07, w + 0.07)
    for l in (-0.55, 0.0, 0.55):                             # cross boards, and the blocks under them
        box(l - 0.05, l + 0.05, 0.1, 0.122, -0.5, 0.5)
        for w in (-0.43, 0.0, 0.43):
            box(l - 0.05, l + 0.05, 0.022, 0.1, w - 0.07, w + 0.07)
    for w in (-0.43, 0.0, 0.43):                             # bottom boards
        box(-0.6, 0.6, 0.0, 0.022, w - 0.07, w + 0.07)


def pallet_stack(m, x, z, count, along_x, inside, seed):
    rng = random.Random(seed)
    y = L.FLOOR_Y if inside else 0.0
    for k in range(count):
        pallet(m, x + rng.uniform(-0.03, 0.03), y + k * PALLET_H, z + rng.uniform(-0.03, 0.03), along_x, not inside)


def leaning_pallet(m, x, wall_z, side, inside):
    """A pallet standing on its edge, its top resting against a long wall (side: which side of the wall)."""
    ground = L.FLOOR_Y if inside else 0.0
    best = None
    for angle in (75.0, -75.0):
        tmp = Mesh()
        pallet(tmp, 0.0, -PALLET_H / 2, 0.0, True, not inside)
        rot = Matrix.Rotation(math.radians(angle), 3, "X")
        pts = [rot @ p for poly in tmp.polys for p in poly[0]]
        top = max(pts, key=lambda p: p.y)
        bottom = min(pts, key=lambda p: p.y)
        # lean into the wall: the top edge must be nearer the wall than the foot
        if (top.z - bottom.z) * side < 0:
            best = (tmp, rot, pts)
    tmp, rot, pts = best
    ymin = min(p.y for p in pts)
    shift_z = (wall_z + 0.01 - min(p.z for p in pts)) if side > 0 else (wall_z - 0.01 - max(p.z for p in pts))
    offset = Vector((x, ground - ymin, shift_z))
    m.add_transformed(tmp, lambda p: rot @ p + offset)


def build_skip(m):
    """Waste skip in the depot's accent colour, open at the top."""
    sx, sz = L.SKIP_POS
    yb, yt = 0.14, 1.4

    def ring(hx, hz, y, inset=0.0):
        return [Vector((sx - hx + inset, y, sz - hz + inset)), Vector((sx + hx - inset, y, sz - hz + inset)),
                Vector((sx + hx - inset, y, sz + hz - inset)), Vector((sx - hx + inset, y, sz + hz - inset))]
    bottom, top = ring(1.5, 0.75, yb), ring(1.9, 0.92, yt)
    ibottom, itop = ring(1.5, 0.75, yb + 0.06, 0.06), ring(1.9, 0.92, yt, 0.06)
    for i in range(4):
        j = (i + 1) % 4
        out = (bottom[i] + bottom[j] + top[i] + top[j]) / 4 - Vector((sx, (yb + yt) / 2, sz))
        out.y = 0
        m.poly([bottom[i], bottom[j], top[j], top[i]], ACCENT, out)
        m.poly([ibottom[i], ibottom[j], itop[j], itop[i]], P("frame"), -out, outdoor=False)
        m.poly([top[i], top[j], itop[j], itop[i]], P("frame"), (0, 1, 0))           # rim
    m.poly(bottom, P("frame"), (0, -1, 0))
    m.poly(ibottom, P("frame"), (0, 1, 0), outdoor=False)
    for dz in (-0.5, 0.42):                                                            # runners
        m.box((sx - 1.55, 0.0, sz + dz), (sx + 1.55, yb, sz + dz + 0.08), P("frame"))
    for dx in (-1.62, 1.54):                                                           # lifting lugs
        m.box((sx + dx, 0.75, sz - 0.6), (sx + dx + 0.08, 0.95, sz + 0.6), P("frame"))


def build_floor_markings(m):
    y = L.FLOOR_Y + 0.004

    def line(x0, x1, z0, z1):
        m.poly([(x0, y, z0), (x1, y, z0), (x1, y, z1), (x0, y, z1)], P("yellow"), (0, 1, 0), outdoor=False)
    for _, front_z, segments in L.RACK_ROWS:                  # line along the front of every rack run
        for x0, bays in segments:
            line(x0 - 0.15, x0 + bays * L.RACK_BAY + 0.15, front_z + 0.15, front_z + 0.23)
    for x in (-2.04, 1.96):                                   # walkway from the open front to the back door
        line(x, x + 0.08, -L.HALL_Z + L.WALL_THICK + 0.05, L.HALL_Z - 0.4)


def build_rack_guards(m):
    """Yellow guards in front of the end uprights of every rack run."""
    for _, front_z, segments in L.RACK_ROWS:
        for x0, bays in segments:
            for x in (x0, x0 + bays * L.RACK_BAY):
                m.box((x - 0.1, L.FLOOR_Y, front_z + 0.02), (x + 0.1, 0.5, front_z + 0.12), P("yellow"),
                      outdoor=False, skip=("-y",))


def build_extinguishers(m):
    zf = L.HALL_Z - L.COLUMN_INSET - L.COLUMN / 2         # inner face of the front columns
    front = 1.5 * math.pi                                  # the hall side (-z) as a lathe angle

    def body_mat(band, angle):                             # white label on the front of band 3
        near = abs((angle - front + math.pi) % (2 * math.pi) - math.pi) < 0.75
        return P("white") if band == 3 and near else P("red")
    for x in L.EXTINGUISHER_XS:
        z = zf - 0.11                                      # body axis, clear of the bracket
        m.box((x - 0.05, 1.02, zf - 0.015), (x + 0.05, 1.3, zf), P("galv"), outdoor=False, skip=("+z",))
        m.box((x - 0.03, 1.2, zf - 0.03), (x + 0.03, 1.24, zf - 0.015), P("galv"), outdoor=False, skip=("+z",))
        m.lathe(x, z, [(0.78, 0.0), (0.78, 0.075), (0.8, 0.085), (0.95, 0.085), (1.12, 0.085), (1.24, 0.085),
                       (1.29, 0.07), (1.32, 0.045), (1.33, 0.025), (1.39, 0.025)], body_mat, outdoor=False)
        m.box((x - 0.03, 1.39, z - 0.03), (x + 0.03, 1.45, z + 0.03), P("galv"), outdoor=False)       # valve
        m.box((x - 0.018, 1.4, z - 0.045), (x + 0.018, 1.436, z - 0.03), P("white"), outdoor=False)   # gauge
        m.beam((x, 1.455, z + 0.03), (x, 1.485, z - 0.11), 0.03, 0.012, P("rubber"))                  # lever
        m.beam((x, 1.43, z + 0.02), (x, 1.44, z - 0.1), 0.03, 0.012, P("rubber"))                     # handle
        m.beam((x + 0.03, 1.42, z), (x + 0.105, 1.36, z), 0.022, 0.022, P("rubber"))                  # hose
        m.beam((x + 0.105, 1.36, z), (x + 0.105, 1.0, z), 0.022, 0.022, P("rubber"))
        m.beam((x + 0.105, 1.0, z), (x + 0.105, 0.9, z), 0.032, 0.032, P("rubber"))                   # nozzle
        m.box((x + 0.08, 0.99, z - 0.02), (x + 0.12, 1.01, z + 0.02), P("galv"), outdoor=False)       # clip
        # sign above it
        m.box((x - 0.16, 1.58, zf - 0.02), (x + 0.16, 1.9, zf), P("red"), outdoor=False, skip=("+z",))
        m.poly([(x - 0.08, 1.66, zf - 0.025), (x + 0.08, 1.66, zf - 0.025), (x + 0.08, 1.82, zf - 0.025),
                (x - 0.08, 1.82, zf - 0.025)], P("white"), (0, 0, -1), outdoor=False)


def build_inside_sign(m):
    """The FOOD / GOODS board again, inside above the back door."""
    z = -L.HALL_Z + L.WALL_THICK
    x0, x1, y0, y1 = -2.2, 2.2, 5.25, 5.91
    m.poly([(x0, y0, z + 0.07), (x1, y0, z + 0.07), (x1, y1, z + 0.07), (x0, y1, z + 0.07)], SIGN, (0, 0, 1),
           outdoor=False)
    m.box((x0 - 0.04, y0 - 0.04, z), (x1 + 0.04, y1 + 0.04, z + 0.065), P("frame"), outdoor=False, skip=("-z",))


def build_bench(m):
    x, z = L.BENCH_POS
    for dx in (-0.8, 0.8):                                   # frame
        m.box((x + dx - 0.04, 0.0, z - 0.22), (x + dx + 0.04, 0.45, z + 0.22), P("frame"))
        m.box((x + dx - 0.04, 0.45, z - 0.25), (x + dx + 0.04, 0.85, z - 0.19), P("frame"))
    for k in range(3):                                       # seat and back slats
        m.box((x - 0.95, 0.45, z - 0.2 + k * 0.14), (x + 0.95, 0.49, z - 0.09 + k * 0.14), WOOD)
    for k in range(2):
        m.box((x - 0.95, 0.58 + k * 0.16, z - 0.27), (x + 0.95, 0.7 + k * 0.16, z - 0.23), WOOD)


def build_bins(m):
    _, z = L.BENCH_POS
    for x in L.BIN_XS:
        m.box((x - 0.29, 0.06, z - 0.36), (x + 0.29, 1.0, z + 0.36), ACCENT)
        m.box((x - 0.31, 1.0, z - 0.4), (x + 0.31, 1.06, z + 0.38), P("rubber"))          # lid
        m.box((x - 0.3, 0.0, z - 0.34), (x - 0.22, 0.12, z - 0.22), P("rubber"))            # wheels
        m.box((x + 0.22, 0.0, z - 0.34), (x + 0.3, 0.12, z - 0.22), P("rubber"))


def build_ibc(m):
    x, z = L.IBC_POS
    pallet(m, x, 0.0, z, True, True)
    y0 = PALLET_H
    m.box((x - 0.55, y0, z - 0.45), (x + 0.55, y0 + 0.95, z + 0.45), P("white"), skip=("-y",))   # tank
    m.cylinder(x, y0 + 0.95, z, 0.14, 0.06, P("rubber"))                                        # filler cap
    for dx in (-0.58, 0.58):                                                                    # cage bars
        for dz in (-0.48, 0.48):
            m.box((x + dx - 0.02, y0, z + dz - 0.02), (x + dx + 0.02, y0 + 1.0, z + dz + 0.02), P("galv"))
    for y in (y0 + 0.33, y0 + 0.66, y0 + 1.0):
        for dz in (-0.48, 0.48):
            m.box((x - 0.6, y - 0.02, z + dz - 0.02), (x + 0.6, y + 0.02, z + dz + 0.02), P("galv"))
        for dx in (-0.58, 0.58):
            m.box((x + dx - 0.02, y - 0.02, z - 0.5), (x + dx + 0.02, y + 0.02, z + 0.5), P("galv"))
    m.box((x - 0.12, y0 + 0.05, z - 0.55), (x + 0.12, y0 + 0.2, z - 0.45), P("rubber"))        # tap


def build_barrels(m):
    x, z = L.BARRELS_POS
    for dx in (-0.31, 0.31):
        for dz in (-0.31, 0.31):
            m.cylinder(x + dx, 0.0, z + dz, 0.29, 0.88, P("rackPost"), top_mat=P("yellow"))


def build_workbench(m):
    """Steel workbench against the right wall (facing -x): wooden top, shelf, drawer cabinet, vise, toolbox,
    and a tool board with tools on the wall above it."""
    x = L.HALL_X - L.WALL_THICK
    z0, z1 = L.WORKBENCH_Z
    y = L.FLOOR_Y
    frame, steel, black, red, yellow = P("frame"), P("galv"), P("rubber"), P("red"), P("yellow")
    m.box((x - 0.75, 0.88, z0), (x, 0.93, z1), WOOD, False)                                       # top
    for lx in (x - 0.72, x - 0.08):                                                                # legs
        for lz in (z0 + 0.03, z1 - 0.08):
            m.box((lx, y, lz), (lx + 0.05, 0.88, lz + 0.05), frame, False, skip=("-y", "+y"))
    for lx in (x - 0.72, x - 0.08):                                                                # rails
        m.box((lx, 0.8, z0 + 0.08), (lx + 0.05, 0.88, z1 - 0.08), frame, False, skip=("+y",))
        m.box((lx, 0.15, z0 + 0.08), (lx + 0.05, 0.19, z1 - 0.08), frame, False)
    m.box((x - 0.69, 0.19, z0 + 0.06), (x - 0.06, 0.21, z1 - 0.06), WOOD, False)                 # shelf
    c0, c1 = z1 - 0.62, z1 - 0.1                                                                  # drawer cabinet
    m.box((x - 0.68, 0.21, c0), (x - 0.1, 0.8, c1), red, False, skip=("-y",))
    for k in range(4):
        ya = 0.21 + k * 0.1475
        m.box((x - 0.69, ya + 0.004, c0 + 0.02), (x - 0.68, ya + 0.1435, c1 - 0.02), red, False, skip=("+x",))
        m.box((x - 0.705, ya + 0.1, (c0 + c1) / 2 - 0.08), (x - 0.69, ya + 0.115, (c0 + c1) / 2 + 0.08), steel,
              False, skip=("+x",))
    vz = z0 + 0.2                                                                                  # vise at the front
    m.box((x - 0.72, 0.93, vz - 0.09), (x - 0.5, 0.96, vz + 0.09), frame, False, skip=("-y",))
    m.box((x - 0.62, 0.96, vz - 0.08), (x - 0.54, 1.06, vz + 0.08), frame, False)
    m.box((x - 0.76, 0.96, vz - 0.08), (x - 0.7, 1.06, vz + 0.08), frame, False)
    for jx in (x - 0.705, x - 0.635):
        m.box((jx, 1.0, vz - 0.075), (jx + 0.006, 1.06, vz + 0.075), steel, False)
    m.beam((x - 0.73, 0.99, vz), (x - 0.86, 0.99, vz), 0.025, 0.025, steel)                       # spindle
    m.beam((x - 0.86, 0.99, vz - 0.12), (x - 0.86, 0.99, vz + 0.12), 0.015, 0.015, steel)          # tommy bar
    tz0, tz1, tx0, tx1 = z1 - 0.62, z1 - 0.12, x - 0.42, x - 0.16                                 # toolbox on top
    m.box((tx0, 0.93, tz0), (tx1, 1.08, tz1), red, False, skip=("-y",))
    m.box((tx0 - 0.005, 1.075, tz0 - 0.005), (tx1 + 0.005, 1.085, tz1 + 0.005), black, False)
    m.box((tx0 - 0.005, 1.085, tz0 - 0.005), (tx1 + 0.005, 1.13, tz1 + 0.005), red, False)
    for zz in (tz0 + 0.1, tz1 - 0.1):
        m.box(((tx0 + tx1) / 2 - 0.01, 1.13, zz - 0.01), ((tx0 + tx1) / 2 + 0.01, 1.17, zz + 0.01), black, False,
              skip=("-y",))
        m.box((tx0 - 0.01, 1.05, zz - 0.02), (tx0, 1.1, zz + 0.02), steel, False, skip=("+x",))  # latches
    m.box(((tx0 + tx1) / 2 - 0.015, 1.17, tz0 + 0.09), ((tx0 + tx1) / 2 + 0.015, 1.19, tz1 - 0.09), black, False)
    # tool board on the wall, grey with a dark frame, tools hanging on it
    b0, b1 = 1.08, 1.86
    m.box((x - 0.02, b0, z0), (x, b1, z1), P("doorFrame"), False, skip=("+x",))
    for ya, yb, za, zb in ((b0 - 0.03, b0, z0 - 0.03, z1 + 0.03), (b1, b1 + 0.03, z0 - 0.03, z1 + 0.03),
                           (b0, b1, z0 - 0.03, z0), (b0, b1, z1, z1 + 0.03)):
        m.box((x - 0.03, ya, za), (x, yb, zb), frame, False, skip=("+x",))

    def tool(ya, yb, za, zb, mat, depth=0.015):
        m.box((x - 0.02 - depth, ya, za), (x - 0.02, yb, zb), mat, False, skip=("+x",))
    hz = z0 + 0.2                                                                                  # hammer
    tool(1.3, 1.6, hz - 0.015, hz + 0.015, WOOD, 0.025)
    tool(1.6, 1.65, hz - 0.07, hz + 0.07, steel, 0.03)
    for k, length in enumerate((0.18, 0.23, 0.28)):                                              # spanners
        wz = z0 + 0.42 + k * 0.08
        tool(1.72 - length, 1.72, wz - 0.012, wz + 0.012, steel, 0.008)
        tool(1.72, 1.76, wz - 0.022, wz + 0.022, steel, 0.008)
        tool(1.68 - length, 1.72 - length, wz - 0.02, wz + 0.02, steel, 0.008)
    for k, mat in enumerate((red, yellow, black)):                                                # screwdrivers
        sz = z0 + 0.74 + k * 0.07
        tool(1.6, 1.71, sz - 0.015, sz + 0.015, mat, 0.03)
        tool(1.46, 1.6, sz - 0.004, sz + 0.004, steel, 0.008)
    sz0, sz1 = z0 + 0.98, z1 - 0.12                                                              # hand saw
    m.hexa([(x - 0.026, 1.5, sz0 + 0.12), (x - 0.02, 1.5, sz0 + 0.12), (x - 0.02, 1.5, sz1),
            (x - 0.026, 1.5, sz1), (x - 0.026, 1.64, sz0 + 0.12), (x - 0.02, 1.64, sz0 + 0.12),
            (x - 0.02, 1.54, sz1), (x - 0.026, 1.54, sz1)], steel, False)
    tool(1.5, 1.66, sz0, sz0 + 0.12, black, 0.025)
    tool(1.22, 1.3, z0 + 0.45, z0 + 0.53, yellow, 0.04)                                          # tape measure
    tool(1.2, 1.36, z0 + 0.7, z0 + 0.74, black, 0.02)                                             # pliers
    tool(1.2, 1.36, z0 + 0.75, z0 + 0.79, black, 0.02)
    tool(1.36, 1.42, z0 + 0.7, z0 + 0.79, steel, 0.02)


def build_cabinet(m):
    x = -L.HALL_X + L.WALL_THICK
    z0, z1 = L.CABINET_Z
    m.box((x, L.FLOOR_Y, z0), (x + 0.5, 1.9, z1), P("doorFrame"), False, skip=("-x",))
    m.box((x + 0.5, 0.2, (z0 + z1) / 2 - 0.005), (x + 0.505, 1.8, (z0 + z1) / 2 + 0.005), P("rubber"), False)
    for zz in ((z0 + z1) / 2 - 0.08, (z0 + z1) / 2 + 0.05):                                      # handles
        m.box((x + 0.5, 1.0, zz), (x + 0.53, 1.12, zz + 0.03), P("galv"), False)


def build_pallet_jack(m):
    """Hand pallet truck, forks towards -x: tapered forks on load rollers, chassis, round pump with piston,
    two steering wheels in a bracket, loop handle."""
    x, z = L.PALLET_JACK_POS
    y = L.FLOOR_Y
    yellow, black, steel = P("yellow"), P("rubber"), P("galv")
    for dz in (-0.2, 0.2):
        z0, z1 = z + dz - 0.08, z + dz + 0.08
        m.box((x - 0.45, y + 0.02, z0), (x + 0.5, y + 0.085, z1), yellow, False, skip=("-y",))     # fork
        m.hexa([(x - 0.6, y + 0.02, z0), (x - 0.45, y + 0.02, z0), (x - 0.45, y + 0.02, z1),         # tapered tip
                (x - 0.6, y + 0.02, z1), (x - 0.6, y + 0.05, z0), (x - 0.45, y + 0.085, z0),
                (x - 0.45, y + 0.085, z1), (x - 0.6, y + 0.05, z1)], yellow, False)
        m.wheel(x - 0.5, y + 0.033, z + dz, 0.033, 0.09, black, steel)                              # load roller
        m.wheel(x + 0.42, y + 0.033, z + dz, 0.03, 0.06, black, steel)                              # entry roller
    m.box((x + 0.5, y + 0.02, z - 0.28), (x + 0.64, y + 0.24, z + 0.28), yellow, False, skip=("-y",))  # chassis
    m.hexa([(x + 0.5, y + 0.24, z - 0.28), (x + 0.64, y + 0.24, z - 0.28), (x + 0.64, y + 0.24, z + 0.28),
            (x + 0.5, y + 0.24, z + 0.28), (x + 0.5, y + 0.27, z - 0.22), (x + 0.6, y + 0.27, z - 0.22),
            (x + 0.6, y + 0.27, z + 0.22), (x + 0.5, y + 0.27, z + 0.22)], yellow, False)
    px = x + 0.74                                                                                   # pump axis
    for dz in (-0.1, 0.1):
        m.wheel(px, y + 0.09, z + dz, 0.09, 0.05, black, steel)                                     # steering wheels
    m.box((px - 0.11, y + 0.19, z - 0.15), (px + 0.11, y + 0.22, z + 0.15), yellow, False)         # wheel bracket
    for sz in (-1, 1):
        m.box((px - 0.07, y + 0.07, z + sz * 0.13 - 0.008), (px + 0.07, y + 0.19, z + sz * 0.13 + 0.008),
              yellow, False)
    m.box((x + 0.64, y + 0.12, z - 0.08), (px - 0.06, y + 0.22, z + 0.08), yellow, False)          # neck
    m.lathe(px, z, [(y + 0.22, 0.0), (y + 0.22, 0.085), (y + 0.46, 0.085), (y + 0.49, 0.065), (y + 0.49, 0.0)],
            yellow, False)
    m.lathe(px, z, [(y + 0.49, 0.03), (y + 0.6, 0.03)], steel, False)                            # piston
    m.box((px - 0.05, y + 0.6, z - 0.07), (px + 0.05, y + 0.65, z + 0.07), yellow, False)          # yoke
    for sz in (-1, 1):
        m.box((px - 0.03, y + 0.6, z + sz * 0.07 - 0.01), (px + 0.03, y + 0.7, z + sz * 0.07 + 0.01), yellow,
              False)
    # handle: tube from the yoke, a loop at the top with a rubber grip and the lift lever
    top, gy, gx = (x + 1.1, y + 1.12, z), y + 1.24, x + 1.16
    m.beam((px, y + 0.66, z), top, 0.045, 0.045, black)
    for sz in (-1, 1):
        m.beam(top, (gx, gy, z + sz * 0.16), 0.03, 0.03, black)
    m.beam((gx, gy, z - 0.18), (gx, gy, z + 0.18), 0.042, 0.042, black)
    m.beam((gx - 0.01, gy - 0.03, z + 0.02), (gx - 0.08, gy - 0.02, z + 0.02), 0.012, 0.02, steel)  # lever


def build_decor(m, detail):
    for i, (x, z, count, along_x, inside) in enumerate(L.DECOR_STACKS):
        if detail == 0 or not inside:
            pallet_stack(m, x, z, count, along_x, inside, seed=i)
    for x, wall_z, side, inside in L.DECOR_LEANING:
        if detail == 0 or not inside:
            leaning_pallet(m, x, wall_z, side, inside)
    build_skip(m)
    build_bins(m)
    build_barrels(m)
    if detail == 0:
        build_ibc(m)
        build_bench(m)
        build_workbench(m)
        build_cabinet(m)
        build_pallet_jack(m)
        build_floor_markings(m)
        build_rack_guards(m)
        build_extinguishers(m)
        build_inside_sign(m)


def decor_collision(m):
    """Simple boxes around the pallets and the skip."""
    for x, z, count, along_x, inside in L.DECOR_STACKS:
        hx, hz = (0.6, 0.5) if along_x else (0.5, 0.6)
        y = L.FLOOR_Y if inside else 0.0
        m.box((x - hx, y, z - hz), (x + hx, y + count * PALLET_H, z + hz), None, False)
    for x, wall_z, side, inside in L.DECOR_LEANING:
        z0, z1 = sorted((wall_z, wall_z + side * 0.42))
        m.box((x - 0.6, L.FLOOR_Y if inside else 0.0, z0), (x + 0.6, 1.15, z1), None, False)
    sx, sz = L.SKIP_POS
    m.box((sx - 1.9, 0.0, sz - 0.92), (sx + 1.9, 1.4, sz + 0.92), None, False)
    bx, bz = L.BENCH_POS
    m.box((bx - 0.95, 0.0, bz - 0.27), (bx + 0.95, 0.85, bz + 0.22), None, False)
    m.box((min(L.BIN_XS) - 0.31, 0.0, bz - 0.4), (max(L.BIN_XS) + 0.31, 1.06, bz + 0.38), None, False)
    ix, iz = L.IBC_POS
    m.box((ix - 0.6, 0.0, iz - 0.55), (ix + 0.6, PALLET_H + 1.05, iz + 0.5), None, False)
    rx, rz = L.BARRELS_POS
    m.box((rx - 0.6, 0.0, rz - 0.6), (rx + 0.6, 0.88, rz + 0.6), None, False)
    wx = L.HALL_X - L.WALL_THICK
    m.box((wx - 0.75, 0.0, L.WORKBENCH_Z[0]), (wx, 0.95, L.WORKBENCH_Z[1]), None, False)
    cx = -L.HALL_X + L.WALL_THICK
    m.box((cx, 0.0, L.CABINET_Z[0]), (cx + 0.5, 1.9, L.CABINET_Z[1]), None, False)


def build_visual(parent):
    visual = attrs(node("visual", parent), lod=True, lod1=70.0, lod2=180.0)
    for detail in range(3):
        m = Mesh()
        build_floor(m)
        build_walls(m, detail)
        build_roof(m, detail)
        build_gutters(m, detail)
        build_frame(m, detail)
        build_canopy(m, detail)
        build_doors(m, detail)
        build_windows(m, detail)
        if detail < 2:
            build_corners(m)
            build_racks(m, detail)
            build_decor(m, detail)
        obj = m.to_object("lod%d" % detail, visual)
        attrs(obj, collision=False, clipDistance=600.0 if detail == 2 else 0.0)
        print("LOD%d: %d polygons" % (detail, len(m.polys)))
    return visual


# --- physics ----------------------------------------------------------------------------------------
def wall_slab(m, axis, s0, s1, t0, t1, gaps):
    """Collision box of a wall from s0 to s1 along axis ('x' or 'z'), t0..t1 across, with door gaps (a, b, h)
    left open from the ground up to h."""
    def box(a, b, y0):
        lo, hi = ((a, y0, t0), (b, L.EAVE_Y, t1)) if axis == "x" else ((t0, y0, a), (t1, L.EAVE_Y, b))
        m.box(lo, hi, None, False)
    start = s0
    for a, b, h in sorted(gaps):
        box(start, a, 0.0)
        box(a, b, h)
        start = b
    box(start, s1, 0.0)


def solid_boxes(m, with_racks, door_gaps=False):
    """Closed boxes for the collision and occlusion meshes; door_gaps: leave the roller door openings free
    (their moving collision slices close them, see build_door_parts)."""
    hx, hz, t = L.HALL_X, L.HALL_Z, 0.2

    def gaps(wall):
        return [(c - w / 2, c + w / 2, h) for wl, c, w, h in L.DOORS if wl == wall] if door_gaps else []
    m.box((-hx, -0.3, -hz), (hx, L.FLOOR_Y, hz), None, False)
    wall_slab(m, "x", -hx, hx, -hz, -hz + t, gaps("back"))                          # back
    for x0, x1 in ((-hx, -L.FRONT_OPEN_X), (L.FRONT_OPEN_X, hx)):                   # front
        m.box((x0, 0.0, hz - t), (x1, L.EAVE_Y, hz), None, False)
    m.box((-L.FRONT_OPEN_X, L.FRONT_OPEN_Y, hz - t), (L.FRONT_OPEN_X, L.EAVE_Y, hz), None, False)
    for x0, x1, wall in ((-hx, -hx + t, "left"), (hx - t, hx, "right")):            # gables
        wall_slab(m, "z", -hz, hz, x0, x1, gaps(wall))
        for s in (1, -1):
            a = [(x0, L.EAVE_Y, s * hz), (x0, L.EAVE_Y, 0.0), (x0, roof_under(0.0), 0.0)]
            b = [(x1, y, z) for _, y, z in a]
            m.poly(a, None, (-1, 0, 0), outdoor=False)
            m.poly(b, None, (1, 0, 0), outdoor=False)
            m.poly([a[0], a[2], b[2], b[0]], None, (0, 1, s * T), outdoor=False)
    if with_racks:
        for _, front_z, segments in L.RACK_ROWS:
            for x0, bays in segments:
                m.box((x0 - 0.05, L.FLOOR_Y, front_z - L.RACK_DEPTH), (x0 + bays * L.RACK_BAY + 0.05,
                      L.RACK_HEIGHT, front_z), None, False)
        zc = L.HALL_Z - L.COLUMN_INSET
        for fx in L.FRAME_XS:
            if abs(fx) < L.HALL_X:
                for s in [-1] + ([1] if abs(fx) >= L.FRONT_OPEN_X else []):
                    m.box((fx - 0.15, 0.0, s * zc - 0.15), (fx + 0.15, L.EAVE_Y, s * zc + 0.15), None, False)


def roof_slab(m):
    xe, ze = L.HALL_X + L.GABLE_OVERHANG, L.HALL_Z + L.EAVE_OVERHANG
    for s in (1, -1):
        lo = [(-xe, roof_under(ze), s * ze), (xe, roof_under(ze), s * ze), (xe, roof_under(0.0), 0.0),
              (-xe, roof_under(0.0), 0.0)]
        hi = [(x, y + ROOF_OFF, z) for x, y, z in lo]
        m.poly(hi, None, (0, 1, s * T), outdoor=False)
        m.poly(lo, None, (0, -1, -s * T), outdoor=False)
        for i in range(4):
            j = (i + 1) % 4
            mid = Vector(lo[i]) + Vector(lo[j]) - Vector((0, 2 * roof_under(ze), 0))
            m.poly([lo[i], lo[j], hi[j], hi[i]], None, (mid.x, 0, mid.z if i != 2 else 0.0), outdoor=False)


def build_physics(parent):
    m = Mesh()
    solid_boxes(m, True, door_gaps=True)
    roof_slab(m)
    # the awning and its sign have no collision: crane arms of trucks on the pad pass through them
    decor_collision(m)
    attrs(m.to_object("collision", parent), static=True, nonRenderable=True, castsShadows=False,
          receiveShadows=False, collisionFilterGroup=COL_BUILDING[0], collisionFilterMask=COL_BUILDING[1])

    m = Mesh()
    solid_boxes(m, False)
    attrs(m.to_object("tipCollision", parent), static=True, nonRenderable=True, castsShadows=False,
          receiveShadows=False, collisionFilterGroup=COL_TIP[0], collisionFilterMask=COL_TIP[1])

    if not WITH_OCCLUDER:
        return
    m = Mesh()                                   # occluder: back and gable walls only, the front is open
    hx, hz = L.HALL_X - 0.1, L.HALL_Z - 0.1
    m.box((-hx, 0.5, -hz), (hx, L.EAVE_Y - 0.1, -hz + 0.05), None, False)
    for x in (-hx, hx - 0.05):
        m.box((x, 0.5, -hz), (x + 0.05, L.EAVE_Y - 0.1, hz), None, False)
    attrs(m.to_object("occluder", parent), oc=True, nonRenderable=True, castsShadows=False,
          receiveShadows=False, collision=False, clipDistance=500.0)


# --- visible stock ----------------------------------------------------------------------------------
GOODS_HEIGHT = {"boxes": 1.15, "sacks": 0.95, "crates": 1.05, "wrapped": 1.3}


def stock_mesh(variant):
    m = Mesh()
    wood = ("depot_stock", L.STOCK_REGIONS["pallet"])
    m.box((-0.6, 0.11, -0.5), (0.6, 0.144, 0.5), wood, False)
    for x in (-0.49, 0.0, 0.49):
        m.box((x - 0.06, 0.0, -0.5), (x + 0.06, 0.11, 0.5), wood, False, skip=("-y",))
    goods = ("depot_stock", L.STOCK_REGIONS[variant])
    m.box((-0.56, 0.144, -0.47), (0.56, 0.144 + GOODS_HEIGHT[variant], 0.47), goods, False, skip=("-y",))
    obj = m.to_object("stockMesh_" + variant, None)
    me = obj.data
    bpy.data.objects.remove(obj)
    return me


def build_stock(parent):
    stock = node("stock", parent)
    meshes = {v: stock_mesh(v) for v in L.STOCK_VARIANTS}
    rng = random.Random(25)
    slots = L.rack_slots()
    for i, pos in enumerate(slots):
        obj = add_object("stock%02d" % (i + 1), meshes[rng.choice(L.STOCK_VARIANTS)], stock, pos)
        attrs(obj, clipDistance=150.0, collision=False)
        obj["i3d_hidden"] = True
    print("stock pallets:", len(slots))
    return stock


# --- ground markings --------------------------------------------------------------------------------
DECAL_Y = 0.01


def strip(m, a, b, width):
    """Warning stripes from a to b (x, z), tiling along the strip."""
    a, b = Vector((a[0], 0, a[1])), Vector((b[0], 0, b[1]))
    d = b - a
    side = Vector((-d.z, 0, d.x)).normalized() * (width / 2)
    u1 = d.length * 0.25 / width
    pts = [a - side, b - side, b + side, a + side]
    m.poly([(p.x, DECAL_Y, p.z) for p in pts], "depot_decals", (0, 1, 0),
           uv=[(0, 0.752), (u1, 0.752), (u1, 0.998), (0, 0.998)], outdoor=False)


def label(m, center, size, rot_y, region):
    """Quad with a texture region, readable when facing it from its local -z side."""
    cx, cz = center
    w, h = size
    c, s = math.cos(math.radians(rot_y)), math.sin(math.radians(rot_y))

    def pt(lx, lz):
        return (cx + lx * c + lz * s, DECAL_Y, cz - lx * s + lz * c)
    u0, v0, u1, v1 = region
    m.poly([pt(-w / 2, h / 2), pt(w / 2, h / 2), pt(w / 2, -h / 2), pt(-w / 2, -h / 2)], "depot_decals", (0, 1, 0),
           uv=[(u0, v0), (u1, v0), (u1, v1), (u0, v1)], outdoor=False)


def rect_stripes(m, x, z, width):
    (x0, x1), (z0, z1) = x, z
    hw = width / 2
    strip(m, (x0, z0 + hw), (x1, z0 + hw), width)
    strip(m, (x0, z1 - hw), (x1, z1 - hw), width)
    strip(m, (x0 + hw, z0 + width), (x0 + hw, z1 - width), width)
    strip(m, (x1 - hw, z0 + width), (x1 - hw, z1 - width), width)


def build_decals(parent):
    m = Mesh()
    rect_stripes(m, L.PAD_X, L.PAD_Z, 0.3)
    label(m, (L.PAD_CENTER[0], L.PAD_Z[1] - 0.95), (4.0, 1.0), 0.0, (0.0, 0.5, 1.0, 0.75))     # UNLOAD
    for x in (L.PAD_X[0] + 1.3, L.PAD_X[1] - 1.3):
        label(m, (x, L.PAD_CENTER[1]), (1.2, 1.2), 0.0, (0.0, 0.0, 0.25, 0.25))               # arrow, +x
    zs = L.SPAWN_LANE_ZS
    lane_z = (min(zs) - L.SPAWN_LANE_HALF_WIDTH, max(zs) + L.SPAWN_LANE_HALF_WIDTH)
    lane_x = (L.SPAWN_LANE_X[0] - 0.3, L.SPAWN_LANE_X[1] + 0.3)
    rect_stripes(m, lane_x, lane_z, 0.2)
    zm = sum(zs) / 2
    x = lane_x[0] + 0.6
    while x + 1.0 < lane_x[1] - 0.4:                                                          # lane divider
        strip(m, (x, zm), (x + 1.0, zm), 0.12)
        x += 2.0
    label(m, (L.LOAD_MARKER_POS[0] + 1.3, L.LOAD_MARKER_POS[2]), (3.2, 0.8), 180.0, (0.0, 0.25, 1.0, 0.5))
    obj = m.to_object("warningStripes", parent)
    return attrs(obj, terrainDecal=True, nonRenderable=True, collision=False, clipDistance=200.0)


# --- function nodes ---------------------------------------------------------------------------------
def build_functions(root):
    # placement areas: whole site, hall interior, both aprons
    ax, az = L.AREA_X, L.AREA_Z
    full = ((ax[1] - ax[0], 0.0, 0.0), (0.0, 0.0, az[1] - az[0]))
    for prefix in ("clearArea", "levelArea"):
        area(node(prefix + "s", root), prefix, 1, ax, az, *full)
    paint = node("paintAreas", root)
    area(paint, "paintArea", 1, ax, (L.HALL_Z, az[1]), (ax[1] - ax[0], 0, 0), (0, 0, az[1] - L.HALL_Z))
    area(paint, "paintArea", 2, ax, (az[0], -L.HALL_Z), (ax[1] - ax[0], 0, 0), (0, 0, az[0] * -1 - L.HALL_Z))
    ix, iz = (-L.HALL_X + 0.1, L.HALL_X - 0.1), (-L.HALL_Z + 0.1, L.HALL_Z - 0.1)
    area(node("indoorAreas", root), "indoorArea", 1, ix, iz, (ix[1] - ix[0], 0, 0), (0, 0, iz[1] - iz[0]))
    area(node("testAreas", root), "testArea", 1, ax, az, (ax[1] - ax[0], L.AREA_HEIGHT, az[1] - az[0]))
    area(node("tipOcclusionUpdateAreas", root), "tipOcclusionUpdateArea", 1, ax, az,
         (ax[1] - ax[0], 0.0, az[1] - az[0]))

    trigger("infoTrigger", root, (0.0, L.FLOOR_Y + L.INFO_TRIGGER_SIZE[1] / 2, 0.0), L.INFO_TRIGGER_SIZE,
            COL_PLAYER_TRIGGER)

    pp = node("productionPoint", root, L.PLAYER_TRIGGER_POS)
    trigger("playerTrigger", pp, (0.0, L.PLAYER_TRIGGER_SIZE[1] / 2, 0.0), L.PLAYER_TRIGGER_SIZE,
            COL_PLAYER_TRIGGER)
    node("playerTriggerMarker", pp, (0.0, 1.0, 0.0))

    # selling station on the front pad: exact-fill root (mostly below ground) and a grid of
    # real-size pallet trigger boxes; never scaled
    cx, cz = L.PAD_CENTER
    ss = node("sellingStation", root, (cx, 0.0, cz))
    pad = (L.PAD_X[1] - L.PAD_X[0], 1.0, L.PAD_Z[1] - L.PAD_Z[0])
    trigger("unloadTrigger", ss, (0.0, L.UNLOAD_TRIGGER_Y, 0.0), pad, COL_EXACT_FILL, kinematic=True)["i3D_trigger"] = False
    node("unloadTriggerMarker", ss, (0.0, 0.5, 0.0))
    node("unloadAINode", ss, (L.PAD_X[0] - cx + 1.0, 0.0, 0.0), rot_y=90.0)    # trucks drive along +x
    pt = node("palletTriggers", ss)
    sx, sy, sz = L.PALLET_TRIGGER_SIZE
    i = 1
    for level in range(L.PALLET_TRIGGER_LEVELS):
        for col in range(L.PALLET_TRIGGER_COLUMNS):
            x = L.PAD_X[0] - cx + sx * (col + 0.5)
            trigger("palletTrigger%02d" % i, pt, (x, sy * (level + 0.5), 0.0), L.PALLET_TRIGGER_SIZE,
                    COL_PALLET_TRIGGER, kinematic=True)
            i += 1

    # pallet spawner: two lanes parallel to the back wall; each start node's +z runs along the lane
    # spawn places in fill order: both lanes on the ground, then both lanes 1.5 m up (stacked pallets)
    sp = node("palletSpawner", root)
    places = [(z, 0.0) for z in L.SPAWN_LANE_ZS] + [(z, L.SPAWN_STACK_Y) for z in L.SPAWN_LANE_ZS]
    for i, (z, y) in enumerate(places, 1):
        start = node("palletAreaStart%02d" % i, sp, (L.SPAWN_LANE_X[0], y, z), rot_y=90.0)
        node("palletAreaEnd%02d" % i, start, (0.0, 0.0, L.SPAWN_LANE_X[1] - L.SPAWN_LANE_X[0]))
    node("loadMarker", sp, L.LOAD_MARKER_POS)

    lights = node("lights", root)
    for name, pos, rot in L.WALL_LIGHTS:
        node(name, lights, pos, rot_y=rot)
    real = node("realLights", lights)
    for i, pos in enumerate(L.POINT_LIGHTS, 1):
        inside = pos[2] < L.HALL_Z
        data = bpy.data.lights.new("pointLight%02d" % i, "POINT")
        data.color = (0.55, 0.52, 0.45) if inside else (0.44, 0.42, 0.38)
        data.use_shadow = False
        if hasattr(data, "use_custom_distance"):
            data.use_custom_distance = True
            data.cutoff_distance = 14.0 if inside else 9.0
        attrs(add_object("pointLight%02d" % i, data, real, pos), weatherMask="0x40", renderInvisible=True)


# --- export -----------------------------------------------------------------------------------------
def export(path):
    addon_utils.enable(EXPORTER, default_set=False, persistent=False)
    exp = importlib.import_module(EXPORTER + ".i3d_export")
    dccb = importlib.import_module(EXPORTER + ".dcc.dccBlender")
    dccb.isNodeVisible = lambda name: not bpy.data.objects[name].get("i3d_hidden", False)
    log = importlib.import_module(EXPORTER + ".util.logUtil").ActionLog
    orig = log.addMessage.__func__
    errors = []

    def show(cls, message, messageType="INFO"):
        print("I3D", messageType, message)
        if messageType in ("ERROR", "WARNING"):
            errors.append(message)
        return orig(cls, message, messageType)
    log.addMessage = classmethod(show)

    st = bpy.context.scene.I3D_UIexportSettings
    st.i3D_exportUseSoftwareFileName = False
    st.i3D_exportFileLocation = path
    st.i3D_gameLocationDisplay = GAME_DIR
    st.i3D_exportRelativePaths = True
    st.i3D_exportGameRelativePath = False
    st.i3D_exportVerbose = True
    exp.I3DExportAll()
    if not (os.path.exists(path) and os.path.exists(path + ".shapes")):
        sys.exit("export failed, see the I3D lines above")
    return errors


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    out = os.path.abspath(argv[0] if argv else os.path.join(ROOT, "i3d", "depot.i3d"))
    blend = os.path.join(ROOT, "build", "depot.blend")

    bpy.ops.wm.read_factory_settings(use_empty=True)
    os.makedirs(os.path.dirname(blend), exist_ok=True)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=blend)      # custom texture paths resolve against the .blend
    make_materials()

    root = attrs(node("palletDepot"), lockedGroup=True)
    build_visual(root)
    build_physics(root)
    build_door_parts(root)
    build_stock(root)
    build_decals(root)
    build_functions(root)
    bpy.ops.wm.save_as_mainfile(filepath=blend)

    errors = export(out)
    print("EXPORTED", out, os.path.getsize(out), os.path.getsize(out + ".shapes"))
    if errors:
        print("EXPORT WARNINGS/ERRORS:", len(errors))


if __name__ == "__main__":
    main()
