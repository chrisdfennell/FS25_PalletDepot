-- Pallet Depot: optional fix for "Price Ticker" (FS25_PriceTicker).
--
-- Price Ticker lists every selling station the economy knows, including the unload pads of production buildings,
-- and ignores the game's hideFromPricesMenu flag. The depots only store goods, so they are taken out of its station
-- list. Price Ticker's files are not changed; this does nothing when Price Ticker is not installed.

PalletDepotPriceTicker = {}

-- the unload pads of all depots on the map
local function getDepotStations()
    local set = {}
    for _, productionPoint in ipairs(PalletDepot.getDepots()) do
        if productionPoint.unloadingStation ~= nil then
            set[productionPoint.unloadingStation] = true
        end
    end
    return set
end

function PalletDepotPriceTicker.getSellingStations(superFunc, mission)
    local stations = superFunc(mission)
    if type(stations) ~= "table" then
        return stations
    end
    local depotStations = getDepotStations()
    for i = #stations, 1, -1 do
        local station = stations[i]
        if type(station) == "table" and (depotStations[station] or PalletDepot.isDepotPlaceable(station.owningPlaceable)) then
            table.remove(stations, i)
        end
    end
    return stations
end

function PalletDepotPriceTicker.install()
    -- other mods' globals live in their own environment, reachable through the mod's name
    local env = _G["FS25_PriceTicker"]
    local utils = env ~= nil and env.PriceTickerUtils or nil
    if PalletDepotPriceTicker.installed or utils == nil or utils.getSellingStations == nil then
        return
    end
    local original = utils.getSellingStations
    utils.getSellingStations = function(mission)
        return PalletDepotPriceTicker.getSellingStations(original, mission)
    end
    PalletDepotPriceTicker.installed = true
    Logging.info("[%s] Price Ticker found: depots are no longer listed as selling stations", PalletDepot.modName)
end

-- Price Ticker may load after this mod, so also try once the map has loaded
PalletDepotPriceTicker.install()
Mission00.loadMission00Finished = Utils.appendedFunction(Mission00.loadMission00Finished, PalletDepotPriceTicker.install)
