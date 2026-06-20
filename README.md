<div align="center">
  <a href="https://v2.nonebot.dev/store">
    <img src="https://raw.githubusercontent.com/fllesser/nonebot-plugin-template/refs/heads/resource/.docs/NoneBotPlugin.svg" width="310" alt="logo">
  </a>

## nonebot-plugin-git-poller

</div>

按群订阅 Git 仓库更新的 NoneBot2 插件。每个群可以独立关注多个仓库，插件定时拉取远端仓库并推送 commit 更新摘要。

第一版只推送 commit 摘要，不包含源码压缩包、远端 worker、密码 7z 或特定项目 changelog 提取逻辑。

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

插件使用 Python 依赖 `dulwich` 拉取 Git 仓库，不要求系统额外安装 `git` 命令。

## 配置

只保留全局默认值，仓库 URL 不再写入 `.env`。群和仓库订阅通过命令维护。

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `git_poller_default_schedule` | `每日04-00` | 新关注仓库的默认定时规则；留空可关闭默认定时注册。 |
| `git_poller_timezone` | `Asia/Shanghai` | 定时任务时区。 |
| `git_poller_default_branch` | `main` | 新关注仓库的默认分支。 |
| `git_poller_proxy` | 空 | HTTP/HTTPS Git 拉取代理。 |
| `git_poller_timeout` | `60.0` | HTTP/HTTPS Git 拉取超时，单位秒。 |
| `git_poller_command_priority` | `10` | 命令优先级。 |
| `git_poller_max_commits` | `20` | 单次最多展示 commit 数。 |

示例：

```dotenv
git_poller_default_schedule="每日04-00"
git_poller_timezone="Asia/Shanghai"
git_poller_default_branch="main"
git_poller_proxy="http://127.0.0.1:7890"
git_poller_timeout=60
git_poller_command_priority=10
git_poller_max_commits=20
```

## 指令

```text
/关注仓库 仓库url [--分支名]
/取关仓库 仓库url [--分支名]
/设置仓库 仓库url [--分支名]
/仓库列表
/拉取仓库 仓库url [--分支名]
/仓库摘要 仓库url [--分支名]
```

带 URL 的命令都支持可选分支后缀，例如 `/关注仓库 https://example.test/repo.git --dev`。不写分支时使用 `git_poller_default_branch`。

`/关注仓库 仓库url [--分支名]` 在当前群关注仓库。插件只探测远端 HEAD 并记录为 `last_success_sha`，不会推送摘要。同一个群可以关注同一仓库的不同分支。

`/取关仓库 仓库url [--分支名]` 只移除当前群的对应仓库分支订阅，不影响其他群，也不会删除本地缓存文件。

`/设置仓库 仓库url [--分支名]` 第一阶段只回复后续格式示例，不会修改状态。

`/仓库列表` 显示当前群关注的仓库、分支、定时、启用状态和 `last_success_sha`。

`/拉取仓库 仓库url [--分支名]` 立即拉取当前群已关注的仓库，并把 `last_success_sha` 更新到远端最新 HEAD。

`/仓库摘要 仓库url [--分支名]` 拉取远端并展示本群记录与远端 HEAD 的差异；本地与远程相同时只回复相同，不更新 `last_success_sha`。

## 定时格式

支持：

```text
每日HH-MM
星期xHH-MM
星期xHHMM
```

`星期x` 兼容 `1-7` 和 `一二三四五六日/天`，其中 `1/一` 为星期一，`7/日/天` 为星期日。

`每周HH-MM` 因缺少星期几，第一版不作为正式格式。

## 状态

状态保存在 localstore 插件数据目录下的 `state.json`，结构按群和仓库独立保存：

```json
{
  "groups": {
    "123456789": {
      "repos": {
        "repo-main-xxxxxxxxxxxx": {
          "url": "https://github.com/example/repo.git",
          "branch": "main",
          "schedule": "每日04-00",
          "last_success_sha": "abcdef...",
          "enabled": true
        }
      }
    }
  }
}
```

## Git 支持

插件维护本地 bare cache，并通过 `dulwich` clone/fetch 远端仓库。HTTP/HTTPS URL、SSH scp-like URL、本地路径等由 `dulwich` 支持范围决定。

GitHub 使用 `/commit`、`/compare` 链接；GitLab/GitGud 使用 `/-/commit`、`/-/compare` 链接；其他通用 HTTP Git URL 会尽量生成 commit/compare 链接。
