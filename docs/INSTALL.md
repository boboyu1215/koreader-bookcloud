# 安装与部署

BookCloud 包含两个部分：运行在阅读器上的 KOReader 插件，以及自己部署的 HTTPS 服务端。普通用户目前需要具备基本的 Docker 部署能力，或由可信的人代为部署。

## 准备

- 一台已经能正常运行 KOReader 的 Kobo；本指南不包含破解设备或安装 KOReader。
- 一台能运行 Docker Engine 和 Docker Compose 的服务器。
- 一个指向服务器的域名及有效 HTTPS 证书。可选配置使用 Caddy 自动申请证书。
- 阅读器连接 Wi-Fi，且能访问该域名。

无需安装 ZenOS。先确认原有书籍在 KOReader 中能正常打开。

## 1. 部署服务端

```sh
git clone https://github.com/boboyu1215/koreader-bookcloud.git
cd koreader-bookcloud
git checkout v0.2.1-beta.1
docker compose up -d --build
docker compose ps
curl --fail http://127.0.0.1:18083/bookcloud/health
```

健康接口应返回 `ok: true` 和版本号。服务器只在本机 `127.0.0.1:18083` 暴露 HTTP 端口，设备访问需要以下 HTTPS 配置。

数据保存在 Docker 的 `bookcloud-data` 命名卷中。首次启动自动生成管理口令、设备凭据和签名密钥；重启不会重新生成。不要执行 `docker compose down -v`，它会删除命名卷。

### 方式 A：没有现成反向代理，使用附带 Caddy

先将域名的 DNS 指向服务器，并确保服务器 80、443 端口空闲、可从公网访问。云服务器还需放行安全组中的对应端口。

```sh
cp .env.example .env
```

编辑 `.env`，将 `BOOKCLOUD_HOST=books.example.com` 替换成自己的域名（不带 `https://` 和路径），然后运行：

```sh
docker compose -f compose.yaml -f compose.https.yaml up -d --build
curl --fail https://你的域名/bookcloud/health
```

Caddy 会自动申请和续期证书。以后启动、停止或更新此部署时，继续使用上述两个 `-f` 文件。若证书申请失败，检查 DNS、端口及 `docker compose -f compose.yaml -f compose.https.yaml logs caddy`。

### 方式 B：已有 Nginx HTTPS 站点

把 [deploy/nginx-location.conf](../deploy/nginx-location.conf) 中的 `location` 配置加入现有 HTTPS 站点的 `server` 块，检查配置后再加载。不要另起 Caddy 占用同一端口。

保留 `/bookcloud` 路径，不要在转发时去掉前缀。必须关闭代理缓冲，否则设备搜索可能因等待首字节而超时。导入上限为 16 MB，代理的请求体限制也要匹配。

## 2. 取得两种独立凭据

在自己的服务器终端运行：

```sh
docker compose exec bookcloud cat /data/admin-token
docker compose exec bookcloud cat /data/device-token
```

- `admin-token`：仅用于电脑上的管理页面。
- `device-token`：填入阅读器配置，只用于设备搜索和下载。

两者不能混用；不要把输出贴到 Issue 或截图里。

## 3. 安装设备插件

