"""Builds the product lists of the four Pallet Depot buildings from game data and tools/product_map.csv.

Sources (read as data only):
  * the game's data/maps/maps_fillTypes.xml: every fill type with a <pallet> entry
  * the FedMods packs in the mods folder (standard and ProEdition): their pallet fill types; a Fed
    building only gets Fed products that BOTH editions define, so it works with either edition

tools/product_map.csv is the reviewable mapping table: one row per pallet fill type with its building
(food = Food & Drinks, goods = Textiles & Goods, or exclude) and an English name. The English name is only the sort key (lines are listed A-Z
by English name); in game every line shows the fill type's own translated title.

The build fails when a pallet fill type is missing from the table, when a table row matches no source,
or when a building would get more than 255 production lines (the game syncs line indices as one byte).

    python tools/products.py          -> build/products.json
"""
import csv
import json
import os
import sys
import xml.etree.ElementTree as ET
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
GAME_FILLTYPES = r"C:\Program Files (x86)\Steam\steamapps\common\Farming Simulator 25\data\maps\maps_fillTypes.xml"
MODS = os.path.join(os.path.expanduser("~"), "OneDrive", "Documents", "My Games", "FarmingSimulator2025", "mods")
FED_EDITIONS = {
    "standard": ["FS25_Fed_Mods_Pack.zip", "FS25_Fed_Produktions_Pack.zip"],
    "pro": ["Fed_Mods_Pack_ProEdition.zip", "Fed_Produktions_Pack_ProEdition.zip"],
}
MAX_LINES = 255
BUILDINGS = {   # store item -> (building of the mapping table, includes Fed products); Fed lines are
    "food": ("food", True),     # dropped at load when the Fed packs are missing (PalletDepotOptionalProducts.lua)
    "goods": ("goods", True),
}


def pallet_types(xml_bytes):
    root = ET.fromstring(xml_bytes.decode("utf-8-sig"))
    return {ft.get("name").upper(): ft.get("title") for ft in root.iter("fillType") if ft.find("pallet") is not None}


def load_sources():
    base = pallet_types(open(GAME_FILLTYPES, "rb").read())
    editions = {}
    for edition, zips in FED_EDITIONS.items():
        types = {}
        for name in zips:
            with zipfile.ZipFile(os.path.join(MODS, name)) as zf:
                types.update(pallet_types(zf.read("fillTypes.xml")))
        editions[edition] = types
    shared = set.intersection(*(set(t) for t in editions.values()))
    fed = {n: editions["standard"][n] for n in sorted(shared - set(base))}
    return base, fed


def main():
    base, fed = load_sources()
    rows = list(csv.DictReader(open(os.path.join(HERE, "product_map.csv"), encoding="utf-8")))
    table = {r["fillType"]: r for r in rows}
    errors = []
    if len(table) != len(rows):
        errors.append("duplicate rows in product_map.csv")
    for source, types in (("base", base), ("fed", fed)):
        for name in types:
            row = table.get(name)
            if row is None:
                errors.append("%s pallet fill type %s is not in product_map.csv" % (source, name))
            elif row["source"] != source:
                errors.append("%s: source should be %s" % (name, source))
    for name, row in table.items():
        if name not in base and name not in fed:
            errors.append("%s is in product_map.csv but in no source (game update or Fed edition change?)" % name)
        if row["building"] not in ("food", "goods", "exclude"):
            errors.append("%s: unknown building %r" % (name, row["building"]))

    out = {}
    for item, (building, with_fed) in BUILDINGS.items():
        lines = []
        for name, row in table.items():
            if row["building"] != building or (row["source"] == "fed" and not with_fed):
                continue
            title = (base if row["source"] == "base" else fed).get(name)
            lines.append({"fillType": name, "title": title, "english": row["english"], "source": row["source"]})
        lines.sort(key=lambda l: (l["english"].casefold(), l["fillType"]))
        if len(lines) > MAX_LINES:
            errors.append("%s has %d production lines, the limit is %d" % (item, len(lines), MAX_LINES))
        out[item] = lines

    if errors:
        sys.exit("product lists failed:\n  " + "\n  ".join(errors))
    os.makedirs(os.path.join(ROOT, "build"), exist_ok=True)
    with open(os.path.join(ROOT, "build", "products.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1)
    excluded = sum(1 for r in rows if r["building"] == "exclude")
    print("products: " + ", ".join("%s %d" % (k, len(v)) for k, v in out.items()) + " (excluded %d)" % excluded)


if __name__ == "__main__":
    main()
