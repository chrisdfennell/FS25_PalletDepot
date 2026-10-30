-- Pallet Depot: loaded pallets on the racks that grow with the stock.
--
-- The building has 84 static pallet units (node "stock", children stock01..stock84, bottom level first). Every few
-- seconds each depot shows one unit per LITERS_PER_UNIT of total stock, rounded up. Purely visual, every client.

PalletDepotStock = {}
PalletDepotStock.POLL_INTERVAL = 5000      -- ms
PalletDepotStock.LITERS_PER_UNIT = 2000
PalletDepotStock.NODE_NAME = "stock"

function PalletDepotStock:loadMap()
    self.timer = PalletDepotStock.POLL_INTERVAL   -- run on the first update
    self.racks = {}   -- productionPoint -> {units = {...}, shown}
end

function PalletDepotStock:getRacks(productionPoint)
    local racks = self.racks[productionPoint]
    if racks == nil then
        racks = {units = {}, shown = -1}
        local placeable = productionPoint.owningPlaceable
        local rootNode = placeable ~= nil and placeable.rootNode or nil
        local node = rootNode ~= nil and PalletDepot.findChild(rootNode, PalletDepotStock.NODE_NAME, 2) or nil
        if node ~= nil then
            for i = 0, getNumOfChildren(node) - 1 do
                table.insert(racks.units, getChildAt(node, i))
            end
        else
            Logging.info("[%s] Stock: no '%s' node in %s", PalletDepot.modName, PalletDepotStock.NODE_NAME,
                tostring(placeable ~= nil and placeable.configFileName))
        end
        self.racks[productionPoint] = racks
    end
    return racks
end

function PalletDepotStock:refresh()
    local seen = {}
    for _, productionPoint in ipairs(PalletDepot.getDepots()) do
        seen[productionPoint] = true
        local racks = self:getRacks(productionPoint)
        if #racks.units > 0 then
            local liters = PalletDepot.getTotalStock(productionPoint)
            local shown = math.min(#racks.units, math.ceil(liters / PalletDepotStock.LITERS_PER_UNIT))
            if shown ~= racks.shown then
                for i, unit in ipairs(racks.units) do
                    setVisibility(unit, i <= shown)
                end
                racks.shown = shown
            end
        end
    end
    for productionPoint in pairs(self.racks) do      -- forget depots that were sold or removed
        if not seen[productionPoint] then
            self.racks[productionPoint] = nil
        end
    end
end

function PalletDepotStock:update(dt)
    if g_client == nil then
        return
    end
    self.timer = self.timer + dt
    if self.timer >= PalletDepotStock.POLL_INTERVAL then
        self.timer = 0
        self:refresh()
    end
end

function PalletDepotStock:deleteMap()
    self.racks = {}
end

addModEventListener(PalletDepotStock)
