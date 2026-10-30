-- Pallet Depot: daily stock report.
--
-- Every few seconds the stock of each depot owned by the local player's farm is compared with the previous reading.
-- Increases count as "in"; decreases count as "sold" (products set to sell), "distributed" (products set to
-- distribute) or "out" (taken away as pallets). Every morning at 06:00 each depot with activity shows a summary as
-- an in-game notification. Totals cover the time since the last report (or since the game was loaded).

PalletDepotReport = {}
PalletDepotReport.POLL_INTERVAL = 5000   -- ms
PalletDepotReport.REPORT_HOUR = 6
PalletDepotReport.MIN_CHANGE = 0.5        -- liters; ignore rounding noise

local function getOwnDepots()
    if g_currentMission == nil then
        return {}
    end
    return PalletDepot.getDepots(g_currentMission:getFarmId())
end

function PalletDepotReport:loadMap()
    self.timer = 0
    self.lastLevels = {}   -- productionPoint -> fillType -> liters
    self.totals = {}       -- productionPoint -> {inLiters, outLiters, soldLiters, distributedLiters, perFillTypeIn}
    g_messageCenter:subscribe(MessageType.HOUR_CHANGED, self.onHourChanged, self)
end

function PalletDepotReport:deleteMap()
    g_messageCenter:unsubscribeAll(self)
end

function PalletDepotReport:getTotals(productionPoint)
    local totals = self.totals[productionPoint]
    if totals == nil then
        totals = {inLiters = 0, outLiters = 0, soldLiters = 0, distributedLiters = 0, perFillTypeIn = {}}
        self.totals[productionPoint] = totals
    end
    return totals
end

function PalletDepotReport:poll()
    for _, productionPoint in ipairs(getOwnDepots()) do
        local last = self.lastLevels[productionPoint]
        local current = {}
        for fillType, level in pairs(productionPoint.storage.fillLevels) do
            current[fillType] = level
        end
        if last ~= nil then
            local totals = self:getTotals(productionPoint)
            for fillType, level in pairs(current) do
                local change = level - (last[fillType] or 0)
                if change > PalletDepotReport.MIN_CHANGE then
                    totals.inLiters = totals.inLiters + change
                    totals.perFillTypeIn[fillType] = (totals.perFillTypeIn[fillType] or 0) + change
                elseif change < -PalletDepotReport.MIN_CHANGE then
                    local amount = -change
                    if productionPoint.outputFillTypeIdsDirectSell ~= nil and productionPoint.outputFillTypeIdsDirectSell[fillType] then
                        totals.soldLiters = totals.soldLiters + amount
                    elseif productionPoint.outputFillTypeIdsAutoDeliver ~= nil and productionPoint.outputFillTypeIdsAutoDeliver[fillType] then
                        totals.distributedLiters = totals.distributedLiters + amount
                    else
                        totals.outLiters = totals.outLiters + amount
                    end
                end
            end
        end
        self.lastLevels[productionPoint] = current
    end
end

function PalletDepotReport:update(dt)
    if g_currentMission == nil or g_client == nil then
        return
    end
    self.timer = self.timer + dt
    if self.timer >= PalletDepotReport.POLL_INTERVAL then
        self.timer = 0
        self:poll()
    end
end

function PalletDepotReport:onHourChanged()
    local environment = g_currentMission ~= nil and g_currentMission.environment or nil
    if environment == nil or environment.currentHour ~= PalletDepotReport.REPORT_HOUR or g_client == nil then
        return
    end
    self:poll()   -- include the last few seconds, e.g. hourly direct sales

    local reported = 0
    for _, productionPoint in ipairs(getOwnDepots()) do
        local totals = self.totals[productionPoint]
        if totals ~= nil and (totals.inLiters + totals.outLiters + totals.soldLiters + totals.distributedLiters) > PalletDepotReport.MIN_CHANGE then
            local text = string.format(g_i18n:getText("depot_report"), productionPoint:getName(),
                g_i18n:formatVolume(totals.inLiters, 0), g_i18n:formatVolume(totals.outLiters, 0),
                g_i18n:formatVolume(totals.distributedLiters, 0), g_i18n:formatVolume(totals.soldLiters, 0))

            local topFillType, topLiters = nil, 0
            for fillType, liters in pairs(totals.perFillTypeIn) do
                if liters > topLiters then
                    topFillType, topLiters = fillType, liters
                end
            end
            local fillTypeDesc = topFillType ~= nil and g_fillTypeManager:getFillTypeByIndex(topFillType) or nil
            if fillTypeDesc ~= nil then
                text = text .. " " .. string.format(g_i18n:getText("depot_reportTop"), fillTypeDesc.title,
                    g_i18n:formatVolume(topLiters, 0))
            end

            g_currentMission:addIngameNotification(FSBaseMission.INGAME_NOTIFICATION_INFO, text)
            Logging.info("[%s] Report: %s", PalletDepot.modName, text)
            reported = reported + 1
        end
    end
    self.totals = {}
    if reported == 0 then
        Logging.info("[%s] Report: no depot activity since the last report", PalletDepot.modName)
    end
end

addModEventListener(PalletDepotReport)
