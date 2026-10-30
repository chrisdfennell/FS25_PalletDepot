# FS25 Pallet Depot

A Farming Simulator 25 mod: a pallet hall that stores your products and sends them on. Drop pallets on the unload pad at the front, then choose per product whether it stays in storage, comes out as pallets at the pickup lanes at the back, is delivered to your other productions, or is sold every full hour.

- Two shop items, each with up to 1,000,000 L storage per product: **Food & Drinks** and **Textiles & Goods**
- FedMods products are included when those packs are loaded
- Productions window (Right Shift + P) for all productions: inputs/outputs, recipes, finances, logistics, schedules, auto-management, CSV export
- Optional own 1,000 L / 5,000 L pallets for any production
- Working roller doors, no daily upkeep

Pallets only: bulk goods, field crops and bales are not accepted.

## Layout

| Path | Contents |
|---|---|
| `modDesc.xml`, `scripts/`, `gui/`, `l10n/` | Mod definition, Lua scripts, dialogs, translations |
| `placeables/`, `i3d/`, `vehicles/`, `textures/`, `store/` | Game assets that go into the zip |
| `src/` | PNG sources of the textures and store images |
| `tools/` | Python/Blender pipeline that generates the model, textures, placeables and pallets and builds the zip |

## Building

The model and textures are generated, not hand-made. `build/products.json` and `build/i3d_mappings.json` are committed, so `gen_placeables.py` works without rerunning the steps before it. The tools expect Blender 5, the GIANTS Editor 10 (for `textureTool.exe`) and the game installed at the default Steam path (see the constants at the top of each script).

```
python tools/make_textures.py                                   # textures -> src/textures, textures/*.dds
blender --background --factory-startup --python tools/build_warehouse.py
python tools/finish_i3d.py                                      # i3d checks, food/goods variants -> build/i3d_mappings.json
python tools/products.py                                        # product table -> build/products.json (scans your mods folder for FedMods)
python tools/gen_placeables.py                                  # placeables/*.xml
python tools/build_mod.py                                       # validate and zip -> build/FS25_PalletDepot.zip
```

Copy `build/FS25_PalletDepot.zip` into your FS25 `mods` folder.
