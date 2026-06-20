<div align="center">
  <a href="https://v2.nonebot.dev/store">
    <img src="https://raw.githubusercontent.com/fllesser/nonebot-plugin-template/refs/heads/resource/.docs/NoneBotPlugin.svg" width="310" alt="logo">
  </a>

## nonebot-plugin-git-poller

</div>

按群订阅 Git 仓库更新的 NoneBot2 插件，支持多仓库、多分支定时拉取，自动推送 commit 更新摘要并上传源码压缩包。

## 安装

在 NoneBot 项目目录中安装插件：

```bash
uv add git+https://github.com/kusadact/nonebot-plugin-git-poller.git
```

在 `pyproject.toml` 中加载插件：

```toml
[tool.nonebot]
plugins = ["nonebot_plugin_git_poller"]
```

## 配置

| 配置项 | 必填 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `git_poller_default_schedule` | 否 | `每日04:00` | 新关注仓库的默认定时规则；留空关闭默认定时注册。 |
| `git_poller_timezone` | 否 | `Asia/Shanghai` | 定时任务时区。 |
| `git_poller_proxy` | 否 | 空 | HTTP/HTTPS Git 拉取代理。 |
| `git_poller_timeout` | 否 | `60.0` | HTTP/HTTPS Git 拉取超时，单位秒。 |
| `git_poller_archive_password` | 否 | 空 | 全局默认压缩包密码；为空时默认不设置密码。 |
| `git_poller_file_base_url` | 条件 | 空 | 上传压缩包时使用的 NoneBot HTTP 服务根地址；Bot 和 OneBot/NapCat 不在同一个文件系统时必须配置，例如 http://nonebot:8088。 |

## 指令

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
2. 修改当前仓库上传压缩包密码（选择后输入无则清除当前仓库密码回到全局默认）
```

回复 `1` 后，下一条消息必须是合法定时格式。回复 `2` 后，下一条消息会保存为当前仓库压缩包密码，此时输入 `无` 会清除当前仓库密码并回到全局默认。输入非法会取消。

`/仓库列表` 显示当前群关注的仓库、分支、定时、启用状态、`last_success_sha` 和压缩包密码来源。

`/拉取仓库` 立即拉取当前群已关注的仓库，上传最新的源码压缩包。

`/仓库摘要` 仅拉取远端并展示本群记录与远端 HEAD 的差异。

## 定时格式

支持：

```text
每日hh:mm
每x天hh:mm
周xhh:mm
```

`每x天` 的 `x` 使用 1 到 30 的整数；`周x` 只支持汉字 `一二三四五六日/天`
