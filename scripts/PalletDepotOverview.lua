-- Pallet Depot: productions window for every production of the player's farm (Right Shift + P).
--
-- Works like the old Productions Manager: one table of all productions, pages switched with the same keys.
--   Productions  each production with its inputs (X: outputs) as "stored / capacity L", five per line
--                C recipes, Q finances, E logistics, Backspace spawn goods, Enter settings
--   Recipes      one line per recipe: product, ingredients, status; Backspace switches the recipe on / off; C back
--   Finances     stock value, running costs and net per month; Backspace spawn goods; Q back
--   Logistics    per recipe: stored, supply, output, destination, status; Enter changes the output (Storing ->
--                Spawning -> Distributing -> Selling with Production Storage Control, else Spawning -> Distributing ->
--                Selling), Backspace switches the recipe on / off, X schedule, C hides inactive recipes, Q spawn goods;
--                E back
--   Settings     farm settings (auto-manage, alerts), the selected production's pallets, the selected depot's
--                capacity, personal settings;
--                Enter changes the selected setting, Backspace back
-- Space exports a CSV, Esc closes. Spawn goods opens Production Storage Control's spawn window for the selected
-- production, as in the old depot. Changes go through the game's own events, so they work in multiplayer. Depots only
-- list stocked products (they have up to 184).

PalletDepotOverview = {}
local PalletDepotOverview_mt = Class(PalletDepotOverview, MessageDialog)

PalletDepotOverview.GUI_NAME = "PalletDepotOverview"
PalletDepotOverview.PAGE = {MAIN = 1, RECIPES = 2, FINANCES = 3, LOGISTICS = 4, SETTINGS = 5}
PalletDepotOverview.PER_LINE = 5               -- products per line on the productions page
PalletDepotOverview.MIN_STOCK = 0.5            -- liters; below this a product counts as empty
PalletDepotOverview.FULL_SHARE = 0.9           -- "Full" above 90 % of capacity
PalletDepotOverview.hideInactive = false       -- logistics page, remembered for the session
PalletDepotOverview.profilesLoaded = false

local PAGE = PalletDepotOverview.PAGE

local COLOR = {
    text = {0.92, 0.94, 0.92, 1}, dim = {0.6, 0.64, 0.61, 1}, green = {0.35, 0.82, 0.4, 1},
    orange = {1, 0.6, 0.15, 1}, red = {0.95, 0.32, 0.27, 1}, blue = {0.35, 0.72, 1, 1}
}

-- columns per page in px of the 1694 px row: slots 1-5 {x, width, icon}, status {x, width}; header text keys
local LAYOUT = {
    [PAGE.MAIN] = {
        slots = {{300, 270, true}, {578, 270, true}, {856, 270, true}, {1134, 270, true}, {1412, 270, true}},
        headers = {name = "pdo_hbName"}},
    [PAGE.RECIPES] = {
        slots = {{300, 330, true}, {650, 235, true}, {890, 235, true}, {1130, 235, true}, {1370, 215, true}},
        status = {1590, 100},
        headers = {name = "pdo_hbName", "pdo_hbRecipe", "pdo_hbIngredients", status = "pdo_hbStatus"}},
    [PAGE.FINANCES] = {
        slots = {{300, 290}, {600, 290}, {900, 290}},
        headers = {name = "pdo_hbName", "pdo_finStockValue", "pdo_finCosts", "pdo_finNet"}},
    [PAGE.LOGISTICS] = {
        slots = {{300, 310, true}, {620, 230}, {860, 120}, {990, 170}, {1170, 410}},
        status = {1590, 100},
        headers = {name = "pdo_hbName", "pdo_hbRecipe", "pdo_hbStored", "pdo_hbSupply", "pdo_hbOutput",
                   "pdo_hbDestination", status = "pdo_hbStatus"}},
    [PAGE.SETTINGS] = {
        slots = {{420, 200}, {640, 1040}},
        headers = {name = "pdo_hbSetting", "pdo_hbValue", "pdo_hbDescription"}},
}

-- farm settings (PalletDepotAutoManager, shared), the selected production's pallets, the selected depot's options and
-- this player's own settings; "only" rows appear when the settings were opened on such a production
local SETTINGS = {
    {section = "pdo_setSectionFarm"},
    {scope = "farm", key = "autoManage", name = "pdo_setAutoManage", desc = "pdo_setAutoManageDesc"},
    {scope = "farm", key = "notifyControl", name = "pdo_setNotifyControl", desc = "pdo_setNotifyControlDesc"},
    {scope = "farm", key = "notifyLowInputs", name = "pdo_setNotifyLow", desc = "pdo_setNotifyLowDesc"},
    {scope = "farm", key = "notifyHighOutputs", name = "pdo_setNotifyHigh", desc = "pdo_setNotifyHighDesc"},
    {scope = "farm", key = "lowThreshold", name = "pdo_setLowThreshold", desc = "pdo_setLowThresholdDesc", choices = "LOW_CHOICES"},
    {scope = "farm", key = "highThreshold", name = "pdo_setHighThreshold", desc = "pdo_setHighThresholdDesc", choices = "HIGH_CHOICES"},
    {section = "pdo_setSectionProduction", only = "spawner"},
    {scope = "pallet", key = "pallet", name = "pdo_setPallet", desc = "pdo_setPalletDesc", choices = "SIZES",
     format = "pallet", only = "spawner"},
    {section = "pdo_setSectionDepot", only = "depot"},
    {scope = "depot", key = "capacity", name = "pdo_setCapacity", desc = "pdo_setCapacityDesc", choices = "CAPACITIES",
     format = "liters", only = "depot"},
    {section = "pdo_setSectionPersonal"},
    {scope = "personal", key = "hideInactiveSites", name = "pdo_setHideInactive", desc = "pdo_setHideInactiveDesc"},
}

