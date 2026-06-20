<div align="center">
  <a href="https://v2.nonebot.dev/store">
    <img src="https://raw.githubusercontent.com/fllesser/nonebot-plugin-template/refs/heads/resource/.docs/NoneBotPlugin.svg" width="310" alt="logo">
  </a>

## nonebot-plugin-git-poller

</div>

按群订阅 Git 仓库更新的 NoneBot2 插件。每个群可以独立关注多个仓库，插件定时拉取远端仓库并推送 commit 更新摘要和源码压缩包。

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

只保留全局默认值，仓库 URL 不再写入 `.env`。群和仓库订阅通过命令维护。

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `git_poller_default_schedule` | `每日04-00` | 新关注仓库的默认定时规则；留空可关闭默认定时注册。 |
| `git_poller_timezone` | `Asia/Shanghai` | 定时任务时区。 |
| `git_poller_default_branch` | `main` | 新关注仓库的默认分支。 |
| `git_poller_proxy` | 空 | HTTP/HTTPS Git 拉取代理。 |
| `git_poller_timeout` | `60.0` | HTTP/HTTPS Git 拉取超时，单位秒。 |
| `git_poller_archive_password` | 空 | 全局默认压缩包密码；为空时默认不设置密码。 |
| `git_poller_file_base_url` | 空 | 上传压缩包时使用的 NoneBot HTTP 服务根地址；为空时直接传本地文件路径。 |
| `git_poller_file_route_prefix` | `/git-poller/files` | 压缩包下载路由前缀。 |
| `git_poller_file_token` | 空 | 压缩包下载链接签名密钥；为空时使用运行期随机密钥。 |
| `git_poller_file_token_ttl` | `3600` | 压缩包下载链接有效期，单位秒。 |
| `git_poller_command_priority` | `10` | 命令优先级。 |
| `git_poller_max_commits` | `20` | 单次最多展示 commit 数。 |

示例：

```dotenv
git_poller_default_schedule="每日04-00"
git_poller_timezone="Asia/Shanghai"
git_poller_default_branch="main"
git_poller_proxy="http://127.0.0.1:7890"
git_poller_timeout=60
git_poller_archive_password=""
git_poller_file_base_url=""
git_poller_file_route_prefix="/git-poller/files"
git_poller_file_token=""
git_poller_file_token_ttl=3600
git_poller_command_priority=10
git_poller_max_commits=20
```

`git_poller_file_base_url` 用于 NapCat 等 OneBot 实现和 bot 分离部署的场景。插件会在 localstore cache 的 `archives` 目录生成压缩包；默认上传时把本地绝对路径传给 OneBot。如果 OneBot 运行在另一个 Docker 容器里读不到这个路径，可以设置 NoneBot 容器在同一 Docker 网络内可访问的服务根地址，例如 `http://nonebot:8088`。插件会生成带过期时间和签名的下载 URL：`git_poller_file_base_url + git_poller_file_route_prefix + 文件名`，群文件展示名仍然保持为仓库压缩包名。

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

`/取关仓库 仓库url [--分支名]` 只移除当前群的对应仓库分支订阅，不影响其他群。取关后插件会在 1 小时后检查是否还有群关注同一个仓库分支；如果没有，会清理对应的本地 Git cache 和压缩包。

`/设置仓库 仓库url [--分支名]` 进入设置流程。Bot 会回复：

```text
输入设置数字选项
1. 修改当前仓库推送抓取时间
2. 修改当前仓库上传压缩包密码（选择后输入无则清除当前仓库密码回到全局默认）
```

回复 `1` 后，下一条消息必须是合法定时格式。回复 `2` 后，下一条消息会保存为当前仓库压缩包密码；输入 `无` 会清除当前仓库密码并回到全局默认。设置流程只接受同一群同一用户的后续回复，输入非法会取消。

`/仓库列表` 显示当前群关注的仓库、分支、定时、启用状态、`last_success_sha` 和压缩包密码来源。

`/拉取仓库 仓库url [--分支名]` 立即拉取当前群已关注的仓库，上传源码压缩包，并在上传成功后把 `last_success_sha` 更新到远端最新 HEAD。生成新压缩包时会清理当前订阅记录的旧压缩包。

`/仓库摘要 仓库url [--分支名]` 拉取远端并展示本群记录与远端 HEAD 的差异；本地与远程相同时只回复相同，不更新 `last_success_sha`。

定时推送发现新提交时，会先发送 commit 摘要，再上传源码压缩包；两者都成功后才更新当前群当前仓库分支的 `last_success_sha`。

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
          "last_archive_path": "/.../archives/repo-main-abcdef12-xxxx.7z",
          "archive_password": null,
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
