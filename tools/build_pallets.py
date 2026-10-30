"""Builds the two depot pallets (1,000 L and 5,000 L) in Blender and exports one i3d per pallet into vehicles/.

    blender --background --factory-startup --python tools/build_pallets.py

The pallets are vehicles of type "pallet" (vehicles/depotPallet*.xml, written by tools/gen_pallets.py). Node layout
follows the base game's pallets: the root is the dynamic compound body (collision around the goods), with the
dynamic-mount trigger, our own wooden pallet (pallet#node), the goods (pallet content) and the runner collisions that
leave gaps for forks. Uses the helpers and materials of build_warehouse.py.
"""
import os
import sys

import bpy

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import build_warehouse as W  # noqa: E402

# size: (pallet length along x, depth along z, goods height)
SIZES = {1000: (1.2, 1.0, 0.95), 5000: (2.4, 1.2, 1.55)}
DECK = 0.144

COL_PALLET = ("0x10004", "0xfe3ffb83")
COL_PALLET_FLOOR = ("0x10000", "0xfe3dfb83")
COL_MOUNT_TRIGGER = ("0x20000000", "0x20000")
WRAPPED = ("depot_stock", W.L.STOCK_REGIONS["wrapped"])


def runners(length, depth):
    """z positions of the runners under the deck (forks go in between, along x)."""
    count = 3 if depth <= 1.0 else 4
    return [-depth / 2 + 0.06 + i * (depth - 0.12) / (count - 1) for i in range(count)]


def build_pallet(size):
    length, depth, height = SIZES[size]
    name = "depotPallet%d" % size
    hx, hz = length / 2, depth / 2

    # root: dynamic compound body, its collision is the goods volume
    m = W.Mesh()
    m.box((-hx + 0.04, DECK, -hz + 0.02), (hx - 0.04, DECK + height, hz - 0.02), None, False)
    root = m.to_object(name + "_component1", None)
    W.attrs(root, dynamic=True, compound=True, staticFriction=1.0, dynamicFriction=1.0, density=0.0,
            collisionFilterGroup=COL_PALLET[0], collisionFilterMask=COL_PALLET[1], nonRenderable=True,
            castsShadows=False, receiveShadows=False, clipDistance=150.0)

    W.box_shape("dynamicMountTrigger", root, (0.0, (DECK + height) / 2, 0.0),
                (length + 0.1, DECK + height + 0.1, depth + 0.1), kinematic=True, trigger=True, nonRenderable=True,
                collisionFilterGroup=COL_MOUNT_TRIGGER[0], collisionFilterMask=COL_MOUNT_TRIGGER[1])

    # our own wooden pallet: deck boards along x on runners along x
    m = W.Mesh()
    boards = 5 if depth <= 1.0 else 7
    for i in range(boards):
        z = -hz + 0.07 + i * (depth - 0.14) / (boards - 1)
        m.box((-hx, DECK - 0.022, z - 0.065), (hx, DECK, z + 0.065), W.WOOD, True)
    for z in runners(length, depth):
        m.box((-hx, 0.0, z - 0.055), (hx, DECK - 0.022, z + 0.055), W.WOOD, True, skip=("-y",))
    W.attrs(m.to_object("palletVisual", root), clipDistance=150.0, collision=False)

    # the goods: a stretch-wrapped block, also the content node for tension belts
    content = W.node("content", root)
    m = W.Mesh()
    m.box((-hx + 0.04, DECK, -hz + 0.02), (hx - 0.04, DECK + height, hz - 0.02), WRAPPED, True, skip=("-y",))
    W.attrs(m.to_object("goods", content), clipDistance=150.0, collision=False)

    # runner collisions (compound children) leave the gaps for forks
    collisions = W.attrs(W.node("collisions", root), collision=False)
    for i, z in enumerate(runners(length, depth), 1):
        W.box_shape("floorCollision%02d" % i, collisions, (0.0, (DECK - 0.022) / 2, z), (length, DECK - 0.022, 0.11),
                    compoundChild=True, staticFriction=1.0, dynamicFriction=1.0, density=0.0, nonRenderable=True,
                    collisionFilterGroup=COL_PALLET_FLOOR[0], collisionFilterMask=COL_PALLET_FLOOR[1])
    return name


def main():
    for size in SIZES:
        bpy.ops.wm.read_factory_settings(use_empty=True)
        blend = os.path.join(W.ROOT, "build", "depotPallet%d.blend" % size)
        os.makedirs(os.path.dirname(blend), exist_ok=True)
        bpy.ops.wm.save_as_mainfile(filepath=blend)
        W.make_materials()
        name = build_pallet(size)
        bpy.ops.wm.save_as_mainfile(filepath=blend)
        out = os.path.join(W.ROOT, "vehicles", name + ".i3d")
        os.makedirs(os.path.dirname(out), exist_ok=True)
        W.export(out)
        print("EXPORTED", out, os.path.getsize(out), os.path.getsize(out + ".shapes"))


if __name__ == "__main__":
    main()