-- which key runs which button on which pages; a key does nothing while its button is hidden
local KEYS = {
    {action = "MENU_EXTRA_1", button = "toggleButton", handler = "onClickToggleInputs", pages = {PAGE.MAIN}},
    {action = "MENU_EXTRA_1", button = "scheduleButton", handler = "onClickSchedule", pages = {PAGE.LOGISTICS}},
    {action = "MENU_EXTRA_2", button = "recipeButton", handler = "onClickRecipes", pages = {PAGE.MAIN, PAGE.RECIPES}},
    {action = "MENU_EXTRA_2", button = "inactiveButton", handler = "onClickHideInactive", pages = {PAGE.LOGISTICS}},
    {action = "MENU_PAGE_PREV", button = "financesButton", handler = "onClickFinances", pages = {PAGE.MAIN, PAGE.RECIPES, PAGE.FINANCES}},
    {action = "MENU_PAGE_PREV", button = "spawnButton", handler = "onClickSpawnGoods", pages = {PAGE.LOGISTICS}},
    {action = "MENU_PAGE_NEXT", button = "logisticsButton", handler = "onClickLogistics",
     pages = {PAGE.MAIN, PAGE.RECIPES, PAGE.FINANCES, PAGE.LOGISTICS}},
    {action = "MENU_ACCEPT", button = "settingsButton", handler = "onClickSettings", pages = {PAGE.MAIN}},
    {action = "MENU_ACCEPT", button = "changeOutputButton", handler = "onClickChangeOutput", pages = {PAGE.LOGISTICS}},
    {action = "MENU_ACCEPT", button = "changeSettingButton", handler = "onClickChangeSetting", pages = {PAGE.SETTINGS}},
    {action = "MENU_CANCEL", button = "spawnButton", handler = "onClickSpawnGoods", pages = {PAGE.MAIN, PAGE.FINANCES}},
    {action = "MENU_CANCEL", button = "activateButton", handler = "onClickActivate", pages = {PAGE.RECIPES, PAGE.LOGISTICS}},
    {action = "MENU_CANCEL", button = "backButton", handler = "onClickSettingsBack", pages = {PAGE.SETTINGS}},
    {action = "MENU_ACTIVATE", button = "exportButton", handler = "onClickExport"},
}

-- --- helpers -------------------------------------------------------------------------------------------

local function text(key)
    return g_i18n:getText(key)
end

-- whole number with "," between thousands
local function formatInt(value)
    local s = tostring(math.floor(math.abs(value) + 0.5))
    local out = s:reverse():gsub("(%d%d%d)", "%1,"):reverse()
    if out:sub(1, 1) == "," then
        out = out:sub(2)
    end
    return (value < 0 and "-" or "") .. out
end

local function formatStock(fillLevel, capacity)
    return string.format("%s / %s L", formatInt(fillLevel or 0), formatInt(capacity or 0))
end

local function money(value)
    return g_i18n:formatMoney(value, 0, true, true)
end

local function getPSC()
    local env = _G["FS25_ProductionStorageControl"]
    return env ~= nil and env.productionStorageControl ~= nil and env or nil
end

local function hasStoreMode()
    return ProductionPoint.OUTPUT_MODE ~= nil and ProductionPoint.OUTPUT_MODE.STORE ~= nil
end

local function contains(list, value)
    for _, v in ipairs(list) do
        if v == value then
            return true
        end
    end
    return false
end

local function productFillType(production)
    if production.primaryProductFillType ~= nil then
        return production.primaryProductFillType
    end
    local output = production.outputs ~= nil and production.outputs[1] or nil
    return output ~= nil and output.type or nil
end

local function fillTypeTitle(fillTypeIndex)
    return g_fillTypeManager:getFillTypeTitleByIndex(fillTypeIndex) or "?"
end

local function fillTypeIcon(fillTypeIndex)
    local fillType = g_fillTypeManager:getFillTypeByIndex(fillTypeIndex)
    return fillType ~= nil and fillType.hudOverlayFilename or nil
end

local function isEnabled(production)
    return production.status ~= ProductionPoint.PROD_STATUS.INACTIVE
end

local function needsAttention(production)
    local status = ProductionPoint.PROD_STATUS
    return production.status == status.MISSING_INPUTS or production.status == status.NO_OUTPUT_SPACE
end

local function cyclesPerHour(production)
    if production.cyclesPerHour ~= nil then
        return production.cyclesPerHour
    elseif production.cyclesPerMinute ~= nil then
        return production.cyclesPerMinute * 60
    elseif production.cyclesPerMonth ~= nil then
        return production.cyclesPerMonth / 24
    end
    return 0
end

local function cell(value, color, icon)
    return {text = value, color = color or COLOR.text, icon = icon}
end

local function statusCell(production, scheduled)
    local status = ProductionPoint.PROD_STATUS
    local mark = scheduled and " [S]" or ""
    if production.status == status.RUNNING then
        return cell(text("pdo_statusActive") .. mark, COLOR.green)
    elseif production.status == status.MISSING_INPUTS then
        return cell(text("pdo_statusActive") .. " (!)" .. mark, COLOR.orange)
    elseif production.status == status.NO_OUTPUT_SPACE then
        return cell(text("pdo_statusFull") .. mark, COLOR.orange)
    end
    return cell(text("pdo_statusInactive") .. mark, COLOR.red)
end

-- --- opening -------------------------------------------------------------------------------------------

function PalletDepotOverview.new(target, custom_mt)
    local self = MessageDialog.new(target, custom_mt or PalletDepotOverview_mt)
    self.showInputs = true
    self.showRecipes = false
    self.showFinances = false
    self.showLogistics = false
    self.showSettings = false
    self.settingsFacility = nil
    self.facilities = {}
    self.rows = {}
    self.rowIndex = 1
    return self
end

function PalletDepotOverview.show()
    local dir = PalletDepot.modDirectory
    if not PalletDepotOverview.profilesLoaded then
        g_gui:loadProfiles(dir .. "gui/PalletDepotOverviewProfiles.xml")
        PalletDepotOverview.profilesLoaded = true
    end
    local dialog = PalletDepotOverview.new()
    g_gui:loadGui(dir .. "gui/PalletDepotOverview.xml", PalletDepotOverview.GUI_NAME, dialog)
    g_gui:showDialog(PalletDepotOverview.GUI_NAME)
end

function PalletDepotOverview:onGuiSetupFinished()
    PalletDepotOverview:superClass().onGuiSetupFinished(self)
    self.table:setDataSource(self)
    self.table:setDelegate(self)
end

