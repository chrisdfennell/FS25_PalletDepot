-- Pallet Depot: lets both depots load with or without the FedMods packs.
--
-- The depots list the base products and the FedMods products. Before a depot's production point reads its
-- XML, this removes every line, storage capacity and trigger fill type whose product the game does not
-- know, so without the Fed packs the depot simply offers the base products.

PalletDepotOptionalProducts = {}
PalletDepotOptionalProducts.modName = g_currentModName

function PalletDepotOptionalProducts.isKnown(fillTypeName)
    return fillTypeName ~= nil and g_fillTypeManager:getFillTypeIndexByName(fillTypeName) ~= nil
end

-- removes the elements at path(i) whose fill type (path(i) .. attribute) is unknown; returns how many
function PalletDepotOptionalProducts.removeUnknown(xmlFile, path, attribute)
    local unknownKeys = {}
    xmlFile:iterate(path, function(_, elementKey)
        if not PalletDepotOptionalProducts.isKnown(xmlFile:getString(elementKey .. attribute)) then
            table.insert(unknownKeys, elementKey)
        end
    end)
    for i = #unknownKeys, 1, -1 do        -- last first, so the remaining indices stay valid
        xmlFile:removeProperty(unknownKeys[i])
    end
    return #unknownKeys
end

-- keeps only known names in a space-separated fillTypes attribute of every element at path(i)
function PalletDepotOptionalProducts.filterLists(xmlFile, path)
    xmlFile:iterate(path, function(_, elementKey)
        local names = xmlFile:getString(elementKey .. "#fillTypes")
        if names ~= nil then
            local known = {}
            for _, name in ipairs(string.split(names, " ")) do
                if PalletDepotOptionalProducts.isKnown(name) then
                    table.insert(known, name)
                end
            end
            xmlFile:setString(elementKey .. "#fillTypes", table.concat(known, " "))
        end
    end)
end

function PalletDepotOptionalProducts.load(productionPoint, superFunc, components, xmlFile, key, customEnvironment, ...)
    if customEnvironment == PalletDepotOptionalProducts.modName then
        local skipped = PalletDepotOptionalProducts.removeUnknown(xmlFile, key .. ".productions.production",
            ".outputs.output(0)#fillType")
        if skipped > 0 then
            PalletDepotOptionalProducts.removeUnknown(xmlFile, key .. ".storage.capacity", "#fillType")
            PalletDepotOptionalProducts.filterLists(xmlFile, key .. ".sellingStation.unloadTrigger")
            PalletDepotOptionalProducts.filterLists(xmlFile, key .. ".sellingStation.palletTrigger")
            Logging.info("Pallet Depot: %d products skipped, their mods (FedMods packs) are not loaded", skipped)
        end
    end
    return superFunc(productionPoint, components, xmlFile, key, customEnvironment, ...)
end

ProductionPoint.load = Utils.overwrittenFunction(ProductionPoint.load, PalletDepotOptionalProducts.load)