1. 从 [Releases](https://github.com/boboyu1215/koreader-bookcloud/releases) 下载 `bookcloud.koplugin-0.2.1-beta.1.zip`，不是 GitHub 自动生成的 Source code 包。
2. 退出 KOReader，再通过 USB 连接 Kobo。
3. 解压安装包，把整个 `bookcloud.koplugin` 文件夹复制到设备的 `.adds/koreader/plugins/`。macOS Finder 可按 `Command + Shift + .` 显示隐藏目录。
4. 安全弹出设备、拔线并重启 KOReader，打开「云书库 · 搜书」。首次使用会自动进入连接设置。
5. 在电脑管理页面的「连接阅读器」区域点击「生成配对码」。
6. 在 Kobo 上输入服务地址和 8 位数字配对码，点击「连接并保存」。配对码 5 分钟有效、只能使用一次；生成新码会使旧码失效。

旧的 `settings/bookcloud.lua` 配置仍可沿用，升级插件不要覆盖它。已配置设备可以通过「搜书 → 服务设置 / 连接检查」重新配对或检查连接。

如果希望手动配置，可在连接页面点击「手动凭据」，填写 HTTPS 服务地址、设备凭据和下载目录；保存前会检查凭据是否有效。也可继续把 [bookcloud.example.lua](../examples/bookcloud.example.lua) 复制为 `settings/bookcloud.lua`。默认下载目录为 `/mnt/onboard/book/云书库`，其他设备需要修改。

新版配对与连接检查要求服务端也更新到 0.2.1-beta.1 或以上。升级旧服务时先升级服务器，再更新设备插件。

最终结构：

```text
.adds/koreader/
├── plugins/
│   └── bookcloud.koplugin/
│       ├── _meta.lua
│       ├── main.lua
│       └── bookcloudmenu.lua
└── settings/
    └── bookcloud.lua
```

若你的 KOReader 安装在别处，使用实际安装路径。升级已有插件时先备份原文件；保留已有 `settings/bookcloud.lua`，不要用示例覆盖其中的凭据和历史。

## 4. 配置与验证书源

在电脑浏览器打开 `https://你的域名/bookcloud/`，使用管理口令登录。

初始预置 Project Gutenberg 的公开 OPDS 搜索配置。先用 `Pride and Prejudice` 做搜索测试，再点一个 EPUB 的「下载验证」。公共来源的实际可用性取决于网络与上游服务。

添加更多来源的方法见 [书源说明](SOURCES.md)。仓库不包含个人使用的书源合集、私人服务地址或电子书文件。

## 5. 在阅读器上使用

安全弹出设备并拔线，重启 KOReader，连接 Wi-Fi。

1. 打开 KOReader 菜单中的 **云书库 · 搜书**。
2. 输入书名或作者。
3. 点作品。有多个版本时先选择版本；只有一个版本时直接进入下载确认。
4. 确认下载，等待完成后点击 **开始阅读**。
5. 断网后从「已下载的书」或本地文件列表再次打开，确认文件已在设备上。

使用 ZenOS 时，可在其导航配置中绑定 `BookCloudSearch` 动作；标准 KOReader 菜单不依赖此配置。

静态章节来源需要服务端先生成 EPUB，可能等待数分钟。任意章节抓取失败时，不会把不完整 EPUB 作为成功下载返回。设备上的取消会停止等待或传输，已开始的服务端准备任务可能继续运行到完成或超时。

## 故障排查

| 现象 | 检查方式 |
| --- | --- |
| 找不到菜单入口 | 确认没有多套一层目录，`main.lua` 在 `plugins/bookcloud.koplugin/` 内；重启 KOReader |
| 提示尚未配置 | 检查 `settings/bookcloud.lua` 文件名、Lua 语法、HTTPS 地址及设备凭据 |
| 401 / 需要凭据 | 确认使用 `device-token`，且没有复制多余空格或换行 |
| 管理页面登录后又回登录页 | 必须通过 HTTPS 使用管理页面，Cookie 带 Secure 标记 |
| 下载时书源 HTTP 502 / 503 / 504 | 服务会在同一时限内最多尝试 3 次；仍失败时显示具体来源和失败阶段。有其他版本时选择「选择其他版本」；持续 502 需要来源本身恢复 |
| 配对码失效 | 配对码已使用、过期或错误尝试达到上限；在电脑管理页生成新码 |
| 搜索超时 | 检查 Wi-Fi、证书和服务连通；确认反向代理关闭响应缓冲 |
| 搜不到书 | 先在电脑端测试来源，尝试更准确的书名或作者；导入规则不代表已启用 |
| 某些来源不可用 | 上游可能变化；阅读来源检测结果，不要把推荐书目误当成命中结果 |
| 下载失败 | 检查设备空间、50 MB 上限和服务端错误；静态规则需能完整取得目录及正文 |
| 中文输入不便 | 使用 KOReader 已安装的输入法；本插件没有捆绑独立输入法 |

反馈时请给出设备型号、KOReader 与 BookCloud 版本、复现步骤、错误提示。分享 `crash.log` 前先检查并去除凭据、签名地址和私人内容。

## 升级与卸载

升级前备份设备上的插件与 `settings/bookcloud.lua`，并在服务器停止 BookCloud 后备份数据卷。更新代码、重新构建服务端并替换设备插件；设备配置继续沿用。

卸载插件：退出 KOReader 后移除 `plugins/bookcloud.koplugin`，按需保留配置和已下载的书籍。服务端可用 `docker compose stop` 停止（使用 Caddy 的部署需带两个 `-f` 参数）；停止服务不会自动删除数据。
