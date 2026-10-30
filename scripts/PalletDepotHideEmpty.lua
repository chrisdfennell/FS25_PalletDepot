-- Pallet Depot: shorten the production menu's lists for a depot.
--
-- A depot stores up to 186 products, so the "Incoming materials" / "Outgoing products" sections of the production
-- menu's details list are mostly 0 L rows, and the products (production lines) list shows every product. Both lists
-- are built from the production point's tables, so while the menu functions that build them run for a depot, the
-- tables are swapped for filtered copies, then restored:
-- * details list: only fill types with stock
-- * products list: products made by a factory the depot's farm owns, plus any product the depot has in stock (so
--   goods unloaded by mistake can still be taken out). Factories = the farm's production points, without depots and
--   without pass-through storages (every line puts out what it takes in)
-- getSelectedProduction is wrapped too, so a selected row in the shortened products list maps to the right product.
-- The menu's buttons and its update loop are untouched. One menu button (C) toggles the hiding on and off.

PalletDepotHideEmpty = {}
PalletDepotHideEmpty.MIN_LITERS = 0.5
PalletDepotHideEmpty.SNAPSHOT_MAX_AGE = 1000  -- ms; stock levels are re-read at most once per second
PalletDepotHideEmpty.enabled = true
PalletDepotHideEmpty.logged = {}
PalletDepotHideEmpty.original = {}
PalletDepotHideEmpty.snapshots = {}
PalletDepotHideEmpty.depth = 0

-- only functions that build or fill lists; button actions and the update loop are not touched.
-- The inj_/pre_ variants are the same functions as injected by other mods that hook this menu; absent ones are skipped
PalletDepotHideEmpty.LIST_FUNCTIONS = {
    "getNumberOfSections", "getNumberOfItemsInSection", "getTitleForSectionHeader", "getCellTypeForItemInSection",
    "populateCellForItemInSection", "inj_getNumberOfSections", "inj_getNumberOfItemsInSection",
    "inj_getTitleForSectionHeader", "inj_getCellTypeForItemInSection", "inj_populateCellForItemInSection",
    "onListSelectionChanged", "setSelectedProductionPoint", "updateProductionLists", "onFrameOpen", "pre_onFrameOpen",
    "getSelectedProduction"
}
-- the production point tables the details list and the products list are built from
PalletDepotHideEmpty.TABLES = {"inputFillTypeIdsArray", "outputFillTypeIdsArray", "inputFillTypeIds", "outputFillTypeIds",
    "productions"}

local function logOnce(key, message, ...)
    if not PalletDepotHideEmpty.logged[key] then
        PalletDepotHideEmpty.logged[key] = true
        Logging.info("[%s] HideEmpty: " .. message, PalletDepot.modName, ...)
    end
end

local function getSelectedDepot(frame)
    local productionPoint = frame.selectedProductionPoint
    if productionPoint == nil then
        local getSelected = PalletDepotHideEmpty.original.getSelectedProduction
        if getSelected == nil then
            return nil
        end
        local ok, _, selectedPoint = pcall(getSelected, frame)
        if not ok then
            return nil
        end
        productionPoint = selectedPoint
    end
    if not PalletDepot.isDepot(productionPoint) or productionPoint.storage == nil then
        return nil
    end
    for _, name in ipairs(PalletDepotHideEmpty.TABLES) do
        if productionPoint[name] == nil then
            logOnce("missing:" .. name, "production point has no '%s' table", name)
            return nil
        end
    end
    return productionPoint
end

local function isStocked(productionPoint, fillTypeIndex)
    return (productionPoint.storage:getFillLevel(fillTypeIndex) or 0) > PalletDepotHideEmpty.MIN_LITERS
end

-- a storage-type production point: every line puts out exactly what it takes in
local function isPassThrough(productionPoint)
    for _, production in ipairs(productionPoint.productions or {}) do
        local inputs, outputs = production.inputs or {}, production.outputs or {}
        if #inputs ~= 1 or #outputs ~= 1 or inputs[1].type ~= outputs[1].type then
            return false
        end
    end
    return true
