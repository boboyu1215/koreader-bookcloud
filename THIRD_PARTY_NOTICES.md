# 第三方与来源说明

BookCloud 自有代码按 AGPL-3.0-or-later 发布。根目录 LICENSE 为 GNU AGPL v3 许可证正文；本项目选择允许使用该版本或后续版本。

本仓库不捆绑 KOReader、ZenOS、输入法插件、字体、电子书文件或第三方书源合集，也不包含之前设备部署时的第三方组件副本。

运行环境与依赖：

- KOReader：设备端运行环境，插件调用其 Lua API。https://github.com/koreader/koreader
- Python：服务端运行时。https://www.python.org/
- Beautiful Soup 4：HTML 解析，MIT。https://www.crummy.com/software/BeautifulSoup/
- Soup Sieve：CSS 选择器，MIT。https://github.com/facelessuser/soupsieve
- regex：正则表达式库，许可证以对应安装版本的包内 LICENSE 为准。https://pypi.org/project/regex/
- typing-extensions：Python 类型辅助，PSF-2.0。https://github.com/python/typing_extensions
- Lupa：仅开发测试使用，MIT。https://github.com/scoder/lupa
- Caddy：可选 HTTPS 反向代理，通过官方容器使用，Apache-2.0。https://github.com/caddyserver/caddy

`server/legado.py` 是本项目的有限静态规则解释器；不捆绑或运行 Legado 应用，也不保证完整兼容其规则。用户导入的规则和通过来源获取的内容遵循各自的权利与使用条件。
