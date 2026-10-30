-- Pallet Depot: auto-management and alerts for the productions of each farm (settings on the productions window's
-- Settings tab).
--
-- Farm settings (per farm, saved with the savegame, shared with all players, changed by players allowed to manage
-- the farm's productions):
--   autoManage         pause lines that are stuck (missing inputs or no output space) so they stop costing money,
--                      and switch them on again once all inputs are there and every output is below the high
--                      threshold, if their schedule allows. Only lines it paused itself are switched on again.
--   notifyControl      alert when a line is paused or restarted by the auto-management
--   notifyLowInputs    alert when an input of a running line falls below the low threshold
--   notifyHighOutputs  alert when an output of a running line reaches the high threshold
--   lowThreshold / highThreshold   in percent of the storage capacity
-- The server checks every CHECK_INTERVAL and sends alerts to the players of the owning farm. Depots are left alone:
-- their lines are storage, not production.

PalletDepotAutoManager = {}
PalletDepotAutoManager.FILENAME = "palletDepotAutoManager.xml"
PalletDepotAutoManager.CHECK_INTERVAL = 30000           -- ms
PalletDepotAutoManager.ALERT_COOLDOWN = 10 * 60 * 1000  -- ms of game time between repeated low/high alerts
PalletDepotAutoManager.LOW_CHOICES = {10, 15, 20, 25, 30}
PalletDepotAutoManager.HIGH_CHOICES = {70, 75, 80, 85, 90}
PalletDepotAutoManager.ALERT = {PAUSED_INPUTS = 1, PAUSED_OUTPUT = 2, RESUMED = 3, LOW_INPUTS = 4, HIGH_OUTPUTS = 5}

PalletDepotAutoManager.settings = {}    -- farmId -> settings
PalletDepotAutoManager.paused = {}      -- productionPoint -> productionId -> true (paused by us; server only)
PalletDepotAutoManager.alerted = {}     -- productionPoint -> key -> game time of the last alert (server only)
PalletDepotAutoManager.timer = 0

function PalletDepotAutoManager.defaultSettings()
    return {autoManage = false, notifyControl = false, notifyLowInputs = false, notifyHighOutputs = false,
        lowThreshold = 20, highThreshold = 80}
end

function PalletDepotAutoManager.getSettings(farmId)
    return PalletDepotAutoManager.settings[farmId] or PalletDepotAutoManager.defaultSettings()
end

local function copySettings(settings)
    local copy = {}
    for k, v in pairs(settings) do
        copy[k] = v
    end
    return copy
end

-- --- the check (server) --------------------------------------------------------------------------------

local function share(storage, fillType)
    local capacity = storage:getCapacity(fillType) or 0
    return capacity > 0 and (storage:getFillLevel(fillType) or 0) / capacity or 0
end

function PalletDepotAutoManager.checkLine(productionPoint, production, settings)
    local storage = productionPoint.storage
    local STATUS = ProductionPoint.PROD_STATUS
    local ALERT = PalletDepotAutoManager.ALERT
    local id = production.id
    local paused = PalletDepotAutoManager.paused[productionPoint] or {}
    PalletDepotAutoManager.paused[productionPoint] = paused
    local enabled = production.status ~= STATUS.INACTIVE

    local inputsOk, low = true, {}
    for _, input in ipairs(production.inputs or {}) do
        if (storage:getFillLevel(input.type) or 0) < input.amount then
            inputsOk = false
        end
        if share(storage, input.type) * 100 < settings.lowThreshold then
            table.insert(low, input.type)
        end
    end
    local high = {}
    for _, output in ipairs(production.outputs or {}) do
        if share(storage, output.type) * 100 >= settings.highThreshold then
            table.insert(high, output.type)
        end
    end

    if enabled and paused[id] then
        paused[id] = nil            -- switched on again by a player: no longer ours
    end
    if settings.autoManage then
        if enabled and (production.status == STATUS.MISSING_INPUTS or production.status == STATUS.NO_OUTPUT_SPACE) then
            local reason = production.status == STATUS.MISSING_INPUTS and ALERT.PAUSED_INPUTS or ALERT.PAUSED_OUTPUT
            PalletDepotAutoManager.setLine(productionPoint, id, false)
            paused[id] = true
            enabled = false
            if settings.notifyControl then
                PalletDepotAutoManager.sendAlert(productionPoint, id, reason, {})
            end
        elseif not enabled and paused[id] and inputsOk and #high == 0 and PalletDepotSchedules.allowsNow(productionPoint, id) then
            PalletDepotAutoManager.setLine(productionPoint, id, true)
            paused[id] = nil
            enabled = true
            if settings.notifyControl then
                PalletDepotAutoManager.sendAlert(productionPoint, id, ALERT.RESUMED, {})
            end
        end
    end
    if enabled then
        if settings.notifyLowInputs and #low > 0 then
            PalletDepotAutoManager.sendAlertOnce(productionPoint, id, ALERT.LOW_INPUTS, low)
        end
        if settings.notifyHighOutputs and #high > 0 then
            PalletDepotAutoManager.sendAlertOnce(productionPoint, id, ALERT.HIGH_OUTPUTS, high)
        end
    end
end

function PalletDepotAutoManager.setLine(productionPoint, productionId, enable)
    ProductionPointProductionStateEvent.sendEvent(productionPoint, productionId, enable, false)
    productionPoint:setProductionState(productionId, enable, true)
end

function PalletDepotAutoManager.check()
    local manager = g_currentMission.productionChainManager
    for _, productionPoint in ipairs(manager ~= nil and manager.productionPoints or {}) do
        local settings = PalletDepotAutoManager.settings[productionPoint:getOwnerFarmId()]
        if settings ~= nil and productionPoint.storage ~= nil and not PalletDepot.isDepot(productionPoint)
            and (settings.autoManage or settings.notifyLowInputs or settings.notifyHighOutputs) then
            for _, production in ipairs(productionPoint.productions or {}) do
                PalletDepotAutoManager.checkLine(productionPoint, production, settings)
            end
        end
    end
end

function PalletDepotAutoManager:update(dt)
    if g_server == nil or g_currentMission == nil then
        return
    end
    PalletDepotAutoManager.timer = PalletDepotAutoManager.timer + dt
    if PalletDepotAutoManager.timer >= PalletDepotAutoManager.CHECK_INTERVAL then
        PalletDepotAutoManager.timer = 0
        PalletDepotAutoManager.check()
    end
end

-- --- alerts --------------------------------------------------------------------------------------------

-- low/high alerts repeat at most every ALERT_COOLDOWN of game time per line
function PalletDepotAutoManager.sendAlertOnce(productionPoint, productionId, kind, fillTypes)
    local alerted = PalletDepotAutoManager.alerted[productionPoint] or {}
    PalletDepotAutoManager.alerted[productionPoint] = alerted
    local key = productionId .. "#" .. kind
    local now = g_currentMission.time or 0
    if alerted[key] == nil or now - alerted[key] >= PalletDepotAutoManager.ALERT_COOLDOWN then
        alerted[key] = now
        PalletDepotAutoManager.sendAlert(productionPoint, productionId, kind, fillTypes)
    end
end

function PalletDepotAutoManager.sendAlert(productionPoint, productionId, kind, fillTypes)
    g_server:broadcastEvent(PalletDepotAlertEvent.new(productionPoint, productionId, kind, fillTypes), true)
end

-- shown on the clients of the owning farm
function PalletDepotAutoManager.showAlert(productionPoint, productionId, kind, fillTypes)
    if g_client == nil or g_currentMission == nil or g_currentMission:getFarmId() ~= productionPoint:getOwnerFarmId() then
        return
    end
    local production = productionPoint.productionsIdToObj ~= nil and productionPoint.productionsIdToObj[productionId] or nil
    local lineName = production ~= nil and production.name or productionId
    local names = {}
    for _, fillType in ipairs(fillTypes) do
        table.insert(names, g_fillTypeManager:getFillTypeTitleByIndex(fillType) or "?")
    end
    local ALERT = PalletDepotAutoManager.ALERT
    local keys = {[ALERT.PAUSED_INPUTS] = "pdo_alertPausedInputs", [ALERT.PAUSED_OUTPUT] = "pdo_alertPausedOutput",
        [ALERT.RESUMED] = "pdo_alertResumed", [ALERT.LOW_INPUTS] = "pdo_alertLowInputs", [ALERT.HIGH_OUTPUTS] = "pdo_alertHighOutputs"}
    if keys[kind] == nil then
        return
    end
    local text = string.format(g_i18n:getText(keys[kind]), lineName, productionPoint:getName(), table.concat(names, ", "))
    local style = (kind == ALERT.RESUMED) and FSBaseMission.INGAME_NOTIFICATION_OK
        or (kind == ALERT.LOW_INPUTS or kind == ALERT.HIGH_OUTPUTS) and FSBaseMission.INGAME_NOTIFICATION_CRITICAL
        or FSBaseMission.INGAME_NOTIFICATION_INFO
    g_currentMission:addIngameNotification(style, text)
end

PalletDepotAlertEvent = {}
local PalletDepotAlertEvent_mt = Class(PalletDepotAlertEvent, Event)
InitEventClass(PalletDepotAlertEvent, "PalletDepotAlertEvent")

function PalletDepotAlertEvent.emptyNew()
    return Event.new(PalletDepotAlertEvent_mt)
end

function PalletDepotAlertEvent.new(productionPoint, productionId, kind, fillTypes)
    local self = PalletDepotAlertEvent.emptyNew()
    self.productionPoint = productionPoint
    self.productionId = productionId
    self.kind = kind
    self.fillTypes = fillTypes
    return self
end

function PalletDepotAlertEvent:readStream(streamId, connection)
    self.productionPoint = NetworkUtil.readNodeObject(streamId)
    self.productionId = streamReadString(streamId)
    self.kind = streamReadUInt8(streamId)
    self.fillTypes = {}
    for _ = 1, streamReadUInt8(streamId) do
        table.insert(self.fillTypes, streamReadUIntN(streamId, FillTypeManager.SEND_NUM_BITS))
    end
    self:run(connection)
end

function PalletDepotAlertEvent:writeStream(streamId, connection)
    NetworkUtil.writeNodeObject(streamId, self.productionPoint)
    streamWriteString(streamId, self.productionId)
    streamWriteUInt8(streamId, self.kind)
    streamWriteUInt8(streamId, math.min(#self.fillTypes, 255))
    for i = 1, math.min(#self.fillTypes, 255) do
        streamWriteUIntN(streamId, self.fillTypes[i], FillTypeManager.SEND_NUM_BITS)
    end
end

function PalletDepotAlertEvent:run(connection)
    if self.productionPoint ~= nil then
        PalletDepotAutoManager.showAlert(self.productionPoint, self.productionId, self.kind, self.fillTypes)
    end
end

-- --- farm settings: editing and sync -------------------------------------------------------------------

-- from the Settings tab; the server stores and shares it, clients ask the server
function PalletDepotAutoManager.requestSettings(farmId, settings)
    PalletDepotAutoManager.settings[farmId] = copySettings(settings)    -- shown at once, the server confirms
    if g_server ~= nil then
        g_server:broadcastEvent(PalletDepotSettingsEvent.new(farmId, settings))
    else
        g_client:getServerConnection():sendEvent(PalletDepotSettingsEvent.new(farmId, settings))
    end
end

PalletDepotSettingsEvent = {}
local PalletDepotSettingsEvent_mt = Class(PalletDepotSettingsEvent, Event)
InitEventClass(PalletDepotSettingsEvent, "PalletDepotSettingsEvent")

function PalletDepotSettingsEvent.emptyNew()
    return Event.new(PalletDepotSettingsEvent_mt)
end

function PalletDepotSettingsEvent.new(farmId, settings)
    local self = PalletDepotSettingsEvent.emptyNew()
    self.farmId = farmId
    self.settings = copySettings(settings)
    return self
end

function PalletDepotSettingsEvent:readStream(streamId, connection)
    self.farmId = streamReadUInt8(streamId)
    local s = PalletDepotAutoManager.defaultSettings()
    s.autoManage = streamReadBool(streamId)
    s.notifyControl = streamReadBool(streamId)
    s.notifyLowInputs = streamReadBool(streamId)
    s.notifyHighOutputs = streamReadBool(streamId)
    s.lowThreshold = streamReadUInt8(streamId)
    s.highThreshold = streamReadUInt8(streamId)
    self.settings = s
    self:run(connection)
end

function PalletDepotSettingsEvent:writeStream(streamId, connection)
    local s = self.settings
    streamWriteUInt8(streamId, self.farmId)
    streamWriteBool(streamId, s.autoManage)
    streamWriteBool(streamId, s.notifyControl)
    streamWriteBool(streamId, s.notifyLowInputs)
    streamWriteBool(streamId, s.notifyHighOutputs)
    streamWriteUInt8(streamId, s.lowThreshold)
    streamWriteUInt8(streamId, s.highThreshold)
end

function PalletDepotSettingsEvent:run(connection)
    if not connection:getIsServer() then
        -- a client's change arrives at the server: only players allowed to manage that farm's productions
        if not g_currentMission:getHasPlayerPermission("manageProductions", connection, self.farmId) then
            return
        end
        PalletDepotAutoManager.settings[self.farmId] = copySettings(self.settings)
        g_server:broadcastEvent(PalletDepotSettingsEvent.new(self.farmId, self.settings))
    else
        PalletDepotAutoManager.settings[self.farmId] = copySettings(self.settings)
    end
end

-- a joining player gets every farm's settings
function PalletDepotAutoManager.sendInitialClientState(mission, connection, user, farm)
    for farmId, settings in pairs(PalletDepotAutoManager.settings) do
        connection:sendEvent(PalletDepotSettingsEvent.new(farmId, settings))
    end
end

FSBaseMission.sendInitialClientState = Utils.appendedFunction(FSBaseMission.sendInitialClientState,
    PalletDepotAutoManager.sendInitialClientState)

-- --- savegame (server) ---------------------------------------------------------------------------------

local function getFilename()
    local dir = g_currentMission ~= nil and g_currentMission.missionInfo ~= nil and g_currentMission.missionInfo.savegameDirectory or nil
    return dir ~= nil and (dir .. "/" .. PalletDepotAutoManager.FILENAME) or nil
end

local function getKey(productionPoint)
    local placeable = productionPoint.owningPlaceable
    return placeable ~= nil and placeable.getUniqueId ~= nil and placeable:getUniqueId() or nil
end

local BOOL_SETTINGS = {"autoManage", "notifyControl", "notifyLowInputs", "notifyHighOutputs"}

function PalletDepotAutoManager.save()
    local filename = getFilename()
    if filename == nil or g_server == nil then
        return
    end
    local xmlId = createXMLFile("palletDepotAutoManager", filename, "palletDepotAutoManager")
    local i = 0
    for farmId, settings in pairs(PalletDepotAutoManager.settings) do
        local key = string.format("palletDepotAutoManager.farm(%d)", i)
        setXMLInt(xmlId, key .. "#id", farmId)
        for _, name in ipairs(BOOL_SETTINGS) do
            setXMLBool(xmlId, key .. "#" .. name, settings[name])
        end
        setXMLInt(xmlId, key .. "#lowThreshold", settings.lowThreshold)
        setXMLInt(xmlId, key .. "#highThreshold", settings.highThreshold)
        i = i + 1
    end
    i = 0
    for productionPoint, lines in pairs(PalletDepotAutoManager.paused) do
        local placeableKey = getKey(productionPoint)
        for productionId in pairs(lines) do
            if placeableKey ~= nil then
                local key = string.format("palletDepotAutoManager.paused(%d)", i)
                setXMLString(xmlId, key .. "#placeable", placeableKey)
                setXMLString(xmlId, key .. "#production", productionId)
                i = i + 1
            end
        end
    end
    saveXMLFile(xmlId)
    delete(xmlId)
end

function PalletDepotAutoManager.load()
    local filename = getFilename()
    if filename == nil or g_server == nil or not fileExists(filename) then
        return
    end
    local xmlId = loadXMLFile("palletDepotAutoManager", filename)
    local i = 0
    while hasXMLProperty(xmlId, string.format("palletDepotAutoManager.farm(%d)", i)) do
        local key = string.format("palletDepotAutoManager.farm(%d)", i)
        local settings = PalletDepotAutoManager.defaultSettings()
        for _, name in ipairs(BOOL_SETTINGS) do
            settings[name] = Utils.getNoNil(getXMLBool(xmlId, key .. "#" .. name), settings[name])
        end
        settings.lowThreshold = Utils.getNoNil(getXMLInt(xmlId, key .. "#lowThreshold"), settings.lowThreshold)
        settings.highThreshold = Utils.getNoNil(getXMLInt(xmlId, key .. "#highThreshold"), settings.highThreshold)
        local farmId = getXMLInt(xmlId, key .. "#id")
        if farmId ~= nil then
            PalletDepotAutoManager.settings[farmId] = settings
        end
        i = i + 1
    end
    local byKey = {}
    for _, productionPoint in ipairs(g_currentMission.productionChainManager.productionPoints or {}) do
        local key = getKey(productionPoint)
        if key ~= nil then
            byKey[key] = productionPoint
        end
    end
    i = 0
    while hasXMLProperty(xmlId, string.format("palletDepotAutoManager.paused(%d)", i)) do
        local key = string.format("palletDepotAutoManager.paused(%d)", i)
        local productionPoint = byKey[getXMLString(xmlId, key .. "#placeable") or ""]
        local productionId = getXMLString(xmlId, key .. "#production")
        if productionPoint ~= nil and productionId ~= nil then
            PalletDepotAutoManager.paused[productionPoint] = PalletDepotAutoManager.paused[productionPoint] or {}
            PalletDepotAutoManager.paused[productionPoint][productionId] = true
        end
        i = i + 1
    end
    delete(xmlId)
end

FSBaseMission.saveSavegame = Utils.appendedFunction(FSBaseMission.saveSavegame, PalletDepotAutoManager.save)
-- not at loadMission00Finished: the buildings of the savegame are still loading then
Mission00.onStartMission = Utils.appendedFunction(Mission00.onStartMission, PalletDepotAutoManager.load)

if ProductionPoint.delete ~= nil then
    ProductionPoint.delete = Utils.prependedFunction(ProductionPoint.delete, function(productionPoint)
        PalletDepotAutoManager.paused[productionPoint] = nil
        PalletDepotAutoManager.alerted[productionPoint] = nil
    end)
end

-- --- personal settings (this player only, kept in modSettings) ------------------------------------------

PalletDepotAutoManager.personal = {hideInactiveSites = false}

local function personalFilename()
    return getUserProfileAppPath() .. "modSettings/PalletDepot/settings.xml"
end

function PalletDepotAutoManager.savePersonal()
    createFolder(getUserProfileAppPath() .. "modSettings/")
    createFolder(getUserProfileAppPath() .. "modSettings/PalletDepot/")
    local xmlId = createXMLFile("palletDepotSettings", personalFilename(), "palletDepotSettings")
    setXMLBool(xmlId, "palletDepotSettings#hideInactiveSites", PalletDepotAutoManager.personal.hideInactiveSites)
    saveXMLFile(xmlId)
    delete(xmlId)
end

function PalletDepotAutoManager.loadPersonal()
    local filename = personalFilename()
    if fileExists(filename) then
        local xmlId = loadXMLFile("palletDepotSettings", filename)
        PalletDepotAutoManager.personal.hideInactiveSites = Utils.getNoNil(getXMLBool(xmlId, "palletDepotSettings#hideInactiveSites"), false)
        delete(xmlId)
    end
end

function PalletDepotAutoManager:loadMap()
    if g_client ~= nil then
        PalletDepotAutoManager.loadPersonal()
    end
end

addModEventListener(PalletDepotAutoManager)
