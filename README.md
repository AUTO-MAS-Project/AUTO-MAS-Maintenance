# AUTOMAS-Update-API

将明日方舟、终末地的**中国大陆服官方维护公告**转换为静态 JSON，开放使用，并允许维护者手动覆盖状态适配提前开服。

## 开发

需要 Python 3.12+ 和 uv。运行时仅使用 Python 标准库。

```sh
uv sync --locked
uv run automas-update
```

更新命令默认读取由 CI 管理的 `config/overrides.json`，原子替换 `api/v1/status.json`，并把检测结果、覆盖状态及错误写入不提交的 `poll-report.json`。日常轮询安排在每天北京时间 05:07；客户端默认接受 48 小时内生成的状态。

退出码：`0` 表示成功；`1` 表示某个公告源读取或解析失败，已写出对应游戏为 `null` 的 fail-open 状态；`2` 表示配置或本地文件操作失败。无效 override 会在轮询及写入前拒绝，不替换已有状态。CI 使用 `--allow-source-failures` 先提交 fail-open 结果，再读取报告让存在公告源错误的任务显示失败。

## 协议

状态文件为 [`api/v1/status.json`](api/v1/status.json)，机器可读约束为 [`status.schema.json`](api/v1/status.schema.json)

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

维护者直接在 GitHub Actions 操作，无须编辑文件：

1. 打开 **Actions → 更新维护状态 / 标记已开服 → Run workflow**。
2. 使用默认分支，在 `game` 中选择 `arknights`（明日方舟）或 `endfield`（终末地）。
3. 点击 **Run workflow**，将所选游戏标记为已开服。

CI 以执行时刻记录 `opened_at = now`，解除该时刻之前已开始的维护，并自动提交状态和记录。客户端在 CI 完成、托管缓存刷新后的下一次拉取时恢复正常执行。定时触发仍只轮询公告，不会标记开服。

这里的“开服时间”对应维护结束时间。现有协议的 `planned_start_at` 是**停服维护开始**，不能设成 `now` 来表示开服；已解除的维护会从对外状态中移除，输出 `maintenance: null`。若还有后续维护，则保留后续窗口。

[`config/overrides.json`](config/overrides.json) 由 CI 持久化开服记录，避免下一次轮询把旧公告重新恢复成维护状态。记录只影响开始时间不晚于 `opened_at` 的维护，之后开始的新维护仍正常生效。重复操作会更新所选游戏的开服时刻，不修改另一款游戏的人工记录。

本地等价命令：

```sh
uv run automas-update --mark-opened arknights
```

内部仍兼容完整时间窗口和带有效期的清除配置，格式见 [`overrides.example.json`](config/overrides.example.json) 和 [`overrides.schema.json`](config/overrides.schema.json)；日常人工开服通过上述 CI 入口完成。
