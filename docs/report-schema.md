# JSON 报告字段（v2）

使用 `--format json` 或浏览器「JSON」按钮导出。报告顶层 `version: 2` 是数据结构版本，软件版本为 0.2.0。字段为增量扩展；读取历史 v1 报告时，应将缺失字段视为未知，不补成已检查或已批准。

| 字段 | 内容 |
| --- | --- |
| `demo` | 是否为虚构演示数据 |
| `generated_at` | 本次采集完成时间，ISO 8601 |
| `target` | `mode` 为 `repository` 或 `issue`；`input` 为规范化目标；`issue_number` 在仓库模式下为空 |
| `repository` | 仓库链接、默认分支、许可证、最近推送等元数据 |
| `stack` | 分隔并去重后的技术栈关键词 |
| `documents` | 收集到的文档、文本摘录、来源仓库与是否来自公共共享规则 |
| `policy` | 原文线索、查找路径、文档读取完整性；`status` 始终为 `unreviewed` |
| `candidates` | 问题元数据、状态、风险、相关 PR、来源与建议 |
| `coverage` | 各类记录读取数量和覆盖标记；源码检查、人工政策确认均为 false |
| `warnings` | 截断、读取失败和未找到文档等具体缺口 |
| `metrics` | GitHub 请求次数和采集耗时 |
| `ai` | 是否成功生成分析；可包含模型名、用量、费用估算或失败原因 |

`policy.findings` 每条包含 `id`、`document_id`、`path`、`line`、`quote`、`url`、`categories` 和 `inherited`。行号对应收集文档的原文；链接指向相应 GitHub 行。文档之后变化时，链接内容可能变化，因此应同时保留报告中的引用文本和采集时间。

`candidates[].related_prs[].state` 区分 `open`、`closed`、`merged` 和可能的未知状态。`kind` 区分 `timeline`、`reference`、`similarity`。`same_repository` 表示 PR 是否属于当前仓库；这些字段不证明改动已解决同一个问题。

`candidates[].coverage` 包含 `timeline_scanned`、`timeline_complete`、`comments_scanned`、`comments_complete`。顶层对应的开放/关闭 PR 完整性与其分开记录。

`*_complete: true` 只表示列表查询在页数上限内读到末尾，不代表 PR 一定引用了该 issue，也不代表已经检查源码或排除了所有重复。返回刚好填满上限的最后一页时，保守标记为不完整。

模型引用只允许指向对应 issue 的来源、已收集文档和规则原文 ID。缺少用量时不估算费用。来源 ID 有效仅说明引用存在，不证明模型结论成立。
