让 Kobo 不止能读书，还能直接找书。

首次公开测试版：在 KOReader 上搜索书名或作者、选择版本、下载并开始阅读；附带可自建的书源管理服务。

## 下载哪个文件

- `bookcloud.koplugin-0.2.0-beta.1.zip`：阅读器插件。解压后把 `bookcloud.koplugin` 放入 KOReader 的 `plugins` 目录。
- `SHA256SUMS`：安装包校验值。
- GitHub 自动生成的 Source code：完整项目源码和服务端部署配置，不是直接安装的插件包。

需要已安装 KOReader，以及可供设备访问的 HTTPS 服务端。请先阅读仓库中的 `docs/INSTALL.md`。ZenOS 可选。

支持 OPDS、Gutendex、自定义目录和部分静态 Legado 规则，不提供公共书库，不保证任意书源可用。其他设备兼容性、休眠和断网等场景仍需要更多真机反馈。结果列表改版尚未包含在此版本。
