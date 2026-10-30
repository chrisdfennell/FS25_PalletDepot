-- Pallet Depot: own pallets of 1,000 L and 5,000 L for every production (Settings page of the productions window).
--
-- Each production with pickup lanes spawns either the game's pallet of each product (0) or our own pallet of 1,000 L
-- or 5,000 L (vehicles/depotPallet*.xml): for every product it already puts on pallets, and in a depot for every
-- product it stores. Our pallets take any product: their fill unit is opened to all fill types when they load, so
-- products of any map or mod fit. A production spawns once a whole pallet is in stock, so 5,000 L pallets come out
-- full.
-- The server owns the choice: it saves it with the savegame (palletDepotPallets.xml, keyed by the building's unique
-- id), applies it and sends every change to all clients; joining clients get it with the production point's join data.

PalletDepotPallets = {}
PalletDepotPallets.FILENAME = "palletDepotPallets.xml"
PalletDepotPallets.SIZES = {0, 1000, 5000}
PalletDepotPallets.FILES = {[1000] = "vehicles/depotPallet1000.xml", [5000] = "vehicles/depotPallet5000.xml"}
PalletDepotPallets.data = {}        -- productionPoint -> pallet size in liters (0 = the game's pallets)

function PalletDepotPallets.get(productionPoint)
    return PalletDepotPallets.data[productionPoint] or 0
end

local function copy(t)
    local out = {}
    for k, v in pairs(t) do
        out[k] = v
    end
    return out
end

-- true for the xml of one of our pallets (spawned or loaded from a savegame)
local function isOwnPallet(filename)
    if filename == nil or string.find(filename, PalletDepot.modName, 1, true) == nil then
        return false
    end
    for _, file in pairs(PalletDepotPallets.FILES) do
        if filename:sub(-#file) == file then
            return true
        end
    end
    return false
end

-- --- our pallets take any product ----------------------------------------------------------------------

function PalletDepotPallets.onFillUnitLoad(vehicle, savegame)
    local spec = vehicle.spec_fillUnit
    if spec == nil or spec.fillUnits == nil or not isOwnPallet(vehicle.configFileName) then
        return
    end
    for _, fillUnit in ipairs(spec.fillUnits) do
        for fillTypeIndex in pairs(g_fillTypeManager.indexToFillType) do
            if fillTypeIndex ~= FillType.UNKNOWN then
                fillUnit.supportedFillTypes[fillTypeIndex] = true
            end
        end
    end
end

-- before onPostLoad, which puts a savegame pallet's product back in
FillUnit.onLoad = Utils.appendedFunction(FillUnit.onLoad, PalletDepotPallets.onFillUnitLoad)

-- --- applying (server and clients) ---------------------------------------------------------------------

local function loadPallet(spawner, size)
    spawner.palletDepotPallets = spawner.palletDepotPallets or {}
    if spawner.palletDepotPallets[size] == nil then
        local filename = PalletDepot.modDirectory .. PalletDepotPallets.FILES[size]
        spawner.palletDepotPallets[size] = spawner:loadPalletFromFilename(filename) or false
    end
    return spawner.palletDepotPallets[size] or nil
end

-- The spawner's table says which pallet gets spawned, the production's own table when: once its capacity is in stock.
-- Both get our pallet for the same products.
function PalletDepotPallets.apply(productionPoint)
    local spawner = productionPoint.palletSpawner
    if spawner == nil or spawner.fillTypeIdToPallet == nil then
        return
    end
    -- the game's tables, kept before our pallet is loaded (loading it adds it to the spawner's table)
    if productionPoint.palletDepotSpawnerPallets == nil then
        productionPoint.palletDepotSpawnerPallets = copy(spawner.fillTypeIdToPallet)
    end
    if productionPoint.palletDepotOutputPallets == nil and productionPoint.outputFillTypeIdsToPallets ~= nil then
        productionPoint.palletDepotOutputPallets = copy(productionPoint.outputFillTypeIdsToPallets)
    end
    local gameOutputs = productionPoint.palletDepotOutputPallets or {}

    local size = PalletDepotPallets.get(productionPoint)
    local pallet = size > 0 and loadPallet(spawner, size) or nil
    local spawnerMap = copy(productionPoint.palletDepotSpawnerPallets)
    local outputMap = copy(gameOutputs)
    if pallet ~= nil then
        local isDepot = PalletDepot.isDepot(productionPoint)
        for fillType in pairs(productionPoint.outputFillTypeIds or {}) do
            -- other productions keep products without a pallet off pallets
            if isDepot or gameOutputs[fillType] ~= nil then
                spawnerMap[fillType] = pallet
                outputMap[fillType] = pallet
            end
        end
    end
    spawner.fillTypeIdToPallet = spawnerMap
    if productionPoint.outputFillTypeIdsToPallets ~= nil then
        productionPoint.outputFillTypeIdsToPallets = outputMap
    end
end

local function store(productionPoint, size)
    if PalletDepotPallets.FILES[size] == nil then
        size = 0
    end
    PalletDepotPallets.data[productionPoint] = size > 0 and size or nil
    PalletDepotPallets.apply(productionPoint)
end
PalletDepotPallets.store = store

-- --- editing -------------------------------------------------------------------------------------------

function PalletDepotPallets.request(productionPoint, size)
    store(productionPoint, size)        -- shown at once, the server confirms
    if g_server ~= nil then
        g_server:broadcastEvent(PalletDepotPalletsEvent.new(productionPoint, size))
    else
        g_client:getServerConnection():sendEvent(PalletDepotPalletsEvent.new(productionPoint, size))
    end
end

PalletDepotPalletsEvent = {}
local PalletDepotPalletsEvent_mt = Class(PalletDepotPalletsEvent, Event)
InitEventClass(PalletDepotPalletsEvent, "PalletDepotPalletsEvent")

function PalletDepotPalletsEvent.emptyNew()
    return Event.new(PalletDepotPalletsEvent_mt)
end

function PalletDepotPalletsEvent.new(productionPoint, size)
    local self = PalletDepotPalletsEvent.emptyNew()
    self.productionPoint = productionPoint
    self.size = size
    return self
end

function PalletDepotPalletsEvent:readStream(streamId, connection)
    self.productionPoint = NetworkUtil.readNodeObject(streamId)
    self.size = streamReadUInt16(streamId)
    self:run(connection)
end

function PalletDepotPalletsEvent:writeStream(streamId, connection)
    NetworkUtil.writeNodeObject(streamId, self.productionPoint)
    streamWriteUInt16(streamId, self.size)
end

function PalletDepotPalletsEvent:run(connection)
    local productionPoint = self.productionPoint
    if productionPoint == nil then
        return
    end
    if not connection:getIsServer() then
        -- a client's change arrives at the server: only players allowed to manage this farm's productions
        if not g_currentMission:getHasPlayerPermission("manageProductions", connection, productionPoint:getOwnerFarmId()) then
            return
        end
        store(productionPoint, self.size)
        g_server:broadcastEvent(PalletDepotPalletsEvent.new(productionPoint, self.size))
    else
        store(productionPoint, self.size)
    end
end

-- --- join synchronisation -------------------------------------------------------------------------------

function PalletDepotPallets.writeStream(productionPoint, streamId, connection)
    if connection:getIsServer() then
        return
    end
    streamWriteUInt16(streamId, PalletDepotPallets.get(productionPoint))
end

function PalletDepotPallets.readStream(productionPoint, streamId, connection)
    if not connection:getIsServer() then
        return
    end
    local size = streamReadUInt16(streamId)
    if size > 0 then
        store(productionPoint, size)
    end
end

ProductionPoint.writeStream = Utils.appendedFunction(ProductionPoint.writeStream, PalletDepotPallets.writeStream)
ProductionPoint.readStream = Utils.appendedFunction(ProductionPoint.readStream, PalletDepotPallets.readStream)
if ProductionPoint.delete ~= nil then
    ProductionPoint.delete = Utils.prependedFunction(ProductionPoint.delete, function(productionPoint)
        PalletDepotPallets.data[productionPoint] = nil
    end)
end

-- --- savegame (server) ---------------------------------------------------------------------------------

local function getFilename()
    local dir = g_currentMission ~= nil and g_currentMission.missionInfo ~= nil and g_currentMission.missionInfo.savegameDirectory or nil
    return dir ~= nil and (dir .. "/" .. PalletDepotPallets.FILENAME) or nil
end

local function getKey(productionPoint)
    local placeable = productionPoint.owningPlaceable
    return placeable ~= nil and placeable.getUniqueId ~= nil and placeable:getUniqueId() or nil
end

function PalletDepotPallets.save()
    local filename = getFilename()
    if filename == nil or g_server == nil then
        return
    end
    local xmlId = createXMLFile("palletDepotPallets", filename, "palletDepotPallets")
    local i = 0
    for productionPoint, size in pairs(PalletDepotPallets.data) do
        local placeableKey = getKey(productionPoint)
        if placeableKey ~= nil then
            local key = string.format("palletDepotPallets.production(%d)", i)
            setXMLString(xmlId, key .. "#placeable", placeableKey)
            setXMLInt(xmlId, key .. "#pallet", size)
            i = i + 1
        end
    end
    saveXMLFile(xmlId)
    delete(xmlId)
end

function PalletDepotPallets.load()
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
    local xmlId = loadXMLFile("palletDepotPallets", filename)
    local i = 0
    while hasXMLProperty(xmlId, string.format("palletDepotPallets.production(%d)", i)) do
        local key = string.format("palletDepotPallets.production(%d)", i)
        local productionPoint = byKey[getXMLString(xmlId, key .. "#placeable") or ""]
        if productionPoint ~= nil then
            store(productionPoint, Utils.getNoNil(getXMLInt(xmlId, key .. "#pallet"), 0))
        end
        i = i + 1
    end
    delete(xmlId)
end

FSBaseMission.saveSavegame = Utils.appendedFunction(FSBaseMission.saveSavegame, PalletDepotPallets.save)
-- not at loadMission00Finished: the buildings of the savegame are still loading then
Mission00.onStartMission = Utils.appendedFunction(Mission00.onStartMission, PalletDepotPallets.load)
