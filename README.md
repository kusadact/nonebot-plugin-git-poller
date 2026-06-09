# nonebot-plugin-eratw-mirror

GitGud eraTW 魔改仓库更新搬运插件。

插件会按定时计划检查 GitGud 项目 `era-games-zh/touhou/eratw-sub-modding` 的指定分支：

1. 比较当前 commit 和本地保存的 `last_success_sha`。
2. 用 GitLab compare API 补齐两次推送间隔内的所有 commit。
3. 请求远端 worker 维护 Git 缓存、fetch 最新 commit，并导出源码。
4. worker 使用 py7zr 重新打包为仅存储、带密码、隐藏文件列表的 7z。
5. 提取 `魔改版更新记录文档/补丁&readme集/ADD_BANQUET_开发日志.md` 在本次更新中的新增内容。
6. 将 worker 下载地址交给 OneBot/NapCat 上传群文件，并发送合并转发消息。

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

# 远端 worker。必须配置。
eratw_worker_base_url="http://worker.example:18721"
eratw_worker_token="change-me"
eratw_worker_timeout=1800

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

## Worker

worker 是独立 Python HTTP 服务，不需要 NoneBot，也不需要系统 `git`、`7zz`、`7z` 或 `7za`。Git 拉取由 `dulwich` 完成，7z 归档由 `py7zr` 生成。

运行示例：

```bash
python3.11 -m venv /opt/eratw-worker/venv
/opt/eratw-worker/venv/bin/pip install dulwich==1.2.6 py7zr==1.1.0

export ERATW_WORKER_HOST=0.0.0.0
export ERATW_WORKER_PORT=18721
export ERATW_WORKER_PUBLIC_BASE_URL="http://worker.example:18721"
export ERATW_WORKER_TOKEN="change-me"
export ERATW_WORKER_DATA_DIR=/opt/eratw-worker/data
export ERATW_WORKER_CACHE_DIR=/opt/eratw-worker/cache
/opt/eratw-worker/venv/bin/python worker/eratw_worker.py
```

worker 持久数据：

- `data/git/*.git`: 本地裸 Git 缓存，用于后续增量 fetch。
- `data/archives/*/*.7z`: 已生成的加密 7z 归档。
- `cache/work/*`: 临时导出的源码工作目录，打包完成后可安全清理。

`upload_group_file` 实际由 OneBot/NapCat 执行。worker 返回的 `download_url` 必须能被 NapCat 访问；如果 NapCat 和 worker 在同一台 Docker 主机上，可以让 `ERATW_WORKER_PUBLIC_BASE_URL` 指向 NapCat 容器可访问的主机地址。

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
