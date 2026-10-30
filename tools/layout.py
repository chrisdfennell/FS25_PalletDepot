"""Shared layout of the Pallet Depot building.

All values are in metres, in i3d coordinates of the placeable root:
x runs along the long front wall, y is up, +z points out of the open loading front.
The Blender model script, the i3d finishing step and the placeable XML generator all read this file,
so geometry, triggers and XML nodes always agree.
"""
import math

# --- hall -------------------------------------------------------------------------------------------
HALL_X = 15.0                      # half length (hall is 30 m long)
HALL_Z = 6.5                       # half depth (hall is 13 m deep)
EAVE_Y = 7.0
ROOF_PITCH_DEG = 17.0
RIDGE_Y = EAVE_Y + HALL_Z * math.tan(math.radians(ROOF_PITCH_DEG))
ROOF_THICK = 0.12
EAVE_OVERHANG = 0.35
GABLE_OVERHANG = 0.25
WALL_THICK = 0.06                  # cladding, outer face on the hall outline
FLOOR_Y = 0.05                     # top of the interior slab
PLINTH_Y = 0.5                     # concrete plinth height outside the walls

FRAME_XS = [-15.0, -9.0, -3.0, 3.0, 9.0, 15.0]   # portal frames (6 m bays)
COLUMN = 0.3                                     # column / rafter section
COLUMN_INSET = WALL_THICK + COLUMN / 2           # column centre inside the wall line

# open loading front between the two outer frames, fascia above it
FRONT_OPEN_X = 9.0
FRONT_OPEN_Y = 5.5

# roller doors: (wall, centre along the wall, width, height)
DOORS = [
    ("back", 0.0, 4.0, 4.5),
    ("left", 0.0, 4.0, 4.5),
    ("right", 0.0, 4.0, 4.5),
]

DOOR_OPEN_SECONDS = 5.0
DOOR_ROLLED = 0.03                 # share of the curtain still showing under the coil box when open
DOOR_SLICES = 3                    # collision slices per door; open, they stack above the opening


def door_name(wall):
    """Node name prefix of the roller door in a wall: doorBack, doorLeft, doorRight."""
    return "door" + wall[0].upper() + wall[1:]


# windows: (wall, centre along the wall, bottom y, width, height)
WINDOWS = [
    ("back", -12.0, 4.6, 3.0, 1.2), ("back", -6.0, 4.6, 3.0, 1.2),
    ("back", 6.0, 4.6, 3.0, 1.2), ("back", 12.0, 4.6, 3.0, 1.2),
    ("front", -12.0, 2.0, 2.4, 1.2), ("front", 12.0, 2.0, 2.4, 1.2),
    ("left", -4.6, 2.0, 1.8, 1.2), ("left", 4.6, 2.0, 1.8, 1.2),
    ("right", -4.6, 2.0, 1.8, 1.2), ("right", 4.6, 2.0, 1.8, 1.2),
]

ACCENT_BAND_Y = (6.45, 6.75)       # coloured band around the hall below the eaves

# --- canopy over the unload pad (cantilevered, no posts in the truck lane) ---------------------------
CANOPY_X = (-9.0, 9.0)
CANOPY_Z = (HALL_Z, 12.5)
CANOPY_Y_WALL = 5.85               # top surface at the wall
CANOPY_Y_TIP = 5.65                # top surface at the tip (falls towards the front)
CANOPY_THICK = 0.15
CANOPY_BEAM_XS = [-9.0, -3.0, 3.0, 9.0]
SIGN_X = (-4.0, 4.0)               # FOOD / GOODS board on the canopy tip
SIGN_Y = (5.7, 6.9)

# --- front unload pad (trucks pull up alongside, parallel to the front wall) ------------------------
PAD_X = (-7.0, 7.0)                # 14 m
PAD_Z = (7.5, 12.3)                # 4.8 m
PAD_CENTER = ((PAD_X[0] + PAD_X[1]) / 2, (PAD_Z[0] + PAD_Z[1]) / 2)
PALLET_TRIGGER_COLUMNS = 3         # real-size boxes, never scaled: 3 along x ...
PALLET_TRIGGER_LEVELS = 3          # ... times 3 stacked 1 m levels = 14 x 4.8 x 3 m
PALLET_TRIGGER_SIZE = ((PAD_X[1] - PAD_X[0]) / PALLET_TRIGGER_COLUMNS, 1.0, PAD_Z[1] - PAD_Z[0])
UNLOAD_TRIGGER_Y = -0.45           # exactFillRootNode box, mostly below ground

