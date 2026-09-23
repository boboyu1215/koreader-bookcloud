local WidgetContainer = require("ui/widget/container/widgetcontainer")
local UIManager = require("ui/uimanager")
local InputDialog = require("ui/widget/inputdialog")
local Menu = require("ui/widget/menu")
local InfoMessage = require("ui/widget/infomessage")
local ConfirmBox = require("ui/widget/confirmbox")
local Dispatcher = require("dispatcher")
local NetworkMgr = require("ui/network/manager")
local Trapper = require("ui/trapper")
local DataStorage = require("datastorage")
local LuaSettings = require("luasettings")
local http = require("socket.http")
local socketutil = require("socketutil")
local ltn12 = require("ltn12")
local json = require("json")
local lfs = require("libs/libkoreader-lfs")
local util = require("util")
local Screen = require("device").screen

local BookCloud = WidgetContainer:extend { name = "bookcloud", is_doc_only = false }

local function encode(s)
    return (s:gsub("([^A-Za-z0-9%-_%.~])", function(c) return string.format("%%%02X", string.byte(c)) end))
end
local function language(s)
    return ({ en="英文", zh="中文", ["zh-Hans"]="简体中文", ["zh-Hant"]="繁体中文", fr="法文", de="德文", ja="日文" })[s] or s