function PalletDepotOverview:onOpen()
    PalletDepotOverview:superClass().onOpen(self)
    -- px -> screen units, measured on the hidden 100 px reference cell
    self.pxToScreen = self.pxRef.size[1] / 100
    self:rebuild()
    FocusManager:setFocus(self.table)
end

function PalletDepotOverview:onClose()
    PalletDepotOverview:superClass().onClose(self)
    self.facilities, self.rows = {}, {}
end

function PalletDepotOverview:onClickOk()
    return false        -- Enter never closes the window
end

function PalletDepotOverview:onClickBack()
    self:close()
end

function PalletDepotOverview:getPage()
    if self.showSettings then
        return PAGE.SETTINGS
    elseif self.showLogistics then
        return PAGE.LOGISTICS
    elseif self.showFinances then
        return PAGE.FINANCES
    elseif self.showRecipes then
        return PAGE.RECIPES
    end
    return PAGE.MAIN
end

-- --- data ----------------------------------------------------------------------------------------------

local function hasEnabledLine(facility)
    for _, production in ipairs(facility.productions) do
        if isEnabled(production) then
            return true
        end
    end
    return false
end

function PalletDepotOverview:collect()
    local facilities = {}
    local manager = g_currentMission ~= nil and g_currentMission.productionChainManager or nil
    if manager == nil or manager.productionPoints == nil then
        return facilities
    end
    local farmId = g_currentMission:getFarmId()
    local hideInactiveSites = PalletDepotAutoManager.personal.hideInactiveSites
    for _, productionPoint in ipairs(manager.productionPoints) do
        if productionPoint:getOwnerFarmId() == farmId and productionPoint.storage ~= nil then
            local facility = self:collectFacility(productionPoint)
            if not hideInactiveSites or hasEnabledLine(facility) then
                table.insert(facilities, facility)
            end
        end
    end
    table.sort(facilities, function(a, b) return a.name:lower() < b.name:lower() end)
    return facilities
end

function PalletDepotOverview:collectFacility(productionPoint)
    local storage = productionPoint.storage
    local title = productionPoint:getName()
    local mode = ""
    if productionPoint.sharedThroughputCapacity ~= nil then
        mode = productionPoint.sharedThroughputCapacity and " (S)" or " (P)"
    end
    local facility = {
        productionPoint = productionPoint,
        isDepot = PalletDepot.isDepot(productionPoint),
        title = title,
        name = title .. mode,
        productions = productionPoint.productions or {},
        inputs = {}, outputs = {}, fillLevel = 0, capacity = 0, running = 0, attention = false
    }
    local isInput, isOutput = {}, {}
    for _, production in ipairs(facility.productions) do
        for _, input in ipairs(production.inputs or {}) do
            isInput[input.type] = true
        end
        for _, output in ipairs(production.outputs or {}) do
            isOutput[output.type] = true
        end
        if production.status == ProductionPoint.PROD_STATUS.RUNNING then
            facility.running = facility.running + 1
        end
        facility.attention = facility.attention or needsAttention(production)
    end
    for fillTypeIndex in pairs(storage.fillLevels) do
        local capacity = storage:getCapacity(fillTypeIndex) or 0
        if capacity > 0 then
            local item = {fillType = fillTypeIndex, title = fillTypeTitle(fillTypeIndex),
                fillLevel = storage:getFillLevel(fillTypeIndex) or 0, capacity = capacity}
            facility.fillLevel = facility.fillLevel + item.fillLevel
            facility.capacity = facility.capacity + capacity
            if isInput[fillTypeIndex] then
                table.insert(facility.inputs, item)
            end
            if isOutput[fillTypeIndex] or not isInput[fillTypeIndex] then
                table.insert(facility.outputs, item)
            end
        end
    end
    local byTitle = function(a, b) return a.title < b.title end
    table.sort(facility.inputs, byTitle)
    table.sort(facility.outputs, byTitle)
    return facility
end

-- depots only show stocked products
local function stocked(facility, items)
    if not facility.isDepot then
        return items
    end
    local out = {}
    for _, item in ipairs(items) do
        if item.fillLevel > PalletDepotOverview.MIN_STOCK then
            table.insert(out, item)
        end
    end
    return out
end

-- recipes of a facility for the recipes page (depots: running or stocked ones) or the logistics page
function PalletDepotOverview:getRecipes(facility, page)
    local recipes = {}
    for _, production in ipairs(facility.productions) do
        local keep = true
        if page == PAGE.LOGISTICS then
            keep = not PalletDepotOverview.hideInactive or isEnabled(production)
        elseif facility.isDepot then
            local fillType = productFillType(production)
            keep = production.status == ProductionPoint.PROD_STATUS.RUNNING
                or (fillType ~= nil and (facility.productionPoint.storage:getFillLevel(fillType) or 0) > PalletDepotOverview.MIN_STOCK)
        end
        if keep then
            table.insert(recipes, production)
        end
    end
    return recipes
end

function PalletDepotOverview:getFinances(facility)
    local value = 0
    for _, item in ipairs(facility.outputs) do
        value = value + item.fillLevel * (g_currentMission.economyManager:getPricePerLiter(item.fillType) or 0)
    end
    local daysPerMonth = g_currentMission.missionInfo.plannedDaysPerPeriod or 1
    local costs = 0
    local placeable = facility.productionPoint.owningPlaceable
    if placeable ~= nil and placeable.getDailyUpkeep ~= nil then
        costs = costs + (placeable:getDailyUpkeep() or 0) * daysPerMonth
    end
    for _, production in ipairs(facility.productions) do
        if isEnabled(production) then
            costs = costs + (production.costsPerActiveHour or 0) * 24 * daysPerMonth
        end
    end
    return value, costs
end

