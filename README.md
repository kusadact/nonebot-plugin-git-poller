# nonebot-plugin-eratw-mirror

GitGud eraTW 魔改仓库更新搬运插件。

插件会按定时计划检查 GitGud 项目 `era-games-zh/touhou/eratw-sub-modding` 的指定分支：

1. 比较当前 commit 和本地保存的 `last_success_sha`。
2. 用 GitLab compare API 补齐两次推送间隔内的所有 commit。
3. 使用 dulwich 在插件 data 目录维护本地 Git 缓存，fetch 最新 commit，并导出到临时工作目录。
4. 使用 py7zr 本地重新打包为仅存储、带密码、隐藏文件列表的 7z。
5. 提取 `魔改版更新记录文档/补丁&readme集/ADD_BANQUET_开发日志.md` 在本次更新中的新增内容。
6. 上传 7z 群文件，并发送合并转发消息。

## 配置

在 NoneBot `.env` 中配置：

```bash
# 自动推送群白名单。为空时不会自动推送。
eratw_group_ids=[123456789]

# 定时检查。留空时关闭自动推送。
# daily@03:30: 每天 03:30
# weekly@mon,thu@03:30: 每周一、周四 03:30
# interval_days@2@03:30: 从下一个 03:30 开始，每 2 天一次
eratw_schedule="daily@04:00"
eratw_schedule_timezone="Asia/Shanghai"

# 可选代理，例如 http://127.0.0.1:7890
eratw_proxy=""

# 7z 密码，默认 eratoho
eratw_archive_password="eratoho"

# Git 拉取深度。1 表示浅克隆/浅 fetch，<=0 表示完整历史。
eratw_git_depth=1

# Git 拉取/导出超时，单位秒。
eratw_git_timeout=1800

# 可选：覆盖 Git 拉取地址。默认由 eratw_project_url 自动追加 .git。
eratw_git_url=""

# 群文件上传使用的临时 HTTP 下载基址。
# Bot 和 OneBot/NapCat 不在同一个文件系统时必须配置。
# Docker compose 中 NapCat 与 NoneBot 同网络时常见写法：
eratw_file_base_url="http://nonebot:8088"

# 临时下载路由和 token。token 为空时插件每次启动自动生成。
eratw_file_route_prefix="/eratw/files"
eratw_file_token=""

# 上传群文件 API 等待时间，单位秒。大文件建议 1800-7200。
eratw_upload_api_timeout=3600

# 合并转发节点展示 QQ 和昵称
eratw_node_user_id=2854196310
eratw_node_nickname="eraTW 更新"
```

## 指令

```text
/eratw测试推送
```

仅限 SuperUser。优先重发最近一次已生成的推送；如果没有历史推送，就拉取最新 commit，生成压缩包，并发送测试合并转发消息。测试命令不会更新 `last_success_sha`。

## 消息结构

合并转发消息按如下节点构造：

```text
消息1: commit 标题 1
消息2: commit 标题 2
...
消息x: 加密压缩包信息
消息x+1: 本次更新的开发日志
```

压缩包会先作为群文件上传。合并转发中的压缩包节点包含文件名、大小、SHA256 和密码。

## 部署注意

Git 拉取由 Python 依赖 `dulwich` 完成，7z 归档由 Python 依赖 `py7zr` 生成，不需要额外安装系统 `git`、`7zz`、`7z` 或 `7za`。

插件会把持久数据放在 NoneBot localstore 的 data 目录下，例如 Docker 环境里的 `/workspace/data/nonebot_plugin_eratw_mirror/`：

- `git/source.git`: 本地裸 Git 缓存，用于后续增量 fetch。
- `archives/*.7z`: 已生成的加密 7z 归档。
- `state.json`、`last_payload.json`: 推送状态和最近一次推送缓存。

临时导出的源码工作目录放在 localstore cache 目录的 `work/<sha>/`，打包完成后可安全清理。

`upload_group_file` 实际由 OneBot 实现端执行。Bot 与 OneBot/NapCat 分容器部署时，OneBot 端无法读取 Bot 容器内的 `/workspace/...` 路径，需要配置 `eratw_file_base_url`，让 OneBot 通过 HTTP 下载插件生成的 7z。

大文件上传时，OneBot API 调用会长时间不返回。插件默认把 `upload_group_file` 的等待时间设为 3600 秒；如果你的 NoneBot 或适配器仍然提前超时，也可以在 `.env` 里额外设置 `API_TIMEOUT=3600`。

## 开发

本插件可以用 uv 管理依赖：

```bash
uv sync --group dev
uv run pytest -q
```

如果只想做语法检查：

```bash
uv run python -m compileall nonebot_plugin_eratw_mirror tests
```
