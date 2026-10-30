"""Turns the exported i3d/depot.i3d into one i3d per building and checks it.

Both buildings share i3d/depot.i3d.shapes; their i3d files differ only in the brand texture (sign face
and accent band). Also writes build/i3d_mappings.json (node name -> "0>a|b" index path) for the
placeable XML generator, so XML nodes always match the exported scene.

    python tools/finish_i3d.py
"""
import json
import os
import sys
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import layout as L  # noqa: E402

ROOT = os.path.dirname(HERE)
I3D_DIR = os.path.join(ROOT, "i3d")
SOURCE = os.path.join(I3D_DIR, "depot.i3d")
BRAND_TEXTURE = "depot_brand_%s_diffuse.dds"


def mappings(scene):
    """Index paths of all nodes below the single root ("0>" is the root itself)."""
    out = {}

    def walk(elem, path):
        for i, child in enumerate(c for c in elem if c.tag in ("TransformGroup", "Shape", "Light", "Camera")):
            p = path + [str(i)]
            name = child.get("name")
            if name in out:
                sys.exit("duplicate node name in i3d: " + name)
            out[name] = "0>" + "|".join(p)
            walk(child, p)
    roots = [c for c in scene if c.tag in ("TransformGroup", "Shape")]
    if len(roots) != 1:
        sys.exit("expected one root node, found %d" % len(roots))
    out[roots[0].get("name")] = "0>"
    walk(roots[0], [])
    return out


def check(tree):
    problems = []
    files = tree.getroot().find("Files")
    for f in files:
        name = f.get("filename")
        if not name.startswith("$") and not os.path.exists(os.path.join(I3D_DIR, name)):
            problems.append("missing file " + name)
    mats = tree.getroot().find("Materials")
    for m in mats:
        if m.get("emissiveColor"):
            problems.append("emissive material " + m.get("name"))
    scene = tree.getroot().find("Scene")
    stock = [n for n in scene.iter("Shape") if n.get("name", "").startswith("stock")]
    if len(stock) != len(L.rack_slots()) or any(n.get("visibility") != "false" for n in stock):
        problems.append("stock pallets: %d, all hidden: %s" % (len(stock), all(n.get("visibility") == "false"
                                                                               for n in stock)))
    triggers = [n for n in scene.iter("Shape") if n.get("name", "").startswith("palletTrigger")]
    if len(triggers) != L.PALLET_TRIGGER_COLUMNS * L.PALLET_TRIGGER_LEVELS:
        problems.append("pallet triggers: %d" % len(triggers))
    if any(n.get("scale") for n in scene.iter()):
        problems.append("scaled nodes (triggers must never be scaled)")
    return problems


def main():
    tree = ET.parse(SOURCE)
    problems = check(tree)
    if problems:
        sys.exit("i3d check failed:\n  " + "\n  ".join(problems))
    text = open(SOURCE, encoding="iso-8859-1", newline="").read()
    default = BRAND_TEXTURE % "food"
    assert text.count(default) == 1, "brand texture not found in " + SOURCE
    for brand in L.BRANDS:
        out = text.replace(default, BRAND_TEXTURE % brand).replace('<i3D name="depot"', '<i3D name="depot_%s"' % brand)
        with open(os.path.join(I3D_DIR, "depot_%s.i3d" % brand), "w", encoding="iso-8859-1", newline="") as f:
            f.write(out)
    maps = mappings(tree.getroot().find("Scene"))
    os.makedirs(os.path.join(ROOT, "build"), exist_ok=True)
    with open(os.path.join(ROOT, "build", "i3d_mappings.json"), "w") as f:
        json.dump(maps, f, indent=1)
    print("i3d ok: %s, %d nodes mapped, buildings: %s" % (os.path.basename(SOURCE), len(maps), ", ".join(L.BRANDS)))


if __name__ == "__main__":
    main()
