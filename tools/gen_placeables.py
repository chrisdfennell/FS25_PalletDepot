"""Writes the two placeable XMLs (Food & Drinks, Textiles & Goods) into placeables/.

Inputs: tools/layout.py (AutoDrive route), build/products.json (tools/products.py) and
build/i3d_mappings.json (tools/finish_i3d.py), so production lines, triggers and i3d nodes always agree.

    python tools/gen_placeables.py
"""
import json
import os
import sys
from xml.sax.saxutils import quoteattr

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import layout as L  # noqa: E402

ROOT = os.path.dirname(HERE)
PRICE = 50000
# no daily upkeep (user's decision, 2026-10-26)
CAPACITY = 1000000                # the most a depot can hold; PalletDepotOptions.lua can lower it per depot
CYCLES_PER_HOUR = 1000          # litres moved per hour and line (1 L in -> 1 L out)
WALL_LIGHT = "$data/shared/assets/lights/lizard/buildings/industrialWallLight.xml"
SELLING_STATION = 'appearsOnStats="false" supportsExtension="false" allowMissions="false" hideFromPricesMenu="true"'

ITEMS = {   # store item: (brand / i3d, l10n key of the shop name)
    "food": ("food", "shopItem_depotFood"),
    "goods": ("goods", "shopItem_depotGoods"),
}

# nodes the XML references (all must exist in the exported i3d)
MAPPED = ["palletDepot", "clearAreaStart01", "clearAreaWidth01", "clearAreaHeight01", "levelAreaStart01",
          "levelAreaWidth01", "levelAreaHeight01", "paintAreaStart01", "paintAreaWidth01", "paintAreaHeight01",
          "paintAreaStart02", "paintAreaWidth02", "paintAreaHeight02", "indoorAreaStart01", "indoorAreaWidth01",
          "indoorAreaHeight01", "testAreaStart01", "testAreaEnd01", "tipOcclusionUpdateAreaStart01",
          "tipOcclusionUpdateAreaEnd01", "infoTrigger", "playerTrigger", "playerTriggerMarker", "sellingStation",
          "unloadTrigger", "unloadTriggerMarker", "unloadAINode", "palletSpawner", "loadMarker",
          "warningStripes", "stock"] + [name for name, _, _ in L.WALL_LIGHTS]


def door_nodes():
    names = []
    for wall, _, _, _ in L.DOORS:
        n = L.door_name(wall)
        names += [n + "Curtain", n + "Bar", n + "Trigger"] + [n + "Col%d" % (i + 1) for i in range(L.DOOR_SLICES)]
    return names


def animated_doors():
    """Roller doors: the curtain rolls up (scaled in y about its top), the bottom bar and the collision
    slices rise; opened and closed with the base game's door key at a trigger on either side."""
    def part(node, attr, closed, opened):
        return '''                <part node="%s">
                    <keyFrame time="0" %s="%s"/>
                    <keyFrame time="1" %s="%s"/>
                </part>
''' % (node, attr, closed, attr, opened)
    out = []
    for wall, _, _, h in L.DOORS:
        n = L.door_name(wall)
        step = h / L.DOOR_SLICES
        parts = [part(n + "Curtain", "scale", "1 1 1", "1 %.3f 1" % L.DOOR_ROLLED),
                 part(n + "Bar", "translation", "0 0 0", "0 %.3f 0" % (h * (1.0 - L.DOOR_ROLLED)))]
        parts += [part(n + "Col%d" % (i + 1), "translation", "0 %.3f 0" % (i * step), "0 %.3f 0" % h)
                  for i in range(L.DOOR_SLICES)]
        out.append('''        <animatedObject saveId="%(n)s">
            <animation duration="%(t).1f">
%(parts)s            </animation>
            <controls triggerNode="%(n)sTrigger" posAction="ACTIVATE_HANDTOOL" posText="action_openGate" negText="action_closeGate"/>
            <sounds>
                <moving linkNode="%(n)sCurtain" template="slidingGateMetalLoop"/>
                <posEnd linkNode="%(n)sCurtain" template="slidingGateMetalOpen"/>
                <negEnd linkNode="%(n)sCurtain" template="slidingGateMetalClose"/>
            </sounds>
        </animatedObject>
''' % dict(n=n, t=L.DOOR_OPEN_SECONDS, parts="".join(parts)))
    return "".join(out)


def spawn_places():
    """Both lanes on the ground first, then both 1.5 m up (see build_warehouse.py)."""
    return [("palletAreaStart%02d" % i, "palletAreaEnd%02d" % i) for i in range(1, 2 * len(L.SPAWN_LANE_ZS) + 1)]


