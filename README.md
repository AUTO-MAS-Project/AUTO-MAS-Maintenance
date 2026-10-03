# AUTOMAS-Update-API

将明日方舟、终末地的**中国大陆服官方维护公告**转换为静态 JSON，开放使用，并允许维护者手动覆盖状态适配提前开服。

## 开发

需要 Python 3.12+ 和 uv。运行时仅使用 Python 标准库。

```sh
uv sync --locked
uv run automas-update
```

更新命令默认读取 `config/overrides.json`，原子替换 `api/v1/maintain.json`，并把检测结果、覆盖状态及错误写入不提交的 `poll-report.json`。日常轮询安排在每天北京时间 05:07；客户端默认接受 48 小时内生成的状态。

退出码：`0` 表示成功；`1` 表示某个公告源读取或解析失败，已写出对应游戏为 `null` 的 fail-open 状态；`2` 表示配置或本地文件操作失败。无效 override 会在轮询及写入前拒绝，不替换已有状态。CI 使用 `--allow-source-failures` 先保存到 `data` 分支并上传 fail-open 结果，再读取报告让存在公告源错误的任务显示失败。

## 协议

状态文件为 `maintain.json`，[`api/v1/maintain.json`](api/v1/maintain.json) 是初始化示例，CI 生成的最新版本位于 `data` 分支并上传至数据中心，机器可读约束为 [`maintain.schema.json`](api/v1/maintain.schema.json)

示例：

```json
{
  "schema_version": 1,
  "generated_at": "2026-09-30T16:30:00+08:00",
  "games": {
    "arknights": {
      "maintenance": {
        "planned_start_at": "2026-10-08T10:00:00+08:00",
        "planned_end_at": "2026-10-08T16:00:00+08:00",
        "type": "version_update",
        "source_url": "https://ak.hypergryph.com/news",
        "override": false
      }
    },
    "endfield": {"maintenance": null}
  }
}
```

| 字段 | 语义 |
| --- | --- |
| `generated_at` | 本轮策略生成时间；源失败的游戏置 `null`，不会续期旧维护状态 |
| `maintenance: null` | 没有要执行的维护限制，可能是无维护、人工清除或源失败；不保证服务器在线 |
| `planned_start_at / planned_end_at` | RFC 3339 时间，必须含时区；生成端统一使用 `+08:00` |
| `type` | `version_update` 版本维护、`hotfix` 闪断、`emergency` 临时/紧急维护、`extension` 维护时间调整 |
| `source_url` | 对应官方公告链接；人工配置也可引用修正依据 |
| `override` | 当前非空维护窗口是否来自人工配置 |

## 人工覆盖

开发者或 bot 在确认提前开服后，触发同一个 `update.yml` 工作流，无须编辑状态文件。

开发者在 GitHub Actions 操作：

1. 打开 **Actions → 更新维护状态 / 标记已开服 → Run workflow**。
2. 使用默认分支，选择 `operation=mark-opened`，在 `game` 中选择 `arknights`（明日方舟）或 `endfield`（终末地）。
3. 点击 **Run workflow**，将所选游戏标记为已开服。

