import unittest
from pathlib import Path
from lupa.lua51 import LuaRuntime

MODULE = Path(__file__).resolve().parents[1]/'plugin/bookcloud.koplugin/bookcloudmenu.lua'


class BookMenuTests(unittest.TestCase):
    def make(self):
        lua = LuaRuntime(unpack_returned_tuples=True)
        lua.execute('''
local cls={}
function cls:new(t) return setmetatable(t or {}, {__index=self}) end
function cls:extend(t) return setmetatable(t or {}, {__index=self}) end
function cls:free() end
local box=cls:extend{}
function box:getSize() return {w=self.width,h=self.height or self.face.size} end
local group=cls:extend{}
function group:getSize()
 local h=0;for _,item in ipairs(self) do h=h+item:getSize().h end
 return {w=400,h=h}
end
local span=cls:extend{}
function span:getSize() return {w=0,h=self.width} end
package.preload["ui/widget/menu"]=function() return cls end
package.preload["ui/font"]=function() return {getFace=function(_,name,size) return {size=size} end} end
package.preload["ui/widget/textboxwidget"]=function() return box end
package.preload["ui/widget/verticalgroup"]=function() return group end
package.preload["ui/widget/verticalspan"]=function() return span end
package.preload["ui/widget/container/leftcontainer"]=function() return cls end
package.preload["ui/geometry"]=function() return cls end
package.preload["ui/size"]=function() return {padding={fullscreen=10},span={vertical_default=8}} end
package.preload["device"]=function() return {screen={scaleBySize=function(_,v) return v end}} end
package.preload["ui/uimanager"]=function() return {show=function(_,w) shown=w end} end
package.preload["ui/widget/infomessage"]=function() return cls end
''')
        lua.globals().Menu = lua.execute(MODULE.read_text())
        return lua

    def test_rows_fit_pages_and_preserve_every_result(self):
        lua = self.make()
        lua.execute('''
m=Menu:new{font_size=22,inner_dimen={w=400},available_height=180,linesize=1,item_table={}}
for i=1,11 do m.item_table[i]={text="长书名"..i,bookcloud_detail="作者 · 2 个版本"} end
m:setupItemHeights()
count=0
for _,page in ipairs(m.page_items) do
 local height=0
 for _,i in ipairs(page) do count=count+1;assert(i==count);height=height+m.item_table[i].height end
 assert(height<=m.available_height)
end
''')
        self.assertEqual(lua.globals().count, 11)

    def test_title_and_detail_have_separate_size_and_full_title_on_hold(self):
        lua = self.make()
        lua.execute('''
m=Menu:new{font_size=22}
item={text=string.rep("完整长书名",30),bookcloud_detail="作者 · 3 个版本"}
row=m:row(item,400)
assert(row[1].bold and row[1].face.size>row[3].face.size)
assert(row[1].height_overflow_show_ellipsis)
m:onMenuHold(item)
assert(shown.text==item.text.."\\n"..item.bookcloud_detail)
''')
