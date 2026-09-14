# Contrib Scout

**开源贡献调研助手：从 GitHub 证据出发，找到值得进一步投入的问题。**

输入公开仓库或指定 issue 和技术栈，收集贡献文档、问题状态、认领线索和开放/近期关闭 PR，生成可下载的调研报告。可选 AI 分析给出最小改动与验证思路，每个建议引用已有来源。

适合正在寻找第一次代码贡献、希望理解所用依赖、或想整理候选问题的开发者。

> v0.3 是调研工具。“未发现占用线索”只描述本次读取范围内的协作线索。技术相关性和贡献规则分别展示；报告不代表已复现、获得贡献许可或保证 PR 合并。演示报告全部为虚构数据。

## 30 秒体验

需要 Python 3.11+。仓库包含已构建的前端，直接运行无需 Node.js、Python 第三方运行依赖或模型密钥。

```bash
git clone https://github.com/xblwh/contrib-scout.git
cd contrib-scout
python3 -m contrib_scout serve
# 浏览器打开 http://127.0.0.1:8765
```

点击「查看演示报告」可离线体验筛选、规则原文、证据展开和 Markdown / JSON 下载。Python 在部分 Windows 环境中命名为 `python`，相应替换命令即可。

[开发案例](docs/case-study.md)记录调研报告如何推动候选筛选改进，以及修改、验证和本项目内合并的过程。首页「阅读开发案例」提供流程页面。普通调研报告包含来源链接和摘录，分享前应检查其中的信息。

调研公开仓库（将 `owner/repo` 和问题编号 `42` 替换为实际目标）：

```bash
python3 -m contrib_scout research owner/repo \
  --stack "Python, TypeScript" --limit 3 --out reports/research.md

# 只调研指定 issue，不受仓库候选列表窗口影响
python3 -m contrib_scout research https://github.com/owner/repo/issues/42
python3 -m contrib_scout research "owner/repo#42" --use-gh

# 机器可读 JSON
python3 -m contrib_scout research owner/repo --format json --out reports/research.json

# 默认不以未匹配的问题凑满数量；需要扩大查看范围时显式开启
python3 -m contrib_scout research owner/repo --include-unmatched --limit 8
# 跳过原文文件路径的 GitHub 查询，仍保留待核实路径
python3 -m contrib_scout research owner/repo --no-source-hints
```

公共 GitHub API 无需 Token 即可访问，但额度较低。需要认证时，在本机终端设置 `GITHUB_TOKEN` / `GH_TOKEN`，或显式使用已登录的 GitHub CLI：

```bash
gh auth login
python3 -m contrib_scout serve --use-gh
python3 -m contrib_scout research owner/repo --use-gh
```

