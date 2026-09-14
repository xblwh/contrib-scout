# JSON 报告字段（v3）

使用 `--format json` 或浏览器「JSON」按钮导出。报告顶层 `version: 3` 是数据结构版本，软件版本为 0.3.0。读取历史报告时，应将缺失字段视为未知，不补成已检查或已批准。v3 新增证据字段并调整协作状态含义；消费者不要用状态推导贡献许可。

| 字段 | 内容 |
| --- | --- |
| `demo` | 是否为虚构演示数据 |
| `generated_at` | 本次采集完成时间，ISO 8601 |
| `target` | `mode` 为 `repository` 或 `issue`；`input` 为规范化目标；`issue_number` 在仓库模式下为空 |
| `repository` | 仓库链接、默认分支、许可证、最近推送等元数据 |
| `stack` | 分隔并去重后的技术栈关键词 |
| `selection` | 请求数量、是否保留未匹配问题、排除数与匹配数量；定向模式请求数量为 1 |
| `documents` | 收集到的文档、文本摘录、来源仓库与是否来自公共共享规则 |
| `policy` | 原文线索、查找路径、文档读取完整性；`status` 始终为 `unreviewed` |
| `candidates` | 问题元数据、状态、风险、相关 PR、来源与建议 |
| `coverage` | 各类记录读取数量和覆盖标记；源码检查、人工政策确认均为 false |
| `warnings` | 截断、读取失败和未找到文档等具体缺口 |
| `metrics` | GitHub 请求次数和采集耗时 |
| `ai` | 是否成功生成分析；可包含模型名、用量、费用估算或失败原因 |

`policy.findings` 每条包含 `id`、`document_id`、`path`、`line`、`quote`、`url`、`categories` 和 `inherited`。行号对应收集文档的原文；链接指向相应 GitHub 行。文档之后变化时，链接内容可能变化，因此应同时保留报告中的引用文本和采集时间。

`candidates[].related_prs[].state` 区分 `open`、`closed`、`merged` 和可能的未知状态。`kind` 区分 `timeline`、`reference`、`similarity`。`same_repository` 表示 PR 是否属于当前仓库；这些字段不证明改动已解决同一个问题。

新增 `repository`、`relation`、`relation_label`、`intent_quote`、`scope_quote` 和 `source_id`。`relation` 是 `solution_intent`（作者提出解决意图）、`scope_unconfirmed`（Refs/Related 标注关联）、`possible_overlap`（标题相似）或 `mention`（普通引用）。它不同于 GitHub 自动关闭或手动 Development 关联；引用字段只保存识别出的作者声明，未核实 diff。`scope_unconfirmed` 保留范围检查义务，不直接产生暂缓。私有或公开性未知的跨仓库引用不导出内容。

候选新增字段：

| 字段 | 含义与限制 |
| --- | --- |
| `relevance` | `kind` 为 `direct`、`repository`、`unknown`、`different_target` 或 `not_requested`；`evidence` 保留命中位置、词、摘录和来源。`score` 仅用于内部排序，不是难度或成功概率 |
| `policy_check` | 始终 `unreviewed`，同时保存贡献文档查找结果和规则线索数；独立于协作状态 |
| `action_plan` | `kind`、`title`、`detail`、`source_ids` 构成有来源的待办；`next_steps` 是同一内容的兼容文本形式 |
| `source_hints` | 默认分支 `snapshot`、已确认 `files`、`unverified` 路径和原因、`mentioned_count`、`paths_omitted`；文件 URL 固定到 commit，原文行号可能发生漂移 |
| `problem_evidence` | 原文中的行为、版本等章节摘录；`truncated` 表示截断，最多 4 段 |
| `reproduction` | 作者代码或配置摘录，优先复现章节，最多 1400 字符；可能为空，始终未执行 |

`sources[].category` 可标为 `related_pr`、`mention`、`work_record`、`match` 或 `file`。实现记录只是作者陈述；`mention` 应与占用依据分开展示。并非每个来源都有 `category`，例如历史的 `issue-*`、`claim-*` 来源。

协作状态键保持 `investigate`、`review`、`hold`、`skip`，显示文字分别为“未发现占用线索”“协作状态待核实”“暂缓”“不适合当前贡献”。v3 中贡献文档的规则命中不再把所有候选自动改为 `review`，但每个候选保留待确认规则状态。

`candidates[].coverage` 包含 `timeline_scanned`、`timeline_complete`、`comments_scanned`、`comments_complete` 和 `cross_references_omitted`。顶层对应的开放/关闭 PR 完整性与其分开记录。顶层新增 `source_lookup_enabled`、`source_snapshot` 与 `source_paths_checked`（各候选已确认路径数之和，重复路径可能重复计数）；`source_code_checked` 仍为 false，不把文件摘录当成源码根因核实。

`*_complete: true` 只表示列表查询在页数上限内读到末尾，不代表 PR 一定引用了该 issue，也不代表已经检查源码或排除了所有重复。返回刚好填满上限的最后一页时，保守标记为不完整。

模型引用只允许指向实际发送的对应 issue 来源、文档和规则原文 ID。模型材料采用有上限的单独投影，记录截断和省略数；完整报告不会因模型输入截断而丢失来源。缺少用量时不估算费用。来源 ID 有效仅说明引用存在，不证明模型结论成立。

本地 `/api/jobs/<id>` 在报告外提供 `request`，用于恢复运行中或已完成任务的表单参数；仅保留仓库、技术栈、数量和三个布尔选项，不保存额外请求字段或密钥。Markdown/JSON 附件只导出报告本身。任务在服务重启后清空。
