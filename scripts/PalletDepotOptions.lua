-- Pallet Depot: options per depot (Settings tab of the productions window, with a depot selected).
--
--   capacity   storage capacity per product: 100,000 / 500,000 / 1,000,000 L (the placeable XML holds the maximum)
-- (the pallet size is PalletDepotPallets, for every production)
-- The server owns the options: it saves them with the savegame (palletDepotOptions.xml, keyed by the building's
-- unique id), applies them and sends every change to all clients; joining clients get them with the production
-- point's join data. Lowering the capacity keeps stock above it; the depot just takes no more of that product.

PalletDepotOptions = {}
PalletDepotOptions.FILENAME = "palletDepotOptions.xml"
PalletDepotOptions.CAPACITIES = {100000, 500000, 1000000}
PalletDepotOptions.data = {}        -- productionPoint -> {capacity}

function PalletDepotOptions.defaults()
    return {capacity = 1000000}
end

function PalletDepotOptions.get(productionPoint)
    return PalletDepotOptions.data[productionPoint] or PalletDepotOptions.defaults()
end

-- --- applying (server and clients) ---------------------------------------------------------------------

function PalletDepotOptions.apply(productionPoint)
    local options = PalletDepotOptions.get(productionPoint)
    local storage = productionPoint.storage
    if storage ~= nil and storage.capacities ~= nil then
        for fillType in pairs(storage.capacities) do
            storage.capacities[fillType] = options.capacity
        end
    end
end

local function store(productionPoint, capacity)
    PalletDepotOptions.data[productionPoint] = {capacity = capacity}
    PalletDepotOptions.apply(productionPoint)
end

-- --- editing -------------------------------------------------------------------------------------------

function PalletDepotOptions.request(productionPoint, capacity)
    store(productionPoint, capacity)        -- shown at once, the server confirms
    if g_server ~= nil then
        g_server:broadcastEvent(PalletDepotOptionsEvent.new(productionPoint, capacity))
    else
        g_client:getServerConnection():sendEvent(PalletDepotOptionsEvent.new(productionPoint, capacity))
    end
end

PalletDepotOptionsEvent = {}
local PalletDepotOptionsEvent_mt = Class(PalletDepotOptionsEvent, Event)
InitEventClass(PalletDepotOptionsEvent, "PalletDepotOptionsEvent")

function PalletDepotOptionsEvent.emptyNew()
    return Event.new(PalletDepotOptionsEvent_mt)
end

function PalletDepotOptionsEvent.new(productionPoint, capacity)
    local self = PalletDepotOptionsEvent.emptyNew()
    self.productionPoint = productionPoint
    self.capacity = capacity
    return self
end

function PalletDepotOptionsEvent:readStream(streamId, connection)
    self.productionPoint = NetworkUtil.readNodeObject(streamId)
    self.capacity = streamReadInt32(streamId)
    self:run(connection)
end

function PalletDepotOptionsEvent:writeStream(streamId, connection)
    NetworkUtil.writeNodeObject(streamId, self.productionPoint)
    streamWriteInt32(streamId, self.capacity)
end

function PalletDepotOptionsEvent:run(connection)
    local productionPoint = self.productionPoint
    if productionPoint == nil then
        return
    end
    if not connection:getIsServer() then
        -- a client's change arrives at the server: only players allowed to manage this farm's productions
        if not g_currentMission:getHasPlayerPermission("manageProductions", connection, productionPoint:getOwnerFarmId()) then
            return
        end
        store(productionPoint, self.capacity)
        g_server:broadcastEvent(PalletDepotOptionsEvent.new(productionPoint, self.capacity))
    else
        store(productionPoint, self.capacity)
    end
end

-- --- join synchronisation -------------------------------------------------------------------------------

function PalletDepotOptions.writeStream(productionPoint, streamId, connection)
    if connection:getIsServer() then
        return
    end
    local options = PalletDepotOptions.data[productionPoint]
    if streamWriteBool(streamId, options ~= nil) then
        streamWriteInt32(streamId, options.capacity)
    end
end

function PalletDepotOptions.readStream(productionPoint, streamId, connection)
    if not connection:getIsServer() then
        return
    end
    if streamReadBool(streamId) then
        store(productionPoint, streamReadInt32(streamId))
    end
end

ProductionPoint.writeStream = Utils.appendedFunction(ProductionPoint.writeStream, PalletDepotOptions.writeStream)
ProductionPoint.readStream = Utils.appendedFunction(ProductionPoint.readStream, PalletDepotOptions.readStream)
if ProductionPoint.delete ~= nil then
    ProductionPoint.delete = Utils.prependedFunction(ProductionPoint.delete, function(productionPoint)
        PalletDepotOptions.data[productionPoint] = nil
    end)
end

-- --- savegame (server) ---------------------------------------------------------------------------------

local function getFilename()
    local dir = g_currentMission ~= nil and g_currentMission.missionInfo ~= nil and g_currentMission.missionInfo.savegameDirectory or nil
    return dir ~= nil and (dir .. "/" .. PalletDepotOptions.FILENAME) or nil
end

local function getKey(productionPoint)
    local placeable = productionPoint.owningPlaceable
    return placeable ~= nil and placeable.getUniqueId ~= nil and placeable:getUniqueId() or nil
end

function PalletDepotOptions.save()
    local filename = getFilename()
    if filename == nil or g_server == nil then
        return
    end
    local xmlId = createXMLFile("palletDepotOptions", filename, "palletDepotOptions")
    local i = 0
    for productionPoint, options in pairs(PalletDepotOptions.data) do
        local placeableKey = getKey(productionPoint)
        if placeableKey ~= nil then
            local key = string.format("palletDepotOptions.depot(%d)", i)
            setXMLString(xmlId, key .. "#placeable", placeableKey)
            setXMLInt(xmlId, key .. "#capacity", options.capacity)
            i = i + 1
        end
    end
    saveXMLFile(xmlId)
    delete(xmlId)
end

function PalletDepotOptions.load()
    local filename = getFilename()
    if filename == nil or g_server == nil or not fileExists(filename) then
        return
    end
    local byKey = {}
    for _, productionPoint in ipairs(g_currentMission.productionChainManager.productionPoints or {}) do
        local key = getKey(productionPoint)
        if key ~= nil then
            byKey[key] = productionPoint
        end
    end
    local xmlId = loadXMLFile("palletDepotOptions", filename)
    local i = 0
    while hasXMLProperty(xmlId, string.format("palletDepotOptions.depot(%d)", i)) do
        local key = string.format("palletDepotOptions.depot(%d)", i)
        local productionPoint = byKey[getXMLString(xmlId, key .. "#placeable") or ""]
        if productionPoint ~= nil then
            store(productionPoint, Utils.getNoNil(getXMLInt(xmlId, key .. "#capacity"), PalletDepotOptions.defaults().capacity))
            -- up to 1.0.0.24 the pallet size was saved here
            local pallet = getXMLInt(xmlId, key .. "#pallet")
            if pallet ~= nil and pallet > 0 and PalletDepotPallets.get(productionPoint) == 0 then
                PalletDepotPallets.store(productionPoint, pallet)
            end
        end
        i = i + 1
    end
    delete(xmlId)
end

FSBaseMission.saveSavegame = Utils.appendedFunction(FSBaseMission.saveSavegame, PalletDepotOptions.save)
-- not at loadMission00Finished: the buildings of the savegame are still loading then
Mission00.onStartMission = Utils.appendedFunction(Mission00.onStartMission, PalletDepotOptions.load)