# wrench (production menu) trigger and info trigger
PLAYER_TRIGGER_POS = (-12.0, 0.0, 9.0)
PLAYER_TRIGGER_SIZE = (2.0, 2.0, 2.0)
INFO_TRIGGER_SIZE = (2 * HALL_X - 1.0, 3.0, 2 * HALL_Z - 1.0)

# --- back pickup area: two spawner lanes parallel to the back wall, 7 and 9 m out --------------------
SPAWN_LANE_X = (-6.0, 6.0)
SPAWN_LANE_ZS = [-(HALL_Z + 7.0), -(HALL_Z + 9.0)]
SPAWN_LANE_HALF_WIDTH = 1.1
SPAWN_STACK_Y = 1.5                # second spawn place per lane, 1.5 m up: pallets stack two high
LOAD_MARKER_POS = (7.6, 0.0, (SPAWN_LANE_ZS[0] + SPAWN_LANE_ZS[1]) / 2)
TRUCK_LANE_Z = -(HALL_Z + 13.0)    # centre of the truck lane behind the pickup lanes

# --- placement areas (building plus both aprons) ----------------------------------------------------
AREA_X = (-16.0, 16.0)
AREA_Z = (-22.0, 13.5)
AREA_HEIGHT = 10.0

# --- lights -----------------------------------------------------------------------------------------
# shared base-game wall lights: (name, position, y rotation in degrees; the light faces its local +z)
WALL_LIGHTS = [
    ("wallLightFrontLeft", (-12.0, 4.6, HALL_Z + 0.05), 0.0),
    ("wallLightFrontRight", (12.0, 4.6, HALL_Z + 0.05), 0.0),
    ("wallLightBackLeft", (-3.0, 4.9, -HALL_Z - 0.05), 180.0),
    ("wallLightBackRight", (3.0, 4.9, -HALL_Z - 0.05), 180.0),
    ("wallLightLeft", (-HALL_X - 0.05, 4.9, 2.8), -90.0),
    ("wallLightRight", (HALL_X + 0.05, 4.9, -2.8), 90.0),
]
# point lights inside the hall and under the canopy (night only)
POINT_LIGHTS = [(-9.0, 6.2, -1.5), (0.0, 6.2, -1.5), (9.0, 6.2, -1.5),
                (-4.5, 5.2, 9.5), (4.5, 5.2, 9.5)]

# --- pallet racking with visible stock --------------------------------------------------------------
RACK_DEPTH = 1.1
RACK_BAY = 2.8                     # two pallet places per bay
RACK_LEVELS_Y = [FLOOR_Y, 1.95, 3.75]   # where pallets stand (floor, beam tops)
RACK_HEIGHT = 5.4
# rows: (name, z of the rack's front edge, list of (x start, number of bays))
RACK_ROWS = [
    ("rowFront", -1.3, [(-10.6, 3), (2.2, 3)]),  # gap: clear aisle from the open front to the back door
    ("rowBack", -5.0, [(-13.4, 4), (2.2, 4)]),   # gap for the back roller door
]
STOCK_LITRES_PER_PALLET = 2000