end
local function cleanTitle(s)
    s = s:gsub("[/\\:%*%?%\"<>|%z\1-\31\127]", "_")
    local chars = {}; for c in s:gmatch("[%z\1-\127\194-\244][\128-\191]*") do
        chars[#chars+1] = c; if #chars >= 45 then break end
    end
    return #chars > 0 and table.concat(chars) or "书籍"
end

function BookCloud:init()
    self.settings = LuaSettings:open(DataStorage:getSettingsDir() .. "/bookcloud.lua")
    self.views = {}
    self.history = self.settings:readSetting("history", {})
    self.downloaded = self.settings:readSetting("downloaded", {})
    self.ui.menu:registerToMainMenu(self)
    self:onDispatcherRegisterActions()
end
function BookCloud:onDispatcherRegisterActions()
    Dispatcher:registerAction("bookcloud_search", { category="none", event="BookCloudSearch", title="云书库搜书", general=true })
end
function BookCloud:addToMainMenu(items)
    items.bookcloud = { text="云书库 · 搜书", sorting_hint="search", callback=function() self:onBookCloudSearch() end }
end
function BookCloud:message(s) UIManager:show(InfoMessage:new{text=s}) end
function BookCloud:request(path, body)
    local base = self.settings:readSetting("base_url", "")
    local key = self.settings:readSetting("device_token", "")
    if not base:match("^https://") or key == "" then return { error="云书库尚未配置，请在电脑连接 Kobo 后配置服务地址和设备凭据。" } end
    local sink = {}; local content = body and json.encode(body) or nil
    socketutil:set_timeout(15, 100)
    local headers = { ["Authorization"]="Bearer "..key, ["Accept-Encoding"]="identity", ["Accept"]="application/json" }
    if content then headers["Content-Type"]="application/json"; headers["Content-Length"]=tostring(#content) end
    local bytes = 0
    local ok, _, code = pcall(http.request, {
        url=base..path, method=body and "POST" or "GET", headers=headers,
        source=content and ltn12.source.string(content) or nil,
        sink=function(chunk)
            if chunk then bytes=bytes+#chunk; if bytes>4*1024*1024 then return nil,"response too large" end; sink[#sink+1]=chunk end
            return 1
        end,
    })
    socketutil:reset_timeout()
    if not ok then return {error="连接失败，请检查 Wi-Fi 后重试。"} end
    local decoded_ok, result = pcall(json.decode, table.concat(sink))
    if not decoded_ok or type(result)~="table" then return {error="服务器未返回有效结果，请稍后重试。"} end
    if tonumber(code)~=200 then return {error=result.error or "服务器暂不可用"} end
    return result
end
function BookCloud:menu(title, items, perpage)
    for _, item in ipairs(items) do item.text=item.text:gsub("\n", " · ") end
    local menu
    menu = Menu:new { title=title, item_table=items, width=Screen:getWidth(), height=Screen:getHeight(),
        is_popout=false, is_borderless=true, items_per_page=14, items_font_size=20, items_max_lines=1, single_line=true,
        setupItemHeights=function(m)
            Menu.setupItemHeights(m)
            local pages={{}};local used=0
            for index,item in ipairs(m.item_table) do
                if item.bookcloud_gap then item.height=Screen:scaleBySize(20) end
                if used+item.height>m.available_height and #pages[#pages]>0 then pages[#pages+1]={};used=0 end
                table.insert(pages[#pages],index);used=used+item.height
            end
            m.page_items=pages
        end,
        close_callback=function() UIManager:close(menu); self.views[menu]=nil end }
    self.views[menu]=true
    UIManager:show(menu)
    return menu
end
function BookCloud:onBookCloudSearch()
    local items={{text="输入书名 / 作者",callback=function() self:input() end}}
    if #self.history>0 then items[#items+1]={text=" ",bookcloud_gap=true,callback=function() end} end
    for _,query in ipairs(self.history) do
        local q=query
        items[#items+1]={text="最近搜索："..q, callback=function() self:search(q) end}
    end
    items[#items+1]={text="已下载的书",callback=function() self:showDownloaded() end}
    if #self.history>0 then items[#items+1]={text="清除搜索历史",callback=function()
        self.history={};self.settings:saveSetting("history",{});self.settings:flush();self:message("搜索历史已清除。")
    end} end
    self:menu("搜书",items)
    return true
end
function BookCloud:input()
    local d
    d=InputDialog:new{title="搜书",fullscreen=false,condensed=true,input=self.last_query or "",input_hint="书名 / 作者",description="输入拼音后点选中文，或按空格确认。",buttons={{
        {text="取消",callback=function() UIManager:close(d) end},
        {text="搜索",is_enter_default=true,callback=function()
            d._input_widget:goToEndOfLine() -- Let the installed IME commit pending composition.
            local q=d:getInputText():gsub("^%s+",""):gsub("%s+$","")
            if q=="" then return end
            self.last_query=q;UIManager:close(d);self:search(q)
        end},
    }}}
    UIManager:show(d);d:onShowKeyboard()
end
function BookCloud:search(q)
    NetworkMgr:runWhenConnected(function() Trapper:wrap(function()
        local completed,result=Trapper:dismissableRunInSubprocess(function() return self:request("/api/v1/search?q="..encode(q)) end,"正在搜索…\n点按可取消")
        if not completed then return end
        if not result or result.error then return self:message(result and result.error or "查询失败，请重试。") end
        local h={q};for _,old in ipairs(self.history) do if old~=q and #h<8 then h[#h+1]=old end end
        self.history=h;self.settings:saveSetting("history",h);self.settings:flush()
        local items={}
        if result.partial then items[#items+1]={text="部分书源暂不可用，点此重试",callback=function() self:search(q) end} end
        for _,work in ipairs(result.works or {}) do
            local w=work;local count=#(w.editions or {})
            items[#items+1]={text=w.title.."\n"..table.concat(w.authors or {}," / ").." · "..count.." 个版本",callback=function()
                if count==1 then self:confirmDownload(w.editions[1]) else self:versions(w) end
            end}
        end
        if #(result.works or {})==0 then
            local text = result.partial and "书源暂时未能完整返回结果，请稍后重试。" or "当前书源没有匹配《"..q.."》的结果。\n可换用书名或作者，也可在电脑端增加书源。"
            UIManager:show(ConfirmBox:new{text=text,ok_text="修改关键词",cancel_text="返回",ok_callback=function() self:input() end})
            return
        end
        self:menu("搜索："..q,items)
    end) end)
end
local function versionName(e)
    local label=e.version_label or ""
    if label:find("EPUB3",1,true) then return "EPUB 3 · 新格式" end
    if label:find("no images",1,true) then return "EPUB · 无插图版" end
    if label:find("older E%-readers") then return "EPUB · 兼容版" end
    return e.format:upper()..(label~="" and " · "..label or "")
end
function BookCloud:versions(work)
    local items={}
    for _,edition in ipairs(work.editions) do
        local e=edition
        local detail=language(e.language)
        if type(e.size_bytes)=="number" then detail=detail..string.format(" · %.1f MB",e.size_bytes/1024/1024) end
        if e.publisher and e.publisher~="" then detail=detail.." · "..e.publisher end
        if e.translator and e.translator~="" then detail=detail.." · 译者："..e.translator end
        items[#items+1]={text=versionName(e).."\n"..detail,callback=function() self:confirmDownload(e) end}
    end
    self:menu(work.title.." · 选择下载版本",items,10)
end
function BookCloud:openBook(path)
    for view in pairs(self.views) do UIManager:close(view) end
    self.views={}
    if self.ui.document then self.ui:switchDocument(path) else self.ui:openFile(path) end
end
function BookCloud:confirmDownload(e)
    local found=self.downloaded[e.edition_id]
    if found and lfs.attributes(found.path,"mode")=="file" then
        UIManager:show(ConfirmBox:new{text="已下载《"..e.title.."》",ok_text="开始阅读",ok_callback=function() self:openBook(found.path) end})
        return
    end
    UIManager:show(ConfirmBox:new{text=e.title.."\n"..language(e.language).." · "..e.format:upper().."\n"..versionName(e).."\n来源："..e.source_name,
        ok_text="下载",ok_callback=function() self:download(e) end})
end
function BookCloud:download(e)
    NetworkMgr:runWhenConnected(function() Trapper:wrap(function()
        local directory=self.settings:readSetting("download_dir","/mnt/onboard/book/云书库")
        util.makePath(directory)
        local path=directory.."/"..cleanTitle(e.title).."-"..e.edition_id.."."..e.format
        local partial=path..".part"
        local completed,result=Trapper:dismissableRunInSubprocess(function()
            local link=self:request("/api/v1/downloads",{edition_id=e.edition_id})
            local deadline=os.time()+660
            while link.status=="preparing" and not link.error do
                if os.time()>deadline then return {error="书籍准备超时，请稍后重试。"} end
                require("socket").sleep(2)
                link=self:request("/api/v1/downloads/"..e.edition_id)
            end
            if link.error then return link end
            if type(link.url)~="string" or not link.url:match("^/bookcloud/files/") then return {error="下载地址无效"} end
            local base=self.settings:readSetting("base_url","")
            local origin=base:match("^(https://[^/]+)")
            local f=io.open(partial,"wb");if not f then return {error="无法写入下载目录，请检查存储空间。"} end
            local count=0;local first=""
            socketutil:set_timeout(20,180)
            local ok,code=http.request{url=origin..link.url,headers={["Accept-Encoding"]="identity"},
                sink=function(chunk)
                    if chunk then
                        count=count+#chunk
                        if count>50*1024*1024 then return nil,"file too large" end
                        if #first<100 then first=first..chunk:sub(1,100-#first) end
                        local written=f:write(chunk);if not written then return nil,"write failed" end
                    end
                    return 1
                end}
            f:close();socketutil:reset_timeout()
            if not ok or tonumber(code)~=200 or count==0 then return {error="下载未完成，请检查网络后重试。"} end
            if e.format=="epub" and first:sub(1,2)~="PK" then return {error="文件格式校验失败。"} end
            local renamed=os.rename(partial,path);if not renamed then return {error="文件保存失败，请检查存储空间。"} end
            return {path=path}
        end,"正在准备并下载《"..e.title.."》…\n点按可取消")
        if not completed or not result or result.error then
            os.remove(partial)
            if completed then UIManager:show(ConfirmBox:new{text=result and result.error or "下载失败",ok_text="重试",ok_callback=function() self:download(e) end}) end
            return
        end
        self.downloaded[e.edition_id]={title=e.title,path=path}
        self.settings:saveSetting("downloaded",self.downloaded);self.settings:flush()
        if self.ui.file_chooser then self.ui.file_chooser:refreshPath() end
        UIManager:show(ConfirmBox:new{text="下载完成，已加入本地书库。",ok_text="开始阅读",cancel_text="继续搜书",ok_callback=function() self:openBook(path) end})
    end) end)
end
function BookCloud:showDownloaded()
    local items={}
    for _,entry in pairs(self.downloaded) do
        local e=entry
        if lfs.attributes(e.path,"mode")=="file" then items[#items+1]={text=e.title,callback=function() self:openBook(e.path) end} end
    end
    table.sort(items,function(a,b) return a.text<b.text end)
    if #items==0 then return self:message("还没有通过云书库下载的书籍。") end
    self:menu("已下载",items)
end
return BookCloud
