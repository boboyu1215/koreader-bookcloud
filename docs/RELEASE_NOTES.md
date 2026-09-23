让 Kobo 不止能读书，还能直接找书。

## 本次更新

- 大号书名 + 小号作者与版本信息；长书名最多两行，长按查看完整标题。
- 系列数字卷号按 1、2、10 排序，支持“第二卷”等明确中文卷号。
- 电脑生成 8 位配对码，设备端输入地址与配对码即可配置；仍支持手动凭据和下载目录。
- 书源 HTTP 502/503/504 等临时错误有限重试，所有文件先在服务端准备好，再传给 Kobo。
- 失败时提示具体书源与阶段，多版本作品可以选择其他版本。

## 安装与升级

下载 `bookcloud.koplugin-0.2.1-beta.1.zip`，解压后把整个 `bookcloud.koplugin` 文件夹放入 KOReader 的 `plugins` 目录。保留现有 `settings/bookcloud.lua`。`SHA256SUMS` 提供校验值。

先升级服务端，再升级阅读器插件并重启 KOReader。安装文档：[docs/INSTALL.md](https://github.com/boboyu1215/koreader-bookcloud/blob/main/docs/INSTALL.md)。

这是测试版。自动测试覆盖网关重试、配对权限、过期与单次使用、分页、排序和下载失败处理；不替代真机触控与排版验收。持续不可用的上游仍可能失败，可改选其他来源。Z-Library 尚未集成。