# --- decoration: empty pallets, skip, extinguishers ---------------------------------------------------
# pallet stacks: (x, z, pallets, long side along x, inside the hall)
DECOR_STACKS = [
    (-14.25, 4.7, 6, False, True), (14.25, 4.7, 4, False, True),
    (-3.75, -HALL_Z - 0.62, 5, True, False), (-13.9, HALL_Z + 0.62, 3, True, False),
]
# pallets leaning against a long wall: (x, wall z, +1 = pallet on the +z side of the wall, inside the hall)
DECOR_LEANING = [
    (-11.6, HALL_Z - WALL_THICK, -1, True), (11.6, HALL_Z - WALL_THICK, -1, True),
    (3.75, -HALL_Z, -1, False), (5.1, -HALL_Z, -1, False),
    (-10.7, HALL_Z, 1, False),             # outside the front wall, left of the canopy
]
SKIP_POS = (11.6, -HALL_Z - 1.6)    # waste skip outside the back right corner, long side along x
# more props (x, z); outside ones get collision
BENCH_POS = (11.3, HALL_Z + 0.55)           # outside the front wall, right of the canopy
BIN_XS = [13.1, 14.0]                       # wheelie bins next to the bench (z like the bench)
IBC_POS = (-12.6, -HALL_Z - 0.75)           # IBC tank on its pallet behind the hall, left
BARRELS_POS = (-10.3, -HALL_Z - 0.75)       # four barrels next to it
WORKBENCH_Z = (2.4, 4.0)                    # along the right wall inside
CABINET_Z = (2.4, 3.4)                      # along the left wall inside
PALLET_JACK_POS = (3.2, 2.8)                # inside next to the walkway
EXTINGUISHER_XS = [-FRONT_OPEN_X, FRONT_OPEN_X]   # on the inner face of the front columns


def rack_slots():
    """Pallet places in fill order: bottom level first, front row before back row, left to right.

    Returns a list of (x, y, z) positions of the bottom centre of each pallet.
    """
    slots = []
    for y in RACK_LEVELS_Y:
        for _, front_z, segments in RACK_ROWS:
            z = front_z - RACK_DEPTH / 2
            for x0, bays in segments:
                for b in range(bays):
                    bx = x0 + b * RACK_BAY
                    slots.append((bx + RACK_BAY * 0.25, y, z))
                    slots.append((bx + RACK_BAY * 0.75, y, z))
    return slots


# --- texture regions (u0, v0, u1, v1; v from the bottom) ---------------------------------------------
# depot_paint atlas: flat painted / galvanised parts
PAINT_SWATCHES = {
    "frame":     (0.00, 0.75, 0.25, 1.00),   # dark grey structural steel
    "galv":      (0.25, 0.75, 0.50, 1.00),   # galvanised gutters, pipes, tie rods
    "rackPost":  (0.50, 0.75, 0.75, 1.00),   # blue rack uprights
    "rackBeam":  (0.75, 0.75, 1.00, 1.00),   # orange rack beams
    "trim":      (0.00, 0.50, 0.25, 0.75),   # light grey flashing / trims
    "doorFrame": (0.25, 0.50, 0.50, 0.75),   # door housings and guides
    "rubber":    (0.50, 0.50, 0.75, 0.75),   # black seals, bumpers
    "yellow":    (0.75, 0.50, 1.00, 0.75),   # safety yellow
    "red":       (0.00, 0.25, 0.25, 0.50),   # fire extinguishers and signs
    "white":     (0.25, 0.25, 0.50, 0.50),   # sign faces
}
# depot_brand atlas (one texture per building): sign face and accent colour
BRAND_SIGN = (0.0, 0.25, 1.0, 1.0)
BRAND_ACCENT = (0.05, 0.04, 0.20, 0.20)
# depot_stock atlas: pallet wood and goods variants
STOCK_REGIONS = {
    "pallet":  (0.0, 0.875, 1.0, 1.0),
    "boxes":   (0.0, 0.4375, 0.5, 0.875),
    "sacks":   (0.5, 0.4375, 1.0, 0.875),
    "crates":  (0.0, 0.0, 0.5, 0.4375),
    "wrapped": (0.5, 0.0, 1.0, 0.4375),
}
STOCK_VARIANTS = ["boxes", "sacks", "crates", "wrapped"]

# tiling sizes of the tiling materials (metres covered by one texture repeat)
TILE = {"wall": (2.0, 2.0), "roof": (2.0, 2.0), "concrete": (4.0, 4.0), "window": (1.0, 1.0)}

BRANDS = {
    "food":  {"word": "FOOD",  "accent": (46, 140, 62)},    # green
    "goods": {"word": "GOODS", "accent": (36, 98, 178)},    # blue
}
