-- Pallet Depot: names every production line after its product.
--
-- Each line stores one product (1 L in -> 1 L out), so its name is the fill type's title. The placeable XML
-- cannot provide it for FedMods products, because their texts live in the Fed mods' own environment; the
-- fill type itself already holds the translated title, so we copy it once the production point has loaded.

PalletDepotLineNames = {}
PalletDepotLineNames.modName = g_currentModName

function PalletDepotLineNames.isDepot(productionPoint, customEnvironment)
    local placeable = productionPoint.owningPlaceable
    return customEnvironment == PalletDepotLineNames.modName
        or (placeable ~= nil and placeable.customEnvironment == PalletDepotLineNames.modName)
end

function PalletDepotLineNames.productFillType(production)
    if production.primaryProductFillType ~= nil then
        return production.primaryProductFillType
    end
    local output = production.outputs ~= nil and production.outputs[1] or nil
    return output ~= nil and output.type or nil
end

function PalletDepotLineNames.load(productionPoint, superFunc, components, xmlFile, key, customEnvironment, ...)
    local success = superFunc(productionPoint, components, xmlFile, key, customEnvironment, ...)
    if success and PalletDepotLineNames.isDepot(productionPoint, customEnvironment) then
        for _, production in ipairs(productionPoint.productions or {}) do
            local fillTypeIndex = PalletDepotLineNames.productFillType(production)
            local title = fillTypeIndex ~= nil and g_fillTypeManager:getFillTypeTitleByIndex(fillTypeIndex) or nil
            if title ~= nil then
                production.name = title
            end
        end
    end
    return success
end

ProductionPoint.load = Utils.overwrittenFunction(ProductionPoint.load, PalletDepotLineNames.load)
