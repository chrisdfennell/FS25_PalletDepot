-- Pallet Depot: production schedules (which months a production line runs), for every production of a farm.
--
-- A schedule belongs to one line of one production point: an on/off switch plus a set of months (periods 1-12).
-- The server owns them: it saves them with the savegame (palletDepotSchedules.xml in the savegame folder, keyed by
-- the building's unique id and the line id), switches scheduled lines on or off whenever the month changes, after
-- loading and after an edit, and sends every change to all clients. Clients get all schedules when they join (with
-- the production point's own join data) and send edits to the server, which checks the player's permission.
-- A schedule without any month selected does nothing.

PalletDepotSchedules = {}
PalletDepotSchedules.FILENAME = "palletDepotSchedules.xml"
PalletDepotSchedules.NUM_MONTHS = 12
PalletDepotSchedules.data = {}      -- productionPoint -> productionId -> {enabled = bool, months = {[period] = true}}

-- --- data ----------------------------------------------------------------------------------------------

function PalletDepotSchedules.get(productionPoint, productionId)
    local lines = PalletDepotSchedules.data[productionPoint]
    return lines ~= nil and lines[productionId] or nil
end

local function hasMonths(schedule)
    return schedule ~= nil and next(schedule.months) ~= nil
end

function PalletDepotSchedules.isActive(schedule)
    return schedule ~= nil and schedule.enabled and hasMonths(schedule)
end

-- false when an active schedule keeps the line off this month (used by the auto-manager)
function PalletDepotSchedules.allowsNow(productionPoint, productionId)
    local schedule = PalletDepotSchedules.get(productionPoint, productionId)
    if not PalletDepotSchedules.isActive(schedule) then
        return true
    end
    return schedule.months[g_currentMission.environment.currentPeriod] == true
end

local function store(productionPoint, productionId, enabled, months)
    local lines = PalletDepotSchedules.data[productionPoint]
    if lines == nil then
        lines = {}
        PalletDepotSchedules.data[productionPoint] = lines
    end
    if not enabled and next(months) == nil then
        lines[productionId] = nil
    else
        lines[productionId] = {enabled = enabled, months = months}
    end
end

local function monthsToMask(months)
    local mask = 0
    for period = 1, PalletDepotSchedules.NUM_MONTHS do
        if months[period] then
            mask = mask + math.floor(2 ^ (period - 1))
        end
    end
    return mask
end

local function maskToMonths(mask)
    local months = {}
    for period = 1, PalletDepotSchedules.NUM_MONTHS do
        if math.floor(mask / 2 ^ (period - 1)) % 2 == 1 then
            months[period] = true
        end
    end
    return months
end

-- --- texts ---------------------------------------------------------------------------------------------

function PalletDepotSchedules.getMonthName(period, short)
    local ok, name = pcall(g_i18n.formatPeriod, g_i18n, period, short)
    if ok and type(name) == "string" and name ~= "" then
        return name
    end
    name = g_i18n:getText("pdo_month" .. period)
    return short and name:sub(1, 3) or name
end

-- "Mar-Jun, Sep" for the lines tab; "Paused" when switched off, "-" without a schedule
function PalletDepotSchedules.describe(schedule)
    if schedule == nil or not hasMonths(schedule) then
        return "-"
    elseif not schedule.enabled then
        return g_i18n:getText("pdo_schedulePaused")
    end
    local parts, period = {}, 1
    while period <= PalletDepotSchedules.NUM_MONTHS do
        if schedule.months[period] then
            local last = period
            while last < PalletDepotSchedules.NUM_MONTHS and schedule.months[last + 1] do
                last = last + 1
            end
            local first = PalletDepotSchedules.getMonthName(period, true)
            table.insert(parts, last > period and (first .. "-" .. PalletDepotSchedules.getMonthName(last, true)) or first)
            period = last + 1
        else
            period = period + 1
        end
    end
    return table.concat(parts, ", ")
end

-- --- applying (server) ---------------------------------------------------------------------------------

local function findProduction(productionPoint, productionId)
    if productionPoint.productionsIdToObj ~= nil and productionPoint.productionsIdToObj[productionId] ~= nil then
        return productionPoint.productionsIdToObj[productionId]
    end
    for _, production in ipairs(productionPoint.productions or {}) do
        if production.id == productionId then
            return production
        end
    end
    return nil
end

function PalletDepotSchedules.applyLine(productionPoint, productionId)
    if g_server == nil then
        return
    end
    local schedule = PalletDepotSchedules.get(productionPoint, productionId)
    local production = findProduction(productionPoint, productionId)
    if production == nil or not PalletDepotSchedules.isActive(schedule) then
        return
    end
    local shouldRun = schedule.months[g_currentMission.environment.currentPeriod] == true
    local isRunning = production.status ~= ProductionPoint.PROD_STATUS.INACTIVE
    if shouldRun ~= isRunning then
        ProductionPointProductionStateEvent.sendEvent(productionPoint, productionId, shouldRun, false)
        productionPoint:setProductionState(productionId, shouldRun, true)
    end
end

function PalletDepotSchedules.applyAll()
    for productionPoint, lines in pairs(PalletDepotSchedules.data) do
        for productionId in pairs(lines) do
            PalletDepotSchedules.applyLine(productionPoint, productionId)
        end
    end
end

-- --- editing -------------------------------------------------------------------------------------------

-- called by the schedule window; the server stores and applies it, clients ask the server
function PalletDepotSchedules.request(productionPoint, productionId, enabled, months)
    if g_server ~= nil then
        store(productionPoint, productionId, enabled, months)
        PalletDepotSchedules.applyLine(productionPoint, productionId)
        g_server:broadcastEvent(PalletDepotScheduleEvent.new(productionPoint, productionId, enabled, months))
    else
        store(productionPoint, productionId, enabled, months)      -- shown at once, the server confirms
        g_client:getServerConnection():sendEvent(PalletDepotScheduleEvent.new(productionPoint, productionId, enabled, months))
    end
end

-- --- network event -------------------------------------------------------------------------------------

PalletDepotScheduleEvent = {}
local PalletDepotScheduleEvent_mt = Class(PalletDepotScheduleEvent, Event)
InitEventClass(PalletDepotScheduleEvent, "PalletDepotScheduleEvent")

function PalletDepotScheduleEvent.emptyNew()
    return Event.new(PalletDepotScheduleEvent_mt)
end

function PalletDepotScheduleEvent.new(productionPoint, productionId, enabled, months)
    local self = PalletDepotScheduleEvent.emptyNew()
    self.productionPoint = productionPoint
    self.productionId = productionId
    self.enabled = enabled
    self.months = months
    return self
end

function PalletDepotScheduleEvent:readStream(streamId, connection)
    self.productionPoint = NetworkUtil.readNodeObject(streamId)
    self.productionId = streamReadString(streamId)
    self.enabled = streamReadBool(streamId)
    self.months = maskToMonths(streamReadUIntN(streamId, PalletDepotSchedules.NUM_MONTHS))
    self:run(connection)
end

function PalletDepotScheduleEvent:writeStream(streamId, connection)
    NetworkUtil.writeNodeObject(streamId, self.productionPoint)
    streamWriteString(streamId, self.productionId)
    streamWriteBool(streamId, self.enabled)
    streamWriteUIntN(streamId, monthsToMask(self.months), PalletDepotSchedules.NUM_MONTHS)
end

function PalletDepotScheduleEvent:run(connection)
    local productionPoint = self.productionPoint
    if productionPoint == nil then
        return
    end
    if not connection:getIsServer() then
        -- a client's edit arrives at the server: only players allowed to manage this farm's productions
        if not g_currentMission:getHasPlayerPermission("manageProductions", connection, productionPoint:getOwnerFarmId()) then
            return
        end
        store(productionPoint, self.productionId, self.enabled, self.months)
        PalletDepotSchedules.applyLine(productionPoint, self.productionId)
        g_server:broadcastEvent(PalletDepotScheduleEvent.new(productionPoint, self.productionId, self.enabled, self.months))
    else
        store(productionPoint, self.productionId, self.enabled, self.months)
    end
end

-- --- join synchronisation (all schedules of a production point travel with its join data) -----------

function PalletDepotSchedules.writeStream(productionPoint, streamId, connection)
    if connection:getIsServer() then
        return
    end
    local lines = PalletDepotSchedules.data[productionPoint] or {}
    local count = 0
    for _ in pairs(lines) do
        count = count + 1
    end
    streamWriteUInt16(streamId, count)
    for productionId, schedule in pairs(lines) do
        streamWriteString(streamId, productionId)
        streamWriteBool(streamId, schedule.enabled)
        streamWriteUIntN(streamId, monthsToMask(schedule.months), PalletDepotSchedules.NUM_MONTHS)
    end
end

function PalletDepotSchedules.readStream(productionPoint, streamId, connection)
    if not connection:getIsServer() then
        return
    end
    local count = streamReadUInt16(streamId)
    for _ = 1, count do
        local productionId = streamReadString(streamId)
        local enabled = streamReadBool(streamId)
        store(productionPoint, productionId, enabled, maskToMonths(streamReadUIntN(streamId, PalletDepotSchedules.NUM_MONTHS)))
    end
end

ProductionPoint.writeStream = Utils.appendedFunction(ProductionPoint.writeStream, PalletDepotSchedules.writeStream)
ProductionPoint.readStream = Utils.appendedFunction(ProductionPoint.readStream, PalletDepotSchedules.readStream)
if ProductionPoint.delete ~= nil then
    ProductionPoint.delete = Utils.prependedFunction(ProductionPoint.delete, function(productionPoint)
        PalletDepotSchedules.data[productionPoint] = nil
    end)
end

-- --- savegame (server) ---------------------------------------------------------------------------------

local function getFilename()
    local dir = g_currentMission ~= nil and g_currentMission.missionInfo ~= nil and g_currentMission.missionInfo.savegameDirectory or nil
    return dir ~= nil and (dir .. "/" .. PalletDepotSchedules.FILENAME) or nil
end

local function getKey(productionPoint)
    local placeable = productionPoint.owningPlaceable
    return placeable ~= nil and placeable.getUniqueId ~= nil and placeable:getUniqueId() or nil
end

function PalletDepotSchedules.save()
    local filename = getFilename()
    if filename == nil or g_server == nil then
        return
    end
    local xmlId = createXMLFile("palletDepotSchedules", filename, "palletDepotSchedules")
    local i = 0
    for productionPoint, lines in pairs(PalletDepotSchedules.data) do
        local placeableKey = getKey(productionPoint)
        if placeableKey ~= nil then
            for productionId, schedule in pairs(lines) do
                local key = string.format("palletDepotSchedules.schedule(%d)", i)
                setXMLString(xmlId, key .. "#placeable", placeableKey)
                setXMLString(xmlId, key .. "#production", productionId)
                setXMLBool(xmlId, key .. "#enabled", schedule.enabled)
                setXMLInt(xmlId, key .. "#months", monthsToMask(schedule.months))
                i = i + 1
            end
        end
    end
    saveXMLFile(xmlId)
    delete(xmlId)
end

function PalletDepotSchedules.load()
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
    local xmlId = loadXMLFile("palletDepotSchedules", filename)
    local i, loaded = 0, 0
    while true do
        local key = string.format("palletDepotSchedules.schedule(%d)", i)
        if not hasXMLProperty(xmlId, key) then
            break
        end
        local productionPoint = byKey[getXMLString(xmlId, key .. "#placeable") or ""]
        local productionId = getXMLString(xmlId, key .. "#production")
        if productionPoint ~= nil and productionId ~= nil and findProduction(productionPoint, productionId) ~= nil then
            store(productionPoint, productionId, Utils.getNoNil(getXMLBool(xmlId, key .. "#enabled"), true),
                maskToMonths(Utils.getNoNil(getXMLInt(xmlId, key .. "#months"), 0)))
            loaded = loaded + 1
        end
        i = i + 1
    end
    delete(xmlId)
    Logging.info("[%s] Schedules: %d loaded", PalletDepot.modName, loaded)
end

FSBaseMission.saveSavegame = Utils.appendedFunction(FSBaseMission.saveSavegame, PalletDepotSchedules.save)

-- --- lifecycle -----------------------------------------------------------------------------------------

-- (data is not reset here: the savegame schedules may already be loaded)
function PalletDepotSchedules:loadMap()
    g_messageCenter:subscribe(MessageType.PERIOD_CHANGED, PalletDepotSchedules.onPeriodChanged, PalletDepotSchedules)
end

function PalletDepotSchedules:deleteMap()
    g_messageCenter:unsubscribeAll(PalletDepotSchedules)
    PalletDepotSchedules.data = {}
end

function PalletDepotSchedules:onPeriodChanged()
    if g_server ~= nil then
        PalletDepotSchedules.applyAll()
    end
end

function PalletDepotSchedules.onMissionLoaded()
    PalletDepotSchedules.load()
    if g_server ~= nil then
        PalletDepotSchedules.applyAll()
    end
end

-- not at loadMission00Finished: the buildings of the savegame are still loading then
Mission00.onStartMission = Utils.appendedFunction(Mission00.onStartMission, PalletDepotSchedules.onMissionLoaded)
addModEventListener(PalletDepotSchedules)