从本地目录安装命令行入口（推荐虚拟环境）：

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install .
contrib-scout serve
```

## 一份报告包含什么

| 内容 | 如何获取 | 需要怎样理解 |
| --- | --- | --- |
| 仓库概况 | GitHub 元数据，许可证、默认分支、最近推送 | 最近推送只是维护线索，不等于维护者愿意接受该贡献 |
| 贡献文档 | 常见位置的 README、CONTRIBUTING、AGENTS、AI_POLICY；必要时查找公共共享 .github 规则 | 提取带行号的规则原文线索，具体适用范围仍需人工核实 |
| 初步候选 | 标题、标签、正文、代码块语言、原文路径扩展名与仓库主要语言 | 展示直接文本证据或间接语言线索；默认不以未匹配的问题凑数，不是难度评分 |
| 认领线索 | assignees、issue 评论，考虑同一作者后续撤回 | 只覆盖部分中英文表达；语义仍需人工核实 |
| 相关 PR | issue 时间线、开放与近期关闭 PR 的编号引用、作者解决意图、标题相似度和合并状态 | 普通引用单独展示；Refs/Related 的关联范围待核实，开放的解决意图提示暂缓，仍需比较 diff |
| 文件入口 | 核实 issue 原文路径在默认分支快照中是否存在，保存固定 commit 链接和摘录 | 不推测路径、不执行代码；文件存在不证明根因 |
| 下一步 | 根据具体 PR、作者实现记录、路径、行为描述和复现材料生成带来源的待办 | 无足够材料时说明缺口；这些步骤均尚未执行 |
| AI 建议 | 可选模型返回 JSON，引用受限于已收集来源 | 来源存在不意味着推论正确，仍需人工核验 |

四种协作状态：**未发现占用线索**、**协作状态待核实**、**暂缓**、**不适合当前贡献**。已有 assignee 或开放 PR 表明作者解决意图时暂缓；数据缺口、认领意向、正文里的实现与验证记录、相似标题或已合并解决意图要求进一步核实。普通引用不作为占用或已解决的依据。贡献规则始终独立标为待人工确认。已关闭的目标 issue 保留证据并标为不适合当前贡献；传入 PR 编号会明确报错。

候选数量是上限。指定 issue 始终保留，即使没有技术匹配；仓库模式可开启「也看未匹配的问题」或将技术栈留空。繁忙仓库可能得到全部暂缓的候选，这不等于仓库没有其他机会；当前没有逐个调查全部 issue 直到找到空闲问题。

## 可选 AI 分析

在启动服务的终端设置以下变量。`.env.example` 是配置说明，应用不会自动读取 `.env`。

```bash
export SCOUT_LLM_BASE_URL="https://api.openai.com/v1"
export SCOUT_LLM_MODEL="你有权限使用、支持 JSON mode 的模型名称"
# 通过你本机的安全方式设置 SCOUT_LLM_API_KEY，不提交到 Git
python3 -m contrib_scout research owner/repo --ai
# 浏览器：重启服务后，按需勾选「AI 辅助分析」
```

实现使用 Chat Completions 协议、`response_format: json_object` 和 `max_completion_tokens: 4000`。可配置实现这些字段的兼容服务；并非所有兼容服务都支持。远程模型地址必须为 HTTPS，本地模型允许 localhost HTTP。

- 只有显式 `--ai` 或勾选开关时，公开仓库材料才会发往配置的模型服务。
- GitHub Token 不包含在模型输入中；网页不接收或展示模型密钥。
- 仓库文档和评论作为不可信材料传入，模型没有工具执行权限。
- 校验 issue 编号、必需字段和来源 ID（包括规则原文 ID）；不合格、被截断或被过滤的输出整批丢弃，事实报告继续可用。
- 记录 token 用量与模型耗时。设置 `SCOUT_INPUT_PRICE_PER_MILLION` 和 `SCOUT_OUTPUT_PRICE_PER_MILLION` 后，按填写的单价估算 USD 费用；缺少价格或有效 token 用量时显示未知。

当前版本已用模拟模型响应验证请求和失败处理。**尚未完成真实付费模型的端到端验证，也没有对外宣称模型准确率。**

## 开发与验证

后端使用 Python 标准库，前端使用严格模式 TypeScript 和原生 DOM。前端构建产物纳入版本管理，方便首次运行。

```bash
python3 -m pip install -e ".[dev]"
ruff check contrib_scout tests
ruff format --check contrib_scout tests
npm ci
npm run build
npm run check
python3 -m unittest discover -s tests -v
git diff --check
```

测试覆盖分页、PR 与 issue 混合返回、认领、关联 PR、疑似重复、陈旧问题、部分失败、模型引用校验、异步任务以及本地 HTTP 接口。CI 在 Python 3.11–3.13 上运行测试，并验证前端构建产物与源码同步。

```text
contrib_scout/
  github.py       GitHub 只读客户端与分页
  research.py     仓库/指定 issue 调研、有限范围的启发式筛选
  matching.py     技术相关性证据与初选排序
  references.py   普通引用、解决意图和标题相似线索
  source_hints.py 原文文件路径与默认分支快照核实
  action_plan.py  按已收集证据生成下一步
  policy.py       贡献文档与带行号的规则原文线索
  llm.py          可选 AI 建议与来源校验
  report.py       Markdown 输出与虚构演示
  server.py       本地 HTTP 服务与异步调研任务
  cli.py          命令行入口
  web/            随包分发的浏览器界面
