import tempfile
import unittest
from pathlib import Path
import test_plugin


class DeviceSettingsTests(unittest.TestCase):
    def make(self, directory, success=True):
        lua = test_plugin.PluginTests().make(directory)
        lua.globals().pair_success = success
        lua.execute('''
package.preload["ui/widget/multiinputdialog"]=function()
 local cls={};function cls:new(t)
  function t:getFields() return {"https://books.example.org/", "12345678"} end
  function t:onShowKeyboard() end
  return t
 end
 return cls
end
saved={}
self.settings.saveSetting=function(_,key,value) saved[key]=value end
self.settings.flush=function() flushed=true end
self.onBookCloudSearch=function() searched=true end
self.request=function(_,path,body,config)
 used_path=path; used_code=body.code; used_base=config.base_url
 if pair_success then return {ok=true,device_token="paired-device-token"} end
 return {error="配对码已失效"}
end
self:configure()
config_dialog=last_widget
config_dialog.buttons[1][3].callback()
''')
        return lua

    def test_pairing_saves_credentials_only_after_success(self):
        with tempfile.TemporaryDirectory() as directory:
            lua = self.make(directory)
            self.assertEqual(lua.globals().saved['base_url'], 'https://books.example.org/bookcloud')
            self.assertEqual(lua.globals().saved['device_token'], 'paired-device-token')
            self.assertEqual(lua.globals().used_code, '12345678')
            self.assertEqual(lua.globals().used_path, '/api/v1/pair')
            self.assertTrue(lua.globals().flushed)

    def test_failed_pair_does_not_overwrite_existing_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            lua = self.make(directory, False)
            self.assertIsNone(lua.globals().saved['device_token'])
            self.assertIsNone(lua.globals().saved['base_url'])
            self.assertIsNone(lua.globals().flushed)
            self.assertEqual(lua.globals().last_widget.text, '配对码已失效')

    def test_service_address_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            lua = test_plugin.PluginTests().make(directory)
            for address in ('http://example.org', 'https://user:pass@example.org', 'https://example.org/path', 'https://example.org/?token=secret'):
                result = lua.globals().self.normalizeBase(lua.globals().self, address)
                self.assertIsNone(result[0])
            self.assertEqual(lua.globals().self.normalizeBase(lua.globals().self, ' https://example.org/bookcloud/ '), 'https://example.org/bookcloud')

    def test_download_failure_offers_other_versions(self):
        with tempfile.TemporaryDirectory() as directory:
            lua = test_plugin.PluginTests().make(directory, failed=True)
            lua.execute('''
work={editions={edition,edition}}
self.versions=function(_,w) chosen_work=w end
self:download(edition,work)
last_widget.cancel_callback()
''')
            self.assertEqual(lua.globals().last_widget.cancel_text, '选择其他版本')
            self.assertIsNotNone(lua.globals().chosen_work)