def pallet_triggers():
    return ["palletTrigger%02d" % (i + 1) for i in range(L.PALLET_TRIGGER_COLUMNS * L.PALLET_TRIGGER_LEVELS)]


def autodrive():
    """Drive-through lane over the front pad (+x) and the truck lane behind the pickup lanes (-x)."""
    xs = [-24, -16, -8, 0, 8, 16, 24]
    pts = [(x, L.PAD_CENTER[1]) for x in xs] + [(x, L.TRUCK_LANE_Z) for x in reversed(xs)]
    n = len(xs)
    out, inc = [], []
    for i in range(len(pts)):
        first, last = i % n == 0, i % n == n - 1
        out.append("-1" if last else str(i + 2))
        inc.append("-1" if first else str(i))
    fmt = lambda v: ("%g" % v)                               # noqa: E731
    return """    <!-- AutoDrive imports this route when the building is placed: a lane over the unload pad at the front
         and one behind the pallet pickup lanes at the back. Connect their ends to your network. -->
    <AutoDrive>
        <waypoints>
            <x>%s</x>
            <y>%s</y>
            <z>%s</z>
            <out>%s</out>
            <incoming>%s</incoming>
            <flags>%s</flags>
        </waypoints>
        <!-- AutoDrive checks for wayPoints; the game matches element names without regard to case, so the data must
             come first or "waypoints.x" would be looked up in this empty marker -->
        <wayPoints/>
        <mapmarker>
            <mm1><id>%d</id><name>Depot unload</name></mm1>
            <mm2><id>%d</id><name>Depot pickup</name></mm2>
        </mapmarker>
    </AutoDrive>
""" % (",".join(fmt(x) for x, _ in pts), ",".join("0" for _ in pts), ",".join(fmt(z) for _, z in pts),
       ";".join(out), ";".join(inc), ",".join("0" for _ in pts), n // 2 + 1, n + n // 2 + 1)


def production(line):
    fill = line["fillType"]
    # FedMods texts live in the Fed mods' own environment, so the XML cannot name those lines;
    # scripts/PalletDepotLineNames.lua renames every line to its fill type's title at load
    name = line["title"] if line["source"] == "base" else "$l10n_depot_productLine"
    return ('            <production id=%s name=%s cyclesPerHour="%d" costsPerActiveHour="0">\n'
            '                <inputs><input fillType="%s" amount="1"/></inputs>\n'
            '                <outputs><output fillType="%s" amount="1"/></outputs>\n'
            '            </production>\n') % (quoteattr(fill.lower()), quoteattr(name), CYCLES_PER_HOUR, fill, fill)


def placeable(item, lines, mappings):
    brand, shop_key = ITEMS[item]
    fill_types = " ".join(l["fillType"] for l in lines)
    triggers = "".join('            <palletTrigger triggerNode="%s" aiNode="unloadAINode" autoUnload="true" '
                       'autoUnloadStrapped="true" fillTypes="%s"/>\n' % (t, fill_types) for t in pallet_triggers())
    lights = "".join('        <sharedLight filename="%s" linkNode="%s" groupIndex="1"/>\n' % (WALL_LIGHT, name)
                     for name, _, _ in L.WALL_LIGHTS)
    nodes = MAPPED + door_nodes() + pallet_triggers() + [n for pair in spawn_places() for n in pair]
    missing = [n for n in nodes if n not in mappings]
    if missing:
        sys.exit("nodes missing from the exported i3d: " + ", ".join(missing))
    i3d_mappings = "".join('        <i3dMapping id="%s" node="%s"/>\n' % (n, mappings[n]) for n in nodes)
    return """<?xml version="1.0" encoding="utf-8" standalone="no" ?>
<!-- Generated by tools/gen_placeables.py, do not edit by hand. -->
<placeable type="productionPoint" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:noNamespaceSchemaLocation="../../../../shared/xml/schema/placeable.xsd">
    <storeData>
        <name>$l10n_%(shop)s</name>
        <functions>
            <function>$l10n_function_palletDepot</function>
        </functions>
        <image>store/store_depot_%(brand)s.dds</image>
        <price>%(price)d</price>
        <lifetime>1000</lifetime>
        <rotation>0</rotation>
        <brand>NONE</brand>
        <species>placeable</species>
        <category>productionPoints</category>
        <brush>
            <type>placeable</type>
            <category>production</category>
            <tab>factories</tab>
        </brush>
    </storeData>

    <base>
        <filename>i3d/depot_%(brand)s.i3d</filename>
        <canBeRenamed>true</canBeRenamed>
    </base>

    <placement useRandomYRotation="false" useManualYRotation="true">
        <testAreas>
            <testArea startNode="testAreaStart01" endNode="testAreaEnd01"/>
        </testAreas>
        <sounds>
            <place template="medImp"/>
        </sounds>
    </placement>

    <clearAreas>
        <clearArea startNode="clearAreaStart01" widthNode="clearAreaWidth01" heightNode="clearAreaHeight01"/>
    </clearAreas>

    <leveling requireLeveling="true" maxSmoothDistance="10" maxSlope="75" maxEdgeAngle="30">
        <levelAreas>
            <levelArea startNode="levelAreaStart01" widthNode="levelAreaWidth01" heightNode="levelAreaHeight01" groundType="asphalt"/>
        </levelAreas>
        <paintAreas>
            <paintArea startNode="paintAreaStart01" widthNode="paintAreaWidth01" heightNode="paintAreaHeight01" groundType="asphalt"/>
            <paintArea startNode="paintAreaStart02" widthNode="paintAreaWidth02" heightNode="paintAreaHeight02" groundType="asphalt"/>
        </paintAreas>
    </leveling>

    <indoorAreas>
        <indoorArea startNode="indoorAreaStart01" widthNode="indoorAreaWidth01" heightNode="indoorAreaHeight01"/>
    </indoorAreas>

    <tipOcclusionUpdateAreas>
        <tipOcclusionUpdateArea startNode="tipOcclusionUpdateAreaStart01" endNode="tipOcclusionUpdateAreaEnd01"/>
    </tipOcclusionUpdateAreas>

    <ai>
        <updateAreas>
            <updateArea startNode="tipOcclusionUpdateAreaStart01" endNode="tipOcclusionUpdateAreaEnd01"/>
        </updateAreas>
    </ai>

    <infoTrigger triggerNode="infoTrigger"/>

    <animatedObjects>
%(doors)s    </animatedObjects>

    <lights>
        <group weatherRequiredFlags="NIGHT"/>
%(lights)s    </lights>

    <hotspots>
        <hotspot type="PRODUCTION_POINT" linkNode="unloadTriggerMarker" teleportNode="unloadTriggerMarker"/>
    </hotspots>

    <triggerMarkers>
        <triggerMarker node="warningStripes"/>
        <triggerMarker node="playerTriggerMarker" filename="$data/shared/assets/marker/markerIconWrench.i3d" adjustToGround="true"/>
        <triggerMarker node="unloadTriggerMarker" filename="$data/shared/assets/marker/markerIconUnload.i3d" adjustToGround="true"/>
        <triggerMarker node="loadMarker" filename="$data/shared/assets/marker/markerIconLoad.i3d" adjustToGround="true"/>
    </triggerMarkers>

    <productionPoint>
        <productions sharedThroughputCapacity="false">
%(productions)s        </productions>

        <storage isExtension="false" fillLevelSyncThreshold="0">
%(capacities)s        </storage>

        <sellingStation node="sellingStation" %(station)s>
            <unloadTrigger exactFillRootNode="unloadTrigger" aiNode="unloadAINode" fillTypes="%(fillTypes)s"/>
%(triggers)s        </sellingStation>

        <palletSpawner node="palletSpawner">
            <spawnPlaces>
%(spawnPlaces)s            </spawnPlaces>
        </palletSpawner>

        <playerTrigger node="playerTrigger"/>
    </productionPoint>

    <i3dMappings>
%(mappings)s    </i3dMappings>

%(autodrive)s</placeable>
""" % dict(shop=shop_key, brand=brand, price=PRICE, lights=lights,
           productions="".join(production(l) for l in lines),
           capacities="".join('            <capacity fillType="%s" capacity="%d"/>\n' % (l["fillType"], CAPACITY)
                              for l in lines),
           spawnPlaces="".join('                <spawnPlace startNode="%s" endNode="%s"/>\n' % p for p in spawn_places()),
           station=SELLING_STATION, fillTypes=fill_types, triggers=triggers, mappings=i3d_mappings,
           autodrive=autodrive(), doors=animated_doors())


def main():
    products = json.load(open(os.path.join(ROOT, "build", "products.json"), encoding="utf-8"))
    mappings = json.load(open(os.path.join(ROOT, "build", "i3d_mappings.json"), encoding="utf-8"))
    os.makedirs(os.path.join(ROOT, "placeables"), exist_ok=True)
    for item in ITEMS:
        path = os.path.join(ROOT, "placeables", "depot_%s.xml" % item)
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(placeable(item, products[item], mappings))
        print("wrote", os.path.relpath(path, ROOT), len(products[item]), "lines")


if __name__ == "__main__":
    main()