-- hours until the first input of a running recipe runs out, from all running recipes of the facility
function PalletDepotOverview:getSupply(facility, production)
    if production.status ~= ProductionPoint.PROD_STATUS.RUNNING then
        return cell("-", COLOR.dim)
    end
    local perHour = {}
    for _, other in ipairs(facility.productions) do
        if other.status == ProductionPoint.PROD_STATUS.RUNNING then
            for _, input in ipairs(other.inputs or {}) do
                perHour[input.type] = (perHour[input.type] or 0) + (input.amount or 0) * cyclesPerHour(other)
            end
        end
    end
    local hours = nil
    for _, input in ipairs(production.inputs or {}) do
        local use = perHour[input.type] or 0
        if use > 0 then
            local h = (facility.productionPoint.storage:getFillLevel(input.type) or 0) / use
            hours = hours == nil and h or math.min(hours, h)
        end
    end
    if hours == nil then
        return cell("N/A", COLOR.dim)
    elseif hours < 24 then
        return cell(string.format("%.1f h", hours), hours < 12 and COLOR.red or COLOR.orange)
    end
    local days = hours / 24
    if days < 30 then
        return cell(string.format("%.1f d", days))
    end
    return cell(string.format("%.1f mo", days / (g_currentMission.missionInfo.plannedDaysPerPeriod or 1)))
end

function PalletDepotOverview.getOutputMode(productionPoint, fillType)
    if productionPoint.getOutputDistributionMode ~= nil then
        return productionPoint:getOutputDistributionMode(fillType)
    end
    return ProductionPoint.OUTPUT_MODE.KEEP
end

function PalletDepotOverview:getOutputCell(productionPoint, fillType)
    local mode = PalletDepotOverview.getOutputMode(productionPoint, fillType)
    local MODE = ProductionPoint.OUTPUT_MODE
    if hasStoreMode() and mode == MODE.STORE then
        return cell(text("pdo_outputStoring"))
    elseif mode == MODE.DIRECT_SELL then
        return cell(text("pdo_outputSelling"), COLOR.green)
    elseif mode == MODE.AUTO_DELIVER then
        return cell(text("pdo_outputDistributing"), COLOR.blue)
    elseif productionPoint.palletSpawner ~= nil then
        return cell(text("pdo_outputSpawning"), COLOR.orange)
    end
    return cell(text("pdo_outputStoring"))
end

-- the first other production of the farm with an enabled recipe that uses the product
function PalletDepotOverview:getDestinationCell(productionPoint, fillType)
    local storage = productionPoint.storage
    if PalletDepotOverview.getOutputMode(productionPoint, fillType) == ProductionPoint.OUTPUT_MODE.AUTO_DELIVER then
        local manager = g_currentMission.productionChainManager
        local farm = manager.farmIds ~= nil and manager.farmIds[productionPoint:getOwnerFarmId()] or nil
        local candidates = farm ~= nil and farm.inputTypeToProductionPoints ~= nil and farm.inputTypeToProductionPoints[fillType] or {}
        for _, other in ipairs(candidates) do
            if other ~= productionPoint then
                for _, production in ipairs(other.activeProductions or {}) do
                    for _, input in ipairs(production.inputs or {}) do
                        if input.type == fillType then
                            return cell(other:getName())
                        end
                    end
                end
            end
        end
        return cell(text("pdo_destinationNotSet"), COLOR.orange)
    end
    local capacity = storage:getCapacity(fillType) or 0
    if capacity > 0 and (storage:getFillLevel(fillType) or 0) > capacity * PalletDepotOverview.FULL_SHARE then
        return cell(text("pdo_destinationFull"), COLOR.red)
    end
    return cell("-", COLOR.dim)
end

function PalletDepotOverview:getSettingValue(entry)
    if entry.scope == "pallet" then
        return PalletDepotPallets.get(self.settingsFacility.productionPoint)
    elseif entry.scope == "depot" then
        return PalletDepotOptions.get(self.settingsFacility.productionPoint)[entry.key]
    elseif entry.scope == "farm" then
        return PalletDepotAutoManager.getSettings(g_currentMission:getFarmId())[entry.key]
    end
    return PalletDepotAutoManager.personal[entry.key]
end

-- --- building the table --------------------------------------------------------------------------------

