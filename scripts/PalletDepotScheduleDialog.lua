-- Pallet Depot: schedule editor for one production line (opened from the productions window, Lines tab, X).
--
-- Twelve months, each switched on or off (Enter), all at once (X), the whole schedule paused or active (C).
-- Space saves through PalletDepotSchedules (the server stores and applies it), Esc cancels.

PalletDepotScheduleDialog = {}
local PalletDepotScheduleDialog_mt = Class(PalletDepotScheduleDialog, MessageDialog)

PalletDepotScheduleDialog.GUI_NAME = "PalletDepotScheduleDialog"

local COLOR = {
    text = {0.92, 0.94, 0.92, 1}, dim = {0.6, 0.64, 0.61, 1}, green = {0.35, 0.82, 0.4, 1},
    switchOn = {0.18, 0.55, 0.24, 1}, switchOff = {0.4, 0.43, 0.41, 1}
}

local KEYS = {
    {action = "MENU_ACCEPT", handler = "onClickToggleMonth"},
    {action = "MENU_EXTRA_1", handler = "onClickAllMonths"},
    {action = "MENU_EXTRA_2", handler = "onClickScheduleState"},
    {action = "MENU_ACTIVATE", handler = "onClickSave"},
}

local function text(key)
    return g_i18n:getText(key)
end

function PalletDepotScheduleDialog.new(target, custom_mt)
    local self = MessageDialog.new(target, custom_mt or PalletDepotScheduleDialog_mt)
    self.months = {}
    self.enabled = true
    self.selected = 1
    return self
end

-- productionPoint, production: the line to edit; onSaved(): called after saving
function PalletDepotScheduleDialog.show(productionPoint, production, facilityName, onSaved)
    local dialog = PalletDepotScheduleDialog.new()
    dialog.productionPoint = productionPoint
    dialog.production = production
    dialog.facilityName = facilityName
    dialog.onSaved = onSaved
    local schedule = PalletDepotSchedules.get(productionPoint, production.id)
    if schedule ~= nil then
        dialog.enabled = schedule.enabled
        for period in pairs(schedule.months) do
            dialog.months[period] = true
        end
    end
    g_gui:loadGui(PalletDepot.modDirectory .. "gui/PalletDepotSchedule.xml", PalletDepotScheduleDialog.GUI_NAME, dialog)
    g_gui:showDialog(PalletDepotScheduleDialog.GUI_NAME)
end

function PalletDepotScheduleDialog:onGuiSetupFinished()
    PalletDepotScheduleDialog:superClass().onGuiSetupFinished(self)
    self.monthList:setDataSource(self)
    self.monthList:setDelegate(self)
end

function PalletDepotScheduleDialog:onOpen()
    PalletDepotScheduleDialog:superClass().onOpen(self)
    self.titleText:setText(self.production.name or "?")
    self.subtitleText:setText(self.facilityName or "")
    self.monthList:reloadData()
    self.monthList:setSelectedItem(1, g_currentMission.environment.currentPeriod or 1, true)
    self:updateTexts()
end

function PalletDepotScheduleDialog:onClickOk()
    return false
end

function PalletDepotScheduleDialog:onClickBack()
    self:close()
end

function PalletDepotScheduleDialog:allMonthsOn()
    for period = 1, PalletDepotSchedules.NUM_MONTHS do
        if not self.months[period] then
            return false
        end
    end
    return true
end

function PalletDepotScheduleDialog:updateTexts()
    local active = self.enabled and next(self.months) ~= nil
    self.stateText:setText(text(active and "pdo_scheduleActive" or (self.enabled and "pdo_scheduleNoMonths" or "pdo_schedulePaused")))
    self.stateText:setTextColor(unpack(active and COLOR.green or COLOR.dim))
    self.allMonthsButton:setText(text(self:allMonthsOn() and "pdo_btnAllMonthsOff" or "pdo_btnAllMonthsOn"))
    self.stateButton:setText(text(self.enabled and "pdo_btnScheduleOff" or "pdo_btnScheduleOn"))
    self.toggleMonthButton:setInputAction(InputAction.MENU_ACCEPT)
    self.allMonthsButton:setInputAction(InputAction.MENU_EXTRA_1)
    self.stateButton:setInputAction(InputAction.MENU_EXTRA_2)
    self.saveButton:setInputAction(InputAction.MENU_ACTIVATE)
    local box = self.buttonBox
    if box ~= nil and box.updateLayoutCells ~= nil and box.applyCellPositions ~= nil then
        box:updateLayoutCells()
        box:applyCellPositions(0, 0)
    end
end

-- --- month list ----------------------------------------------------------------------------------------

function PalletDepotScheduleDialog:getNumberOfItemsInSection(list, section)
    return PalletDepotSchedules.NUM_MONTHS
end

function PalletDepotScheduleDialog:populateCellForItemInSection(list, section, index, row)
    local on = self.months[index] == true
    row:getAttribute("month"):setText(PalletDepotSchedules.getMonthName(index, false))
    local now = row:getAttribute("now")
    now:setText(index == g_currentMission.environment.currentPeriod and text("pdo_scheduleNow") or "")
    now:setTextColor(unpack(COLOR.green))
    local state = row:getAttribute("state")
    state:setText(text(on and "pdo_scheduleRuns" or "pdo_scheduleOff"))
    state:setTextColor(unpack(on and COLOR.green or COLOR.dim))
    -- a small switch: the knob sits right and turns green when the month is on
    local bg, knob = row:getAttribute("switchBg"), row:getAttribute("switchKnob")
    knob:setPosition(on and (bg.position[1] + bg.size[1] - knob.size[1]) or bg.position[1], nil)
    knob:setImageColor(nil, unpack(on and COLOR.switchOn or COLOR.switchOff))
end

function PalletDepotScheduleDialog:onListSelectionChanged(list, section, index)
    self.selected = index
end

-- --- actions -------------------------------------------------------------------------------------------

function PalletDepotScheduleDialog:refresh()
    self.monthList:reloadData()
    self.monthList:setSelectedItem(1, self.selected, true)
    self:updateTexts()
end

function PalletDepotScheduleDialog:onClickToggleMonth()
    self.months[self.selected] = not self.months[self.selected] or nil
    self:refresh()
end

function PalletDepotScheduleDialog:onClickAllMonths()
    local allOn = self:allMonthsOn()
    for period = 1, PalletDepotSchedules.NUM_MONTHS do
        self.months[period] = (not allOn) or nil
    end
    self:refresh()
end

function PalletDepotScheduleDialog:onClickScheduleState()
    self.enabled = not self.enabled
    self:updateTexts()
end

function PalletDepotScheduleDialog:onClickSave()
    PalletDepotSchedules.request(self.productionPoint, self.production.id, self.enabled, self.months)
    local onSaved = self.onSaved
    self:close()
    if onSaved ~= nil then
        onSaved()
    end
end

function PalletDepotScheduleDialog:inputEvent(action, value, eventUsed)
    if not eventUsed and value ~= 0 then
        for _, key in ipairs(KEYS) do
            if action == InputAction[key.action] then
                self[key.handler](self)
                return true
            end
        end
    end
    return PalletDepotScheduleDialog:superClass().inputEvent(self, action, value, eventUsed)
end