bot 使用 GitHub Actions 的 [`workflow_dispatch` API](https://docs.github.com/en/rest/actions/workflows#create-a-workflow-dispatch-event) 或 GitHub CLI 触发同一个操作。例如，确认明日方舟已开服后执行：

```sh
gh workflow run update.yml \
  --repo AUTO-MAS-Project/AUTO-MAS-Update-API \
  --ref main \
  -f operation=mark-opened \
  -f game=arknights
```

`--ref` 使用仓库默认分支。bot 的 GitHub App / fine-grained token 需要该仓库的 `Actions: write` 权限，使用 `GH_TOKEN` 提供；这是调用 GitHub 的凭证。仓库 Secret `AUTOMAS_TOKEN` 则由 CI 用于上传数据中心，bot 无须持有它。

同一个流程还支持 `operation=poll`（只轮询公告）和 `operation=sync`（只重试上传 `data` 分支的最新状态）。定时触发和代码 push 固定执行 `poll`；只有开发者或 bot 明确触发 `mark-opened` 才会记录开服。

CI 以执行时刻记录 `opened_at = now`，解除该时刻之前已开始的维护，并自动将状态和记录保存到独立的 `data` 分支，再上传至数据中心。CI 不修改 `main` 或默认分支。客户端在上传完成、下载缓存刷新后的下一次拉取时恢复正常执行。定时触发仍只轮询公告，不会标记开服。

这里的“开服时间”对应维护结束时间。现有协议的 `planned_start_at` 是**停服维护开始**，不能设成 `now` 来表示开服；已解除的维护会从对外状态中移除，输出 `maintenance: null`。若还有后续维护，则保留后续窗口。

`data` 分支的 `config/overrides.json` 由 CI 持久化开服记录，避免下一次轮询把旧公告重新恢复成维护状态。记录只影响开始时间不晚于 `opened_at` 的维护，之后开始的新维护仍正常生效。重复操作会更新所选游戏的开服时刻，不修改另一款游戏的人工记录。默认分支中的配置仅用于首次初始化；直接修改持久化人工配置时，应编辑 `data` 分支的同名文件。

本地等价命令：

```sh
uv run automas-update --mark-opened arknights
```

内部仍兼容完整时间窗口和带有效期的清除配置，格式见 [`overrides.example.json`](config/overrides.example.json) 和 [`overrides.schema.json`](config/overrides.schema.json)；日常人工开服通过上述 CI 入口完成。

## 同步到数据中心

已接入数据中心现有的 [Access Key 上传接口](https://github.com/AUTO-MAS-Project/AUTO-MAS-data-center-backend/blob/main/docs/API_EXAMPLES.md#14-access-key机器凭证与-cicd-上传)：`POST /api/v1/user/files/{file_id}/versions`，使用 `Authorization: Bearer $AUTOMAS_TOKEN`，multipart 字段为 `file` 和 `change_note`，上传文件名固定为 `maintain.json`。

`AUTOMAS_TOKEN` 已配置为仓库 Actions Secret。手动在数据中心建立目标文件，首次上传 `maintain.json` 后，在 **Settings → Secrets and variables → Actions → Variables** 填写以下配置：

| 类型 | 名称 | 值 |
| --- | --- | --- |
| Secret（已配置） | `AUTOMAS_TOKEN` | 已分配的完整 Access Key |
| Variable | `AUTOMAS_FILE_ID` | 目标文件的数字数据库 ID，不是 `file_key` |
| Variable | `AUTOMAS_PUBLIC_URL` | 该文件的公开下载 URL，不带版本号参数 |

公开下载 URL 为 `https://data.auto-mas.top/api/v1/files/{project_key}/{category_key}/{file_key}/download`，返回原始 JSON。客户端使用此固定 URL；网页文件详情地址不能用作下载 URL。数据中心的 `file_key` 由文件显示名生成，上传文件名不决定路由。

现有后端根据 Access Key 所属账号处理审核：管理员的上传自动审核通过并发布，普通用户的上传进入待审核。无人值守即时生效需要已分配的 Key 属于管理员账号。CI 检查上传结果的审核与发布版本，再回读客户端使用的公开下载 URL；待审核或下载内容不一致均显示失败。上传 POST 不自动重试，避免网络中断后创建重复版本；公开内容一致时跳过上传，409 冲突只有回读内容一致才视为成功。

- 每日北京时间 05:07 轮询，以及 Actions 人工标记开服，均生成 `api/v1/maintain.json`，保存到 `data` 分支后立即上传。公告源失败时也发布对应游戏为 `null` 的 fail-open 状态，再将任务标记失败。
- CI 从默认分支读取代码，仅向固定的 `refs/heads/data` 写入状态和人工记录。首次运行自动创建独立历史的 `data` 分支，只包含这两个 JSON 文件；后续执行先读取该分支最新内容。`main` 和默认分支不被 CI 修改。
- **Actions → 更新维护状态 / 标记已开服 → Run workflow** 选择 `operation=sync`，从 `data` 分支读取最新状态并重试上传，不重新轮询、不刷新 `generated_at`、不重新标记开服。
- 轮询、标记开服与重试使用同一个工作流和发布锁，统一执行上传。并发手动修改 `data` 分支会让过期状态的推送被拒绝；CI 不强推，不把旧结果覆盖到新开服记录上。
- 上传失败仍保留 `data` 分支中的状态和开服记录，可使用 `operation=sync` 重试。Secret 或 Variables 缺失时明确报错；目标文件尚未建立时，不会自动创建其他文件。

本地使用同名环境变量运行 `uv run automas-publish`，默认上传 `api/v1/maintain.json`。令牌只从环境变量读取，不接收命令行参数、不写入日志。下载接口的 CDN 应不缓存或使用短缓存；回读旧内容超过重试次数会报告失败。