-- a row: facility (nil for spacers), name (only on a facility's first line), slots {cell...}, status, plus what the
-- keys act on: production, fillType, setting
function PalletDepotOverview:buildMainRows(rows)
    local perLine = PalletDepotOverview.PER_LINE
    for _, facility in ipairs(self.facilities) do
        local items = stocked(facility, self.showInputs and facility.inputs or facility.outputs)
        if #items == 0 then
            table.insert(rows, {facility = facility, name = facility.name, slots = {cell(text("pdo_nothingStored"), COLOR.dim)}})
        end
        for i = 1, #items, perLine do
            local row = {facility = facility, name = i == 1 and facility.name or nil, slots = {}}
            for j = i, math.min(#items, i + perLine - 1) do
                local item = items[j]
                local share = item.capacity > 0 and item.fillLevel / item.capacity or 0
                local color = item.fillLevel <= PalletDepotOverview.MIN_STOCK and COLOR.dim
                    or share > PalletDepotOverview.FULL_SHARE and COLOR.orange or COLOR.text
                table.insert(row.slots, cell(formatStock(item.fillLevel, item.capacity), color, fillTypeIcon(item.fillType)))
            end
            table.insert(rows, row)
        end
    end
end

function PalletDepotOverview:buildRecipeRows(rows)
    for _, facility in ipairs(self.facilities) do
        local recipes = self:getRecipes(facility, PAGE.RECIPES)
        if #recipes == 0 then
            table.insert(rows, {facility = facility, name = facility.name, slots = {cell(text("pdo_noRecipes"), COLOR.orange)}})
        end
        for i, production in ipairs(recipes) do
            local product = productFillType(production)
            local row = {facility = facility, name = i == 1 and facility.name or nil, production = production, fillType = product,
                slots = {cell(production.name or "?", COLOR.text, product ~= nil and fillTypeIcon(product) or nil)},
                status = statusCell(production)}
            for k, input in ipairs(production.inputs or {}) do
                if k > 4 then
                    break
                end
                table.insert(row.slots, cell(string.format("%s: %s L", fillTypeTitle(input.type), formatInt(input.amount or 0)),
                    COLOR.dim, fillTypeIcon(input.type)))
            end
            table.insert(rows, row)
        end
        table.insert(rows, {})
    end
end

function PalletDepotOverview:buildFinanceRows(rows)
    for _, facility in ipairs(self.facilities) do
        local value, costs = self:getFinances(facility)
        local net = value - costs
        table.insert(rows, {facility = facility, name = facility.name, slots = {
            cell(money(value)),
            cell(money(costs) .. text("pdo_perMonth"), COLOR.red),
            cell(money(net), net >= 0 and COLOR.green or COLOR.red)}})
    end
end

function PalletDepotOverview:buildLogisticsRows(rows)
    for _, facility in ipairs(self.facilities) do
        local recipes = self:getRecipes(facility, PAGE.LOGISTICS)
        if #facility.productions > 0 and #recipes == 0 then
            -- every recipe of this facility is inactive and hidden
        else
            if #recipes == 0 then
                table.insert(rows, {facility = facility, name = facility.name, slots = {cell(text("pdo_noActiveRecipes"), COLOR.orange)}})
            end
            local productionPoint = facility.productionPoint
            local storage = productionPoint.storage
            for i, production in ipairs(recipes) do
                local product = productFillType(production)
                local schedule = PalletDepotSchedules.get(productionPoint, production.id)
                local row = {facility = facility, name = i == 1 and facility.name or nil, production = production, fillType = product,
                    slots = {cell(production.name or "?", COLOR.text, product ~= nil and fillTypeIcon(product) or nil)},
                    status = statusCell(production, PalletDepotSchedules.isActive(schedule))}
                if product ~= nil then
                    row.slots[2] = cell(formatStock(storage:getFillLevel(product) or 0, storage:getCapacity(product) or 0))
                    row.slots[3] = self:getSupply(facility, production)
                    row.slots[4] = self:getOutputCell(productionPoint, product)
                    row.slots[5] = self:getDestinationCell(productionPoint, product)
                else
                    row.slots[2] = cell("-", COLOR.dim)
                    row.slots[3] = self:getSupply(facility, production)
                end
                table.insert(rows, row)
            end
            table.insert(rows, {})
        end
    end
end

local function settingShown(entry, facility)
    if entry.only == "depot" then
        return facility ~= nil and facility.isDepot
    elseif entry.only == "spawner" then
        return facility ~= nil and facility.productionPoint.palletSpawner ~= nil
    end
    return true
end

function PalletDepotOverview:buildSettingRows(rows)
    local facility = self.settingsFacility
    for _, entry in ipairs(SETTINGS) do
        if not settingShown(entry, facility) then
            -- production and depot rows only appear when the settings were opened on one
        elseif entry.section ~= nil then
            local title = text(entry.section)
            if entry.only ~= nil then
                title = string.format(title, facility.title)
            end
            table.insert(rows, {name = title, nameColor = COLOR.green, slots = {}})
        else
            local value = self:getSettingValue(entry)
            local shown
            if entry.format == "liters" then
                shown = cell(formatInt(value) .. " L")
            elseif entry.format == "pallet" then
                shown = cell(value == 0 and text("pdo_palletGame") or string.format(text("pdo_palletDepot"), formatInt(value)))
            elseif entry.choices ~= nil then
                shown = cell(string.format("%d %%", value))
            else
                shown = cell(text(value and "pdo_on" or "pdo_off"), value and COLOR.green or COLOR.dim)
            end
            table.insert(rows, {setting = entry, name = text(entry.name), slots = {shown, cell(text(entry.desc), COLOR.dim)}})
        end
    end
end

function PalletDepotOverview:buildRows()
    local rows = {}
    local page = self:getPage()
    if page == PAGE.SETTINGS then
        self:buildSettingRows(rows)
    elseif page == PAGE.LOGISTICS then
        self:buildLogisticsRows(rows)
    elseif page == PAGE.FINANCES then
        self:buildFinanceRows(rows)
    elseif page == PAGE.RECIPES then
        self:buildRecipeRows(rows)
    else
        self:buildMainRows(rows)
    end
    if #rows == 0 then
        table.insert(rows, {name = text("pdo_noSites"), nameColor = COLOR.dim, slots = {}})
    end
    self.rows = rows
end

-- re-reads everything and keeps the selection on the same production (and recipe or setting) where possible
function PalletDepotOverview:rebuild()
    local old = self.rows[self.rowIndex]
    local oldPoint = old ~= nil and old.facility ~= nil and old.facility.productionPoint or nil
    self.facilities = self:collect()
    self:buildRows()
    local index = math.max(1, math.min(self.rowIndex, #self.rows))
    if old ~= nil then
        local first = nil
        for i, row in ipairs(self.rows) do
            if old.setting ~= nil and row.setting == old.setting then
                first = i
                break
            elseif oldPoint ~= nil and row.facility ~= nil and row.facility.productionPoint == oldPoint then
                first = first or i
                if old.production ~= nil and row.production == old.production then
                    first = i
                    break
                end
            end
        end
        index = first or index
    end
    self.rowIndex = index
    self.table:reloadData()
    self.table:setSelectedItem(1, self.rowIndex, true)
    self:updateTexts()
    self:updateButtons()
end

-- --- drawing -------------------------------------------------------------------------------------------

function PalletDepotOverview:px(value)
    return value * self.pxToScreen
end

local PAGE_TITLES = {[PAGE.MAIN] = "pdo_tabLines", [PAGE.RECIPES] = "pdo_tabRecipes", [PAGE.FINANCES] = "pdo_tabFinances",
    [PAGE.LOGISTICS] = "pdo_tabLogistics", [PAGE.SETTINGS] = "pdo_tabSettings"}

function PalletDepotOverview:updateTexts()
    local page = self:getPage()
    local running, total = 0, 0
    for _, facility in ipairs(self.facilities) do
        running = running + facility.running
        total = total + #facility.productions
    end
    self.summaryText:setText(string.format(text("pdo_summary"), #self.facilities, running, total))
    self.titleText:setText(text(PAGE_TITLES[page]))

    for i = 1, 5 do
        local strip = self["page" .. i]
        strip:setTextColor(unpack(i == page and COLOR.text or COLOR.dim))
        if i == page then
            self.pageUnderline:setPosition(strip.position[1], nil)
        end
    end

    local layout = LAYOUT[page]
    self.headerName:setText(text(layout.headers.name))
    for i = 1, 5 do
        local header = self["header" .. i]
        local slot = layout.slots[i]
        local key = layout.headers[i]
        if page == PAGE.MAIN and i == 1 then
            key = self.showInputs and "pdo_hbInputs" or "pdo_hbOutputs"
        end
        if slot ~= nil and key ~= nil then
            header:setPosition(self:px(slot[1] + 6 + (slot[3] and 24 or 0)), nil)
            header:setSize(self:px(slot[2]), nil)
            header:setText(text(key))
            header:setVisible(true)
        else
            header:setVisible(false)
        end
    end
    if layout.status ~= nil then
        self.headerStatus:setPosition(self:px(layout.status[1] + 6), nil)
        self.headerStatus:setSize(self:px(layout.status[2]), nil)
        self.headerStatus:setText(text(layout.headers.status))
        self.headerStatus:setVisible(true)
    else
        self.headerStatus:setVisible(false)
    end
end

function PalletDepotOverview:getNumberOfItemsInSection(list, section)
    return #self.rows
end

function PalletDepotOverview:populateCellForItemInSection(list, section, index, element)
    local row = self.rows[index]
    if row == nil then
        return
    end
    local layout = LAYOUT[self:getPage()]
    local name = element:getAttribute("name")
    name:setText(row.name or "")
    local nameColor = row.nameColor or (row.facility ~= nil and row.facility.attention and COLOR.orange) or COLOR.text
    name:setTextColor(unpack(nameColor))
    for i = 1, 5 do
        local icon, label = element:getAttribute("icon" .. i), element:getAttribute("text" .. i)
        local value = row.slots ~= nil and row.slots[i] or nil
        local slot = layout.slots[i]
        if value ~= nil and slot ~= nil then
            local x = slot[1]
            if slot[3] then
                icon:setPosition(self:px(x), nil)
                if value.icon ~= nil then
                    icon:setImageFilename(value.icon)
                end
                icon:setVisible(value.icon ~= nil)
                x = x + 24
            else
                icon:setVisible(false)
            end
            label:setPosition(self:px(x), nil)
            label:setSize(self:px(slot[2] - (slot[3] and 24 or 0)), nil)
            label:setText(value.text)
            label:setTextColor(unpack(value.color or COLOR.text))
            label:setVisible(true)
        else
            icon:setVisible(false)
            label:setVisible(false)
        end
    end
    local status = element:getAttribute("status")
    if row.status ~= nil and layout.status ~= nil then
        status:setPosition(self:px(layout.status[1]), nil)
        status:setSize(self:px(layout.status[2]), nil)
        status:setText(row.status.text)
        status:setTextColor(unpack(row.status.color))
        status:setVisible(true)
    else
        status:setVisible(false)
    end
end

function PalletDepotOverview:onListSelectionChanged(list, section, index)
    self.rowIndex = index
    self:updateButtons()
end

function PalletDepotOverview:getSelectedRow()
    return self.rows[self.rowIndex]
end

-- --- buttons and keys ----------------------------------------------------------------------------------

-- as in the old depot: offered for the selected own production with pickup lanes while Production Storage Control is
-- installed
function PalletDepotOverview:getSpawnProductionPoint()
    local row = self:getSelectedRow()
    local productionPoint = row ~= nil and row.facility ~= nil and row.facility.productionPoint or nil
    if getPSC() == nil or productionPoint == nil or productionPoint.palletSpawner == nil or productionPoint.activatable == nil
        or productionPoint:getOwnerFarmId() ~= g_currentMission:getFarmId() then
        return nil
    end
    return productionPoint
end

function PalletDepotOverview:updateButtons()
    local page = self:getPage()
    local row = self:getSelectedRow()
    local recipeSelected = row ~= nil and row.production ~= nil

    self.toggleButton:setVisible(page == PAGE.MAIN)
    self.toggleButton:setText(text(self.showInputs and "pdo_btnShowOutputs" or "pdo_btnShowInputs"))
    self.toggleButton:setInputAction(InputAction.MENU_EXTRA_1)
    self.scheduleButton:setVisible(page == PAGE.LOGISTICS and recipeSelected)
    self.scheduleButton:setInputAction(InputAction.MENU_EXTRA_1)

    self.recipeButton:setVisible(page == PAGE.MAIN or page == PAGE.RECIPES)
    self.recipeButton:setText(text(self.showRecipes and "pdo_btnShowFillTypes" or "pdo_btnShowRecipes"))
    self.recipeButton:setInputAction(InputAction.MENU_EXTRA_2)
    self.inactiveButton:setVisible(page == PAGE.LOGISTICS)
    self.inactiveButton:setText(text(PalletDepotOverview.hideInactive and "pdo_btnShowInactive" or "pdo_btnHideInactive"))
    self.inactiveButton:setInputAction(InputAction.MENU_EXTRA_2)

    self.financesButton:setVisible(page == PAGE.MAIN or page == PAGE.RECIPES or page == PAGE.FINANCES)
    self.financesButton:setText(text(self.showFinances and "pdo_btnHideFinances" or "pdo_btnShowFinances"))
    self.financesButton:setInputAction(InputAction.MENU_PAGE_PREV)

    self.settingsButton:setVisible(page == PAGE.MAIN)
    self.settingsButton:setInputAction(InputAction.MENU_ACCEPT)
    self.changeOutputButton:setVisible(page == PAGE.LOGISTICS and recipeSelected and row.fillType ~= nil)
    self.changeOutputButton:setInputAction(InputAction.MENU_ACCEPT)
    self.changeSettingButton:setVisible(page == PAGE.SETTINGS and row ~= nil and row.setting ~= nil)
    self.changeSettingButton:setInputAction(InputAction.MENU_ACCEPT)

    self.activateButton:setVisible((page == PAGE.RECIPES or page == PAGE.LOGISTICS) and recipeSelected)
    if recipeSelected then
        self.activateButton:setText(text(isEnabled(row.production) and "pdo_btnDeactivate" or "pdo_btnActivate"))
    end
    self.activateButton:setInputAction(InputAction.MENU_CANCEL)
    self.spawnButton:setVisible((page == PAGE.MAIN or page == PAGE.FINANCES or page == PAGE.LOGISTICS)
        and self:getSpawnProductionPoint() ~= nil)
    self.spawnButton:setInputAction(page == PAGE.LOGISTICS and InputAction.MENU_PAGE_PREV or InputAction.MENU_CANCEL)
    self.backButton:setVisible(page == PAGE.SETTINGS)
    self.backButton:setInputAction(InputAction.MENU_CANCEL)

    self.logisticsButton:setVisible(page ~= PAGE.SETTINGS)
    self.logisticsButton:setText(text(self.showLogistics and "pdo_btnHideLogistics" or "pdo_btnShowLogistics"))
    self.logisticsButton:setInputAction(InputAction.MENU_PAGE_NEXT)
    self.exportButton:setVisible(page ~= PAGE.SETTINGS)
    self.exportButton:setInputAction(InputAction.MENU_ACTIVATE)

    -- the button bar keeps its old cell positions until it is laid out again
    local box = self.buttonBox
    if box ~= nil and box.updateLayoutCells ~= nil and box.applyCellPositions ~= nil then
        box:updateLayoutCells()
        box:applyCellPositions(0, 0)
    end
end

-- a menu key runs the visible button bound to it on this page
function PalletDepotOverview:inputEvent(action, value, eventUsed)
    if not eventUsed and value ~= 0 then
        local page = self:getPage()
        for _, key in ipairs(KEYS) do
            local button = self[key.button]
            if action == InputAction[key.action] and (key.pages == nil or contains(key.pages, page))
                and button ~= nil and button:getIsVisible() then
                self[key.handler](self)
                return true
            end
        end
    end
    return PalletDepotOverview:superClass().inputEvent(self, action, value, eventUsed)
end

-- --- pages ---------------------------------------------------------------------------------------------

function PalletDepotOverview:onClickToggleInputs()
    self.showInputs = not self.showInputs
    self:rebuild()
end

function PalletDepotOverview:onClickRecipes()
    self.showRecipes = not self.showRecipes
    self:rebuild()
end

function PalletDepotOverview:onClickFinances()
    self.showFinances = not self.showFinances
    self:rebuild()
end

function PalletDepotOverview:onClickLogistics()
    self.showLogistics = not self.showLogistics
    self.showRecipes = false
    self:rebuild()
end

function PalletDepotOverview:onClickHideInactive()
    PalletDepotOverview.hideInactive = not PalletDepotOverview.hideInactive
    self:rebuild()
end

-- Enter on the productions page: settings, with the depot's own settings when a depot is selected
function PalletDepotOverview:onClickSettings()
    local row = self:getSelectedRow()
    self.settingsFacility = row ~= nil and row.facility or nil
    self.showSettings = true
    self.rowIndex = 2       -- the first setting, below its section title
    self:rebuild()
end

function PalletDepotOverview:onClickSettingsBack()
    self.showSettings = false
    local facility = self.settingsFacility
    self:rebuild()
    -- back on the production the settings were opened from
    if facility ~= nil then
        for i, row in ipairs(self.rows) do
            if row.facility ~= nil and row.facility.productionPoint == facility.productionPoint then
                self.rowIndex = i
                self.table:setSelectedItem(1, i, true)
                break
            end
        end
    end
end

-- a click on the page strip opens that page
function PalletDepotOverview:openPage(page)
    self.showRecipes = page == PAGE.RECIPES
    self.showFinances = page == PAGE.FINANCES
    self.showLogistics = page == PAGE.LOGISTICS
    if page == PAGE.SETTINGS then
        if not self.showSettings then
            self:onClickSettings()
        end
        return
    end
    self.showSettings = false
    self:rebuild()
end

function PalletDepotOverview:onClickPage1() self:openPage(PAGE.MAIN) end
function PalletDepotOverview:onClickPage2() self:openPage(PAGE.RECIPES) end
function PalletDepotOverview:onClickPage3() self:openPage(PAGE.FINANCES) end
function PalletDepotOverview:onClickPage4() self:openPage(PAGE.LOGISTICS) end
function PalletDepotOverview:onClickPage5() self:openPage(PAGE.SETTINGS) end

-- --- recipe actions ------------------------------------------------------------------------------------

function PalletDepotOverview:canManage()
    if g_currentMission.getHasPlayerPermission ~= nil and not g_currentMission:getHasPlayerPermission("manageProductions") then
        InfoDialog.show(text("pdo_noPermission"))
        return false
    end
    return true
end

function PalletDepotOverview.getNextOutputMode(mode)
    local MODE = ProductionPoint.OUTPUT_MODE
    if hasStoreMode() then
        local nextMode = {[MODE.STORE] = MODE.KEEP, [MODE.KEEP] = MODE.AUTO_DELIVER,
            [MODE.AUTO_DELIVER] = MODE.DIRECT_SELL, [MODE.DIRECT_SELL] = MODE.STORE}
        return nextMode[mode] or MODE.STORE
    end
    local nextMode = {[MODE.KEEP] = MODE.AUTO_DELIVER, [MODE.AUTO_DELIVER] = MODE.DIRECT_SELL, [MODE.DIRECT_SELL] = MODE.KEEP}
    return nextMode[mode] or MODE.KEEP
end

function PalletDepotOverview:onClickChangeOutput()
    local row = self:getSelectedRow()
    if row == nil or row.production == nil or row.facility == nil or not self:canManage() then
        return
    end
    local productionPoint = row.facility.productionPoint
    local fillType = productFillType(row.production)
    if fillType == nil then
        InfoDialog.show(text("pdo_noOutput"))
        return
    end
    local mode = PalletDepotOverview.getNextOutputMode(PalletDepotOverview.getOutputMode(productionPoint, fillType))
    ProductionPointOutputModeEvent.sendEvent(productionPoint, fillType, mode, false)
    productionPoint:setOutputDistributionMode(fillType, mode, true)
    self:rebuild()
end

function PalletDepotOverview:onClickActivate()
    local row = self:getSelectedRow()
    if row == nil or row.production == nil or row.facility == nil or not self:canManage() then
        return
    end
    local productionPoint = row.facility.productionPoint
    local enable = not isEnabled(row.production)
    ProductionPointProductionStateEvent.sendEvent(productionPoint, row.production.id, enable, false)
    productionPoint:setProductionState(row.production.id, enable, true)
    self:rebuild()
end

-- Enter on the settings page: next value of the selected setting
function PalletDepotOverview:onClickChangeSetting()
    local row = self:getSelectedRow()
    local entry = row ~= nil and row.setting or nil
    if entry == nil then
        return
    end
    local value = self:getSettingValue(entry)
    if entry.choices ~= nil then
        local owner = entry.scope == "pallet" and PalletDepotPallets or entry.scope == "depot" and PalletDepotOptions
            or PalletDepotAutoManager
        local choices = owner[entry.choices]
        local nextValue = choices[1]
        for i, choice in ipairs(choices) do
            if choice == value then
                nextValue = choices[i % #choices + 1]
            end
        end
        value = nextValue
    else
        value = not value
    end
    if entry.scope == "pallet" then
        if not self:canManage() then
            return
        end
        PalletDepotPallets.request(self.settingsFacility.productionPoint, value)
    elseif entry.scope == "depot" then
        if not self:canManage() then
            return
        end
        PalletDepotOptions.request(self.settingsFacility.productionPoint, value)
    elseif entry.scope == "farm" then
        if not self:canManage() then
            return
        end
        local farmId = g_currentMission:getFarmId()
        local copy = {}
        for k, v in pairs(PalletDepotAutoManager.getSettings(farmId)) do
            copy[k] = v
        end
        copy[entry.key] = value
        PalletDepotAutoManager.requestSettings(farmId, copy)
    else
        PalletDepotAutoManager.personal[entry.key] = value
        PalletDepotAutoManager.savePersonal()
    end
    self:rebuild()
end

function PalletDepotOverview:onClickSchedule()
    local row = self:getSelectedRow()
    if row == nil or row.production == nil or row.facility == nil or not self:canManage() then
        return
    end
    PalletDepotScheduleDialog.show(row.facility.productionPoint, row.production, row.facility.title, function()
        self:rebuild()
    end)
end

function PalletDepotOverview:onClickSpawnGoods()
    local productionPoint = self:getSpawnProductionPoint()
    if productionPoint == nil then
        return
    end
    -- remember the selected recipe's product to preselect it in the spawn dialog
    local row = self:getSelectedRow()
    local fillTypeIndex = row ~= nil and row.fillType or nil

    productionPoint.activatable:run(true)       -- opens Production Storage Control's spawn dialog

    if fillTypeIndex ~= nil then
        local psc = getPSC()
        local dialogClass = psc ~= nil and psc.ProductionStorageDialog or nil
        local dialog = dialogClass ~= nil and dialogClass.INSTANCE or nil
        if dialog ~= nil and dialog.options ~= nil and dialog.fillTypeElement ~= nil then
            for i, option in ipairs(dialog.options) do
                if option.fillTypeIndex == fillTypeIndex then
                    dialog.fillTypeElement:setState(i, true)
                    break
                end
            end
        end
    end
end

-- --- CSV export ----------------------------------------------------------------------------------------

local function csvField(value)
    return '"' .. tostring(value):gsub('"', '""') .. '"'
end

function PalletDepotOverview:onClickExport()
    if #self.facilities == 0 then
        InfoDialog.show(text("pdo_exportNothing"))
        return
    end
    local folder = getUserProfileAppPath() .. "modSettings/PalletDepot/"
    createFolder(getUserProfileAppPath() .. "modSettings/")
    createFolder(folder)
    local environment = g_currentMission.environment
    local filename = string.format("%sproductions_Y%02d_P%02d_D%02d.csv", folder, environment.currentYear or 0,
        environment.currentPeriod or 0, environment.currentDayInPeriod or 0)
    local file = io.open(filename, "w")
    if file == nil then
        InfoDialog.show(text("pdo_exportFailed"))
        return
    end
    local currency = g_i18n:getCurrencySymbol(true)
    local header = {"Production", "Lines running", "Type", "Fill type", "Amount (L)", "Capacity (L)", "Fill %",
        "Stock value (" .. currency .. ")", "Costs per month (" .. currency .. ")", "Net (" .. currency .. ")"}
    for i, h in ipairs(header) do
        header[i] = csvField(h)
    end
    local lines = {table.concat(header, ",")}
    for _, facility in ipairs(self.facilities) do
        local running = string.format("%d/%d", facility.running, #facility.productions)
        for _, list in ipairs({{"Input", stocked(facility, facility.inputs)}, {"Output", stocked(facility, facility.outputs)}}) do
            for _, item in ipairs(list[2]) do
                local share = item.capacity > 0 and item.fillLevel / item.capacity * 100 or 0
                table.insert(lines, table.concat({csvField(facility.name), csvField(running), csvField(list[1]),
                    csvField(item.title), csvField(math.floor(item.fillLevel)), csvField(math.floor(item.capacity)),
                    csvField(string.format("%.2f", share)), '""', '""', '""'}, ","))
            end
        end
        local value, costs = self:getFinances(facility)
        table.insert(lines, table.concat({csvField(facility.name), csvField(running), csvField("Finances"), '""', '""', '""', '""',
            csvField(math.floor(value)), csvField(math.floor(costs)), csvField(math.floor(value - costs))}, ","))
    end
    file:write("\239\187\191" .. table.concat(lines, "\n") .. "\n")
    file:close()
    InfoDialog.show(string.format(text("pdo_exportDone"), filename))
end

-- --- key binding ---------------------------------------------------------------------------------------

function PalletDepotOverview.onInputAction()
    PalletDepotOverview.show()
end

function PalletDepotOverview.registerActionEvents(playerInputComponent, controlling)
    local _, actionEventId = g_inputBinding:registerActionEvent(InputAction.PALLET_DEPOT_OVERVIEW, PalletDepotOverview,
        PalletDepotOverview.onInputAction, false, true, false, true, nil, true)
    if actionEventId ~= nil then
        g_inputBinding:setActionEventTextPriority(actionEventId, GS_PRIO_VERY_LOW)
        g_inputBinding:setActionEventTextVisibility(actionEventId, true)
    end
end

PlayerInputComponent.registerGlobalPlayerActionEvents = Utils.appendedFunction(
    PlayerInputComponent.registerGlobalPlayerActionEvents, PalletDepotOverview.registerActionEvents)