frontend/app.ts   TypeScript 界面逻辑
tests/           离线自动化测试
docs/            架构、开发、评测与报告格式说明
```

设计取舍见 [architecture.md](docs/architecture.md)，验证范围见 [evaluation.md](docs/evaluation.md)，JSON 字段见 [report-schema.md](docs/report-schema.md)，调试入口见 [development-guide.md](docs/development-guide.md)，参与开发见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 当前边界

- 只支持公开 GitHub 仓库，服务只绑定 `127.0.0.1`；不适合直接作为公网多用户服务。
- 仓库模式从最近更新的最多 100 条 issue/PR 混合记录中筛选 1–8 个候选；指定 issue 模式直接读取该问题。两种模式最多读取 500 个开放 PR、100 个近期关闭 PR、每个候选 300 条时间线和 300 条评论。达到上限就标明可能不完整。
- 不遍历所有历史关闭 PR、不克隆或执行仓库代码、不核实当前默认分支是否已修复。作者解决意图采用有限的中英文声明和标题规则，并非 GitHub 自动关闭或 Development 手动关联的完整检测；标题相似度、认领词和实现记录识别均可能漏报或误报。
- 文件核实每个问题最多 2 个原文路径，每份报告最多 8 次文件查询，另有 1 次分支快照查询；先给各候选一次查询机会，再使用余量。报告最多展示每个问题的 12 个路径，所有缺口和省略数均保留。只识别部分常见扩展名和无歧义的 GitHub blob 链接；不解析任意分支名、路径中的空格或完整目录结构。旧路径、拟新增文件、目录和读取失败均不能当作已确认文件。
- 规则线索采用中英文关键词匹配，跳过围栏代码和引用段；最多展示 40 条、每条最多 1200 字符。它可能漏报或误报，不解析完整政策语义和复杂 monorepo 分层规则；读取不到文档不表示没有规则。共享 .github CONTRIBUTING 仅是待确认适用范围的回退来源，私有共享仓库不会读取。
- 每份文档最多读取 24000 字符。模型输入每份文档最多 3000 字符、20 条规则摘录（每条 600 字符）、每候选 20 条来源（issue 2000 字符、其余 600 字符）与 20 条风险；保留截断和省略标记，避免材料重复占用上下文。引用必须来自实际发送的材料。
- 浏览器任务保存在当前服务进程内，最多保留 20 份；同一标签页刷新后可恢复当前任务/报告，重启服务后清空。sessionStorage 只保存任务 ID；存储被禁用时仍能调研，但不能自动恢复。已下载报告仍由你保管。
- 不自动创建 issue、认领、fork、push 或提交 PR。

## 接下来

1. 用真实仓库人工标注案例，评估重复检测的漏报与误报。
2. 为原文线索增加人工确认记录，并探索更准确的政策适用范围识别。
3. 在已核实的文件入口上增加更深入的源码定位，并按需扩大历史 PR 检查范围。
4. 基于用户实际反馈优化候选选择，再考虑更复杂的 Agent 工作流。

本项目在开发中使用 AI 辅助。已完成的检查与验证范围见 [evaluation.md](docs/evaluation.md)。

## 接口参考

- [GitHub issue API](https://docs.github.com/en/rest/issues/issues)
- [GitHub issue timeline API](https://docs.github.com/en/rest/issues/timeline)
- [GitHub pull request API](https://docs.github.com/en/rest/pulls/pulls)
- [GitHub PR 与 issue 的关联方式](https://docs.github.com/en/issues/tracking-your-work-with-issues/using-issues/linking-a-pull-request-to-an-issue)
- [GitHub 默认社区规则](https://docs.github.com/en/communities/setting-up-your-project-for-healthy-contributions/creating-a-default-community-health-file)
- [GitHub repository contents API](https://docs.github.com/en/rest/repos/contents)
- [OpenAI Chat Completions API](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)

## License

[MIT](LICENSE)
