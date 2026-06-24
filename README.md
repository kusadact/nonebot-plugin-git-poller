<div align="center">
  <a href="https://v2.nonebot.dev/store">
    <img src="https://raw.githubusercontent.com/fllesser/nonebot-plugin-template/refs/heads/resource/.docs/NoneBotPlugin.svg" width="310" alt="logo">
  </a>

## ✨ nonebot-plugin-git-poller ✨

[![LICENSE](https://img.shields.io/github/license/kusadact/nonebot-plugin-git-poller.svg)](./LICENSE)
[![pypi](https://img.shields.io/pypi/v/nonebot-plugin-git-poller.svg)](https://pypi.org/project/nonebot-plugin-git-poller/)
[![python](https://img.shields.io/badge/python-3.10|3.11|3.12|3.13-blue.svg)](https://www.python.org)
[![uv](https://img.shields.io/badge/package%20manager-uv-black?style=flat-square&logo=uv)](https://github.com/astral-sh/uv)
[![codecov](https://codecov.io/gh/kusadact/nonebot-plugin-git-poller/graph/badge.svg)](https://codecov.io/gh/kusadact/nonebot-plugin-git-poller)

</div>

按群订阅 Git 仓库更新的 NoneBot2 插件，支持多仓库、多分支定时拉取，自动推送 commit 更新摘要并上传源码压缩包。

支持 GitHub、GitLab、Gitee 以及自建 Git 服务等主流 Git 托管平台，兼容标准 HTTP/HTTPS Git 远端。

## 💿 安装

<details open>
<summary>使用 nb-cli 安装</summary>

```bash
nb plugin install nonebot-plugin-git-poller
```

</details>

<details>
<summary>使用包管理器安装</summary>

在 NoneBot 项目目录中，根据你使用的包管理器，输入相应的安装命令：

<details open>
<summary>uv</summary>

```bash
uv add nonebot-plugin-git-poller
```

</details>

<details>
<summary>pdm</summary>

```bash
pdm add nonebot-plugin-git-poller
```

</details>

<details>
<summary>poetry</summary>

```bash
poetry add nonebot-plugin-git-poller
```

</details>

打开 NoneBot 项目根目录下的 `pyproject.toml` 文件，在 `[tool.nonebot]` 部分追加写入：

```toml
[tool.nonebot]
plugins = ["nonebot_plugin_git_poller"]
```

</details>

## ⚙️ 配置

| 配置项 | 必填 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `git_poller_default_schedule` | 否 | `每天04:00` | 新关注仓库的默认定时规则；留空关闭默认定时注册。 |
| `git_poller_timezone` | 否 | `+8` | 定时任务 UTC 偏移量，含半点时区，例如 `+8.5` 或 `-3.5`。 |
| `git_poller_proxy` | 否 | 空 | HTTP/HTTPS Git 拉取代理。 |
| `git_poller_timeout` | 否 | `60.0` | HTTP/HTTPS Git 拉取超时，单位秒。 |
| `git_poller_upload_api_timeout` | 否 | `3600.0` | 调用 OneBot 上传压缩包 API 的超时，单位秒。 |
| `git_poller_archive_password` | 否 | 空 | 全局压缩包密码；为空时不自动加密。 |
| `git_poller_file_base_url` | 条件 | 空 | 上传文件使用的 NoneBot HTTP 服务根地址；Bot 和 协议端 不在同一个文件系统时必须配置，例如 http://nonebot:8088 。`NapCat` 协议端在 v4.8.115 起支持直接传输，无需配置此项。 |

## 🎉 指令

```text
/关注仓库 仓库url [--分支名]
/取关仓库 仓库url [--分支名]
/设置仓库 仓库url [--分支名]
/拉取仓库 仓库url [--分支名]
/仓库摘要 仓库url [--分支名]
/仓库列表
```

带 URL 的命令都支持可选分支后缀，例如 `/关注仓库 https://example.test/repo.git --dev`。`/关注仓库` 不写分支时追踪远端默认分支；其他命令不写分支时优先使用本群本仓库的唯一订阅，若同仓库关注了多个分支则需要写 `--分支名`。

`/关注仓库` 在当前群关注仓库。同一个群可以关注同一仓库的不同分支。

`/取关仓库` 移除当前群的对应仓库分支订阅，不影响其他群。

`/设置仓库` 进入设置流程。Bot 会回复：

```text
输入设置数字选项
1. 修改当前仓库推送抓取时间
2. 修改当前仓库上传压缩包密码（选择后输入无则清除当前仓库密码）
```

回复 `1` 后，下一条消息必须是合法定时格式。回复 `2` 后，下一条消息会保存为当前仓库压缩包密码，此时输入 `无` 会清除当前仓库密码。输入非法会取消。

```text
定时格式

每天hh:mm
每隔hh:mm
每x天hh:mm
周xhh:mm
```

`每隔` 的时间范围是 `00:01` 到 `23:59`；`每x天` 的 `x` 使用 1 到 30 的整数；`周x` 只支持汉字 `一二三四五六日/天`

`/仓库列表` 显示当前群关注的仓库 Git 链接、分支、计划时间、SHA 和实际使用的压缩包密码。

`/拉取仓库` 立即拉取当前群已关注的仓库，上传最新的源码压缩包。

`/仓库摘要` 仅拉取远端并展示本群记录与远端 HEAD 的差异。

## ⚠️ 注意事项

使用 NapCat 上传较大的仓库压缩包时，如果 Bot 宿主机实际上传速度较慢，可能会出现“文件最终发送成功，但 NapCat API 先返回超时错误”的情况。这是 NapCat 在等待 QQNT 的发送回执时超时导致的伪超时，会导致本插件无法正常使用。

`NapCat` 在 v4.17.49 起提供了上传/下载超时预测配置。若遇到此类情况，请在 NapCat WebUI 的 OneBot 配置中自行调整： `预估上传速度(KB/s)` 或 `最大超时时间(毫秒)` 。
