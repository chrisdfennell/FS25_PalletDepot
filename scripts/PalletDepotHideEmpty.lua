-- Pallet Depot: hide empty materials in the production menu's details list.
--
-- A depot stores up to 184 products, so the "Incoming materials" / "Outgoing products" sections of the production
-- menu's details list are mostly 0 L rows. That list is built from the production point's fill type tables, so while
-- the menu functions that build it run for a depot, the tables are swapped for copies that only hold fill types with
-- stock, then restored. The products (production lines) list, the menu's buttons and its update loop are untouched.
-- One menu button (C) toggles the hiding on and off for the session.

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
    "onListSelectionChanged", "setSelectedProductionPoint", "updateProductionLists", "onFrameOpen", "pre_onFrameOpen"
}
-- the production point tables the details list is built from
PalletDepotHideEmpty.TABLES = {"inputFillTypeIdsArray", "outputFillTypeIdsArray", "inputFillTypeIds", "outputFillTypeIds"}

local function logOnce(key, message, ...)
    if not PalletDepotHideEmpty.logged[key] then
        PalletDepotHideEmpty.logged[key] = true
        Logging.info("[%s] HideEmpty: " .. message, PalletDepot.modName, ...)
    end
end

local function getSelectedDepot(frame)
    local getSelected = PalletDepotHideEmpty.original.getSelectedProduction
    if getSelected == nil then
        return nil
    end
    local ok, _, productionPoint = pcall(getSelected, frame)
    if not ok or not PalletDepot.isDepot(productionPoint) or productionPoint.storage == nil then
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

local function buildSnapshot(productionPoint, now)
    local snapshot = {time = now}
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
-- list starts a full reload, never while a list draws its rows, so row counts and contents come from one copy
local function getSnapshot(productionPoint, force)
    local snapshot = PalletDepotHideEmpty.snapshots[productionPoint]
    local now = g_time or 0
    if PalletDepotHideEmpty.lastSelected ~= productionPoint then
        PalletDepotHideEmpty.lastSelected = productionPoint
        force = true
    end
    if force == "reload" then
        force = snapshot ~= nil and now - snapshot.time > PalletDepotHideEmpty.SNAPSHOT_MAX_AGE
    end
    if force or snapshot == nil then
        snapshot = buildSnapshot(productionPoint, now)
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

    -- re-run the menu's own "product selected" handler, which rebuilds the details list, and keep its scroll position
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
    if InGameMenuProductionFrame.updateMenuButtons ~= nil then
        InGameMenuProductionFrame.updateMenuButtons = Utils.appendedFunction(InGameMenuProductionFrame.updateMenuButtons,
            PalletDepotHideEmpty.updateMenuButtons)
    end
    Logging.info("[%s] HideEmpty: wrapped %s", PalletDepot.modName, table.concat(wrapped, ", "))
else
    Logging.warning("[%s] InGameMenuProductionFrame not found, empty materials will not be hidden", PalletDepot.modName)
end
