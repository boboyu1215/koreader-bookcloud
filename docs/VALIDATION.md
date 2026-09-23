# 首次公开版验证记录

版本：0.2.0-beta.1。验证日期：2026-09-24。

- 32 项现有自动测试全部通过，覆盖认证与管理权限隔离、来源地址约束、搜索聚合、部分结果、静态规则、EPUB 合成、准备失败、设备轮询及下载成功/失败处理。
- 本地验证使用 Python 3.9.6 和 Lupa 2.8（Lua 5.1）；服务镜像与 GitHub Actions 目标运行时为 Python 3.12。
- 两种 Docker Compose 配置均通过 `docker compose config --quiet`。
- 安装包由明确文件清单构建，只含插件 Lua 文件和许可证说明；ZIP 完整性与版本一致性检查通过。
- Markdown 本地链接检查通过。
- 公开文件未包含个人部署目录、服务域名、设备备份、配置凭据或第三方书源合集。

本机 Docker 引擎未运行；[首次 GitHub Actions](https://github.com/boboyu1215/koreader-bookcloud/actions/runs/35886425744) 已在 Python 3.12 上通过全部测试和容器构建。持续集成还加入了全新数据卷启动、健康检查、非 root 用户及凭据生成检查，可在仓库 Actions 查看各次运行结果。公开 HTTPS、DNS 与真实设备网络仍需按部署环境验收。照片证明现有设备的搜索界面能够显示，不替代新用户完整安装、真实下载、休眠、断网及其他设备验收。
