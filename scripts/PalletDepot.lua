-- Pallet Depot: helpers shared by the depot scripts (loaded first).

PalletDepot = {}
PalletDepot.modName = g_currentModName
PalletDepot.modDirectory = g_currentModDirectory

function PalletDepot.isDepotPlaceable(placeable)
    if placeable == nil then
        return false
    end
    if placeable.customEnvironment == PalletDepot.modName then
        return true
    end
    local file = placeable.configFileName
    return file ~= nil and string.find(file, PalletDepot.modName, 1, true) ~= nil
end

function PalletDepot.isDepot(productionPoint)
    return productionPoint ~= nil and PalletDepot.isDepotPlaceable(productionPoint.owningPlaceable)
end

-- all depots on the map with a storage; only those of farmId when given
function PalletDepot.getDepots(farmId)
    local depots = {}
    local manager = g_currentMission ~= nil and g_currentMission.productionChainManager or nil
    if manager == nil or manager.productionPoints == nil then
        return depots
    end
    for _, productionPoint in ipairs(manager.productionPoints) do
        if productionPoint.storage ~= nil and productionPoint.storage.fillLevels ~= nil and PalletDepot.isDepot(productionPoint)
            and (farmId == nil or productionPoint:getOwnerFarmId() == farmId) then
            table.insert(depots, productionPoint)
        end
    end
    return depots
end

function PalletDepot.getTotalStock(productionPoint)
    local liters = 0
    for _, level in pairs(productionPoint.storage.fillLevels) do
        liters = liters + level
    end
    return liters
end

-- depth-first search for a child node by name, at most depth levels down
function PalletDepot.findChild(node, name, depth)
    for i = 0, getNumOfChildren(node) - 1 do
        local child = getChildAt(node, i)
        if getName(child) == name then
            return child
        end
        if depth > 0 then
            local found = PalletDepot.findChild(child, name, depth - 1)
            if found ~= nil then
                return found
            end
        end
    end
    return nil
end
