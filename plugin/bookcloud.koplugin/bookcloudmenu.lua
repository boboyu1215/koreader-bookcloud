-- Keep KOReader's navigation, focus and touch behavior; only replace row content.
local Menu = require("ui/widget/menu")
local Font = require("ui/font")
local TextBoxWidget = require("ui/widget/textboxwidget")
local VerticalGroup = require("ui/widget/verticalgroup")
local VerticalSpan = require("ui/widget/verticalspan")
local LeftContainer = require("ui/widget/container/leftcontainer")
local Geom = require("ui/geometry")
local Size = require("ui/size")
local Screen = require("device").screen
local UIManager = require("ui/uimanager")
local InfoMessage = require("ui/widget/infomessage")

local BookCloudMenu = Menu:extend{}

local function textBox(text, width, size, bold, max_lines)
    local face = Font:getFace("smallinfofont", size)
    local sample = TextBoxWidget:new{text="书", face=face, width=width, bold=bold}
    local line_height = sample:getSize().h
    sample:free()
    local widget = TextBoxWidget:new{
        text=text, face=face, width=width, bold=bold, alignment="left",
        height=max_lines * line_height, height_adjust=true,
        height_overflow_show_ellipsis=true,
    }
    return widget
end

function BookCloudMenu:row(item, width)
    local title = textBox(item.text, width, self.font_size, true, 2)
    local group = VerticalGroup:new{align="left", title}
    if item.bookcloud_detail then
        table.insert(group, VerticalSpan:new{width=Screen:scaleBySize(4)})
        table.insert(group, textBox(item.bookcloud_detail, width, self.font_size-6, false, 1))
    end
    return group
end

function BookCloudMenu:setupItemHeights()
    local width = math.max(1, self.inner_dimen.w-2*Size.padding.fullscreen)
    self.page_items = {{}}
    local used = 0
    for i, item in ipairs(self.item_table) do
        local row = self:row(item, width)
        item.height = row:getSize().h + 2*Size.span.vertical_default + self.linesize
        row:free()
        local page = self.page_items[#self.page_items]
        if #page > 0 and used + item.height > self.available_height then
            page = {}; self.page_items[#self.page_items+1] = page; used = 0
        end
        page[#page+1] = i
        used = used + item.height
    end
end

function BookCloudMenu:updateItems(...)
    Menu.updateItems(self, ...)
    for _, widget in ipairs(self.item_group) do
        local underline = widget._underline_container
        underline[1]:free()
        underline[1] = LeftContainer:new{
            dimen=Geom:new{w=widget.content_width, h=widget.dimen.h-self.linesize},
            self:row(widget.entry, widget.content_width),
        }
        widget[1][1]:resetLayout()
    end
end

function BookCloudMenu:onMenuHold(item)
    UIManager:show(InfoMessage:new{
        text=item.text .. (item.bookcloud_detail and "\n"..item.bookcloud_detail or ""),
    })
    return true
end

return BookCloudMenu
