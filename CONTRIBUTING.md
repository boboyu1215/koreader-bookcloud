# 开发与反馈

建议使用 Python 3.12。插件运行于 KOReader 的 Lua 环境。

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
python scripts/build_release.py
```

测试使用临时数据库、本地 HTTP 服务和模拟上游，不需要生产凭据。Lua 插件测试使用 Lupa 的 Lua 5.1 运行时；这些测试不能替代真机触摸、休眠及阅读验收。

服务端开发可运行 `BOOKCLOUD_DATA=./data python server/app.py`，健康检查位于 `http://127.0.0.1:8080/bookcloud/health`。管理登录 Cookie 要求 HTTPS，设备端也要求 HTTPS，请通过本地反向代理或实际域名联调，不要关闭 TLS 校验。

提交修改前运行上述测试。界面变更请附真机图片或明确标为原型的示意图。书源适配请使用可复现的测试夹具，不提交私有来源、电子书内容、口令或带签名的下载地址。

仓库结构：`plugin/` 为设备插件，`server/` 为服务端，`examples/` 为配置示例，`deploy/` 为反向代理模板，`tests/` 为自动测试。`dist/` 由构建脚本生成，不提交。
