import tempfile,unittest
from pathlib import Path
from lupa.lua51 import LuaRuntime
PLUGIN=Path(__file__).resolve().parents[1]/'plugin/bookcloud.koplugin/main.lua'
class PluginTests(unittest.TestCase):
 def make(self,folder,code=200,preparing=False,failed=False):
  lua=LuaRuntime(unpack_returned_tuples=True)
  lua.globals().test_preparing=preparing;lua.globals().test_failed=failed;lua.globals().test_folder=folder;lua.globals().test_status=code
  lua.execute('''
local original_open=io.open; io.open=function(path,mode) last_path=path; return original_open(path,mode) end
local cls={};function cls:new(t) return t or {} end
function cls:extend(t) t.__index=t;return t end
package.preload["ui/widget/container/widgetcontainer"]=function() return cls end
for _,name in ipairs({"inputdialog","menu","infomessage","confirmbox","buttondialog"}) do
 package.preload["ui/widget/"..name]=function() return cls end
end
package.preload["ui/uimanager"]=function() return {show=function(_,w) last_widget=w end, close=function() end} end
package.preload["dispatcher"]=function() return {registerAction=function() end} end
package.preload["ui/network/manager"]=function() return {runWhenConnected=function(_,fn) fn() end} end
package.preload["ui/trapper"]=function() return {wrap=function(_,fn) fn() end,dismissableRunInSubprocess=function(_,fn) return true,fn() end} end
package.preload["datastorage"]=function() return {} end
package.preload["luasettings"]=function() return {} end
package.preload["socket"]=function() return {sleep=function() end} end
package.preload["socket.http"]=function() return {request=function(opts) opts.sink("PK-test-file");opts.sink(nil);return 1,test_status,{} end} end
package.preload["socketutil"]=function() return {set_timeout=function() end,reset_timeout=function() end} end
package.preload["ltn12"]=function() return {} end
package.preload["json"]=function() return {} end
package.preload["libs/libkoreader-lfs"]=function() return {attributes=function() return nil end} end
package.preload["util"]=function() return {makePath=function() end} end
package.preload["device"]=function() return {screen={}} end
''')
  plugin=lua.execute(PLUGIN.read_text());lua.globals().Plugin=plugin
  lua.execute('''
self=setmetatable({views={},downloaded={},ui={},settings={readSetting=function(_,k,d)
 if k=="download_dir" then return test_folder elseif k=="base_url" then return "https://example.com/bookcloud" end return d end,
 saveSetting=function() end,flush=function() end}},Plugin)
request_count=0
self.request=function(_,path)
 request_count=request_count+1
 if test_preparing and request_count==1 then return {status="preparing"} end
 if test_failed then return {status="failed",error="正文缺失"} end
 return {status="ready",url="/bookcloud/files/abc?sig=test"}
end
edition={edition_id="abc",title="测试/书",format="epub",language="中文",source_name="test"}
self:download(edition)
''')
  return lua
 def test_success_http_return_positions_and_atomic_file(self):
  with tempfile.TemporaryDirectory() as d:
   lua=self.make(d)
   self.assertIsNotNone(lua.globals().self.downloaded['abc'])
   files=list(Path(d).iterdir());self.assertEqual(len(files),1);self.assertEqual(files[0].suffix,'.epub')
   self.assertEqual(lua.globals().last_widget.ok_text,'开始阅读')
 def test_http_error_not_marked_downloaded(self):
  with tempfile.TemporaryDirectory() as d:
   lua=self.make(d,503)
   self.assertIsNone(lua.globals().self.downloaded['abc']);self.assertEqual(list(Path(d).iterdir()),[])
   self.assertEqual(lua.globals().last_widget.ok_text,'重试')
 def test_preparation_polled_before_download(self):
  with tempfile.TemporaryDirectory() as d:
   lua=self.make(d,preparing=True)
   self.assertEqual(lua.globals().request_count,2)
   self.assertIsNotNone(lua.globals().self.downloaded['abc'])
 def test_preparation_failure_does_not_download(self):
  with tempfile.TemporaryDirectory() as d:
   lua=self.make(d,preparing=True,failed=True)
   self.assertEqual(list(Path(d).iterdir()),[])
   self.assertIn('正文缺失',lua.globals().last_widget.text)
   self.assertIn('测试/书',lua.globals().last_widget.text)
if __name__=='__main__':unittest.main()