end

-- fill types put out by the factories the farm owns
local function getOwnedOutputs(farmId)
    local outputs = {}
    local manager = g_currentMission ~= nil and g_currentMission.productionChainManager or nil
    for _, productionPoint in ipairs(manager ~= nil and manager.productionPoints or {}) do
        if productionPoint:getOwnerFarmId() == farmId and not PalletDepot.isDepot(productionPoint)
            and not isPassThrough(productionPoint) then
            for _, production in ipairs(productionPoint.productions or {}) do
                for _, item in ipairs(production.outputs or {}) do
                    if item.type ~= nil then
                        outputs[item.type] = true
                    end
                end
            end
        end
    end
    return outputs
end

-- a depot product (production line) is shown when a factory of the farm makes it or the depot has it in stock
local function buildProductions(productionPoint)
    local owned = getOwnedOutputs(productionPoint:getOwnerFarmId())
    local shown = {}
    for _, production in ipairs(productionPoint.productions) do
        local show = false
        for _, item in ipairs(production.outputs or {}) do
            if item.type ~= nil and (owned[item.type] or isStocked(productionPoint, item.type)) then
                show = true
            end
        end
        if show then
            table.insert(shown, production)
        end
    end
    logOnce("products", "products list shows %d of %d products", #shown, #productionPoint.productions)
    -- never an empty products list
    if #shown == 0 then
        return productionPoint.productions
    end
    return shown
end

local function buildSnapshot(productionPoint, now, productions)
    local snapshot = {time = now, productions = productions or buildProductions(productionPoint)}
    for _, name in ipairs({"inputFillTypeIdsArray", "outputFillTypeIdsArray"}) do
        local stocked = {}
        for _, fillTypeIndex in ipairs(productionPoint[name]) do
            if isStocked(productionPoint, fillTypeIndex) then
                table.insert(stocked, fillTypeIndex)
            end
        end
        snapshot[name] = stocked
    end
    for _, name in ipairs({"inputFillTypeIds", "outputFillTypeIds"}) do
        local stocked = {}
        for fillTypeIndex, value in pairs(productionPoint[name]) do
            if isStocked(productionPoint, fillTypeIndex) then
                stocked[fillTypeIndex] = value
            end
        end
        snapshot[name] = stocked
    end
    return snapshot
end

-- filtered copies of the tables, rebuilt only when forced (button), when another depot gets selected, or when a
-- list starts a full reload, never while a list draws its rows, so row counts and contents come from one copy.
-- The products copy is kept on a list reload, so the products list's rows never shift under the selection
local function getSnapshot(productionPoint, force)
    local snapshot = PalletDepotHideEmpty.snapshots[productionPoint]
    local now = g_time or 0
    local keepProductions = false
    if PalletDepotHideEmpty.lastSelected ~= productionPoint then
        PalletDepotHideEmpty.lastSelected = productionPoint
        force = true
    end
    if force == "reload" then
        force = snapshot ~= nil and now - snapshot.time > PalletDepotHideEmpty.SNAPSHOT_MAX_AGE
        keepProductions = true
    end
    if force or snapshot == nil then
        snapshot = buildSnapshot(productionPoint, now, keepProductions and snapshot ~= nil and snapshot.productions or nil)
        PalletDepotHideEmpty.snapshots[productionPoint] = snapshot
    end
    return snapshot
end

-- runs a list-building menu function with the selected depot's tables swapped for the stocked-only copies
local function wrap(name, originalFunc)
    return function(frame, ...)
        if PalletDepotHideEmpty.depth > 0 or not PalletDepotHideEmpty.enabled or type(frame) ~= "table" then
            return originalFunc(frame, ...)
        end
        local productionPoint = getSelectedDepot(frame)
        if productionPoint == nil then
            return originalFunc(frame, ...)
        end

        local listReloadStart = (name == "getNumberOfItemsInSection" or name == "inj_getNumberOfItemsInSection")
            and select(2, ...) == 1
        local snapshot = getSnapshot(productionPoint, listReloadStart and "reload" or false)
        local saved = {}
        for _, tableName in ipairs(PalletDepotHideEmpty.TABLES) do
            saved[tableName] = productionPoint[tableName]
            productionPoint[tableName] = snapshot[tableName]
        end
        PalletDepotHideEmpty.depth = PalletDepotHideEmpty.depth + 1

        local result = {pcall(originalFunc, frame, ...)}

        PalletDepotHideEmpty.depth = PalletDepotHideEmpty.depth - 1
        for tableName, original in pairs(saved) do
            productionPoint[tableName] = original
        end
        if not result[1] then
            error(result[2], 0)
        end
        return unpack(result, 2, table.maxn(result))
    end
end

function PalletDepotHideEmpty.toggle(frame)
    PalletDepotHideEmpty.enabled = not PalletDepotHideEmpty.enabled
    local productionPoint = getSelectedDepot(frame)
    if productionPoint ~= nil then
        getSnapshot(productionPoint, true)
    end

    -- rebuild the products list, then re-run the menu's own "product selected" handler, which rebuilds the details
    -- list, and keep its scroll position
    if frame.productsList ~= nil and frame.productsList.reloadData ~= nil then
        frame.productsList:reloadData()
    end
    local detailsList = frame.detailsList
    local viewOffset = detailsList ~= nil and detailsList.viewOffset or nil
    if frame.productsList ~= nil and frame.onListSelectionChanged ~= nil then
        local section, index = frame.productsList:getSelectedPath()
        local ok, err = pcall(frame.onListSelectionChanged, frame, frame.productsList, section, index)
        if not ok then
            logOnce("refresh", "refreshing the details list failed: %s", tostring(err))
        end
    end
    if detailsList ~= nil and detailsList.reloadData ~= nil then
        detailsList:reloadData()
        if viewOffset ~= nil then
            detailsList.viewOffset, detailsList.targetViewOffset = viewOffset, viewOffset
            detailsList:updateView(true, true)
        end
    end
    frame:updateMenuButtons()
end

-- adds the "Show all materials" / "Hide empty materials" button to the bottom bar while a depot is selected
function PalletDepotHideEmpty.updateMenuButtons(frame)
    if frame.menuButtonInfo == nil or getSelectedDepot(frame) == nil then
        return
    end
    table.insert(frame.menuButtonInfo, {
        inputAction = InputAction.MENU_EXTRA_2,
        text = g_i18n:getText(PalletDepotHideEmpty.enabled and "depot_showMaterials" or "depot_hideMaterials"),
        callback = function()
            PalletDepotHideEmpty.toggle(frame)
        end
    })
    frame:setMenuButtonInfoDirty()
end

if InGameMenuProductionFrame ~= nil then
    PalletDepotHideEmpty.original.getSelectedProduction = InGameMenuProductionFrame.getSelectedProduction
    local wrapped = {}
    for _, name in ipairs(PalletDepotHideEmpty.LIST_FUNCTIONS) do
        if type(InGameMenuProductionFrame[name]) == "function" then
            InGameMenuProductionFrame[name] = wrap(name, InGameMenuProductionFrame[name])
            table.insert(wrapped, name)
        end
    end
    -- each time the menu opens, stock and owned factories are read again
    if InGameMenuProductionFrame.onFrameOpen ~= nil then
        InGameMenuProductionFrame.onFrameOpen = Utils.prependedFunction(InGameMenuProductionFrame.onFrameOpen, function()
            PalletDepotHideEmpty.snapshots = {}
            PalletDepotHideEmpty.lastSelected = nil
        end)
    end
    if InGameMenuProductionFrame.updateMenuButtons ~= nil then
        InGameMenuProductionFrame.updateMenuButtons = Utils.appendedFunction(InGameMenuProductionFrame.updateMenuButtons,
            PalletDepotHideEmpty.updateMenuButtons)
    end
    Logging.info("[%s] HideEmpty: wrapped %s", PalletDepot.modName, table.concat(wrapped, ", "))
else
    Logging.warning("[%s] InGameMenuProductionFrame not found, empty materials will not be hidden", PalletDepot.modName)
end
