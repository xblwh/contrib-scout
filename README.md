# Contrib Scout

**开源贡献调研助手：从 GitHub 证据出发，找到值得进一步投入的问题。**

输入公开仓库和技术栈，收集贡献文档、开放 issue、认领线索和相关 PR，生成可下载的调研报告。可选 AI 分析给出最小改动与验证思路，每个建议引用已有来源。

适合正在寻找第一次代码贡献、希望理解所用依赖、或想整理候选问题的开发者。

> v0.1 是调研工具。报告中的“可继续调研”表示值得进一步调查，不代表已复现、获得贡献许可、排除全部重复或保证 PR 合并。演示报告全部为虚构数据。

## 30 秒体验

需要 Python 3.11+。仓库包含已构建的前端，直接运行无需 Node.js、Python 第三方运行依赖或模型密钥。

```bash
# 在项目根目录运行
python3 -m contrib_scout serve
# 浏览器打开 http://127.0.0.1:8765
```

点击「查看演示报告」可离线体验筛选、证据展开和 Markdown 下载。Python 在部分 Windows 环境中命名为 `python`，相应替换命令即可。

调研真实公开仓库：

```bash
python3 -m contrib_scout research Hisn00w/ASu-skills \
  --stack "Python, TypeScript" --limit 3 --out reports/research.md

# 机器可读 JSON
python3 -m contrib_scout research owner/repo --format json --out reports/research.json
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
| 贡献文档 | 常见位置的 README、CONTRIBUTING、AGENTS、AI_POLICY | 提供原文链接，具体政策与组织规则仍需人工核实 |
| 初步候选 | issue 文本中的技术栈词和 `good first issue` / `help wanted` 标签 | 启发式排序，不是难度或合并概率评分 |
| 认领线索 | assignees、issue 评论 | 评论匹配只覆盖部分中英文表达；意向可能过期 |
| 相关 PR | issue 时间线、开放 PR 的 issue 引用与标题相似度 | 时间线关联不等于重复；相似标题仅作线索 |
| 下一步 | 明确列出贡献规则、源码复现、PR diff 和回归验证待办 | 工具没有执行这些步骤 |
| AI 建议 | 可选模型返回 JSON，引用受限于已收集来源 | 来源存在不意味着推论正确，仍需人工核验 |

四种状态：**可继续调研**、**需要核实**、**暂缓**、**不适合当前贡献**。已有 assignee 或开放的明确关联 PR 会标为暂缓；数据缺口、认领意向或疑似重复标为需要核实。

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
- 校验 issue 编号、必需字段和来源 ID；不合格输出整批丢弃，事实报告继续可用。
- 记录 token 用量与模型耗时。设置 `SCOUT_INPUT_PRICE_PER_MILLION` 和 `SCOUT_OUTPUT_PRICE_PER_MILLION` 后，按填写的单价估算 USD 费用；未配置就显示未知。

当前版本已用模拟模型响应验证请求和失败处理。**尚未完成真实付费模型的端到端验证，也没有对外宣称模型准确率。**

## 开发与验证

后端使用 Python 标准库，前端使用严格模式 TypeScript 和原生 DOM。前端构建产物纳入版本管理，方便首次运行。

```bash
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
  research.py     证据采集、有限范围的启发式筛选
  llm.py          可选 AI 建议与来源校验
  report.py       Markdown 输出与虚构演示
  server.py       本地 HTTP 服务与异步调研任务
  cli.py          命令行入口
  web/            随包分发的浏览器界面
frontend/app.ts   TypeScript 界面逻辑
tests/           离线自动化测试
docs/            设计取舍、评测说明与学习路径
```

设计取舍见 [architecture.md](docs/architecture.md)，验证范围见 [evaluation.md](docs/evaluation.md)，参与开发见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 当前边界

- 只支持公开 GitHub 仓库，服务只绑定 `127.0.0.1`；不适合直接作为公网多用户服务。
- 从最近更新的最多 100 条 issue/PR 混合记录中筛选 1–8 个候选；最多读取 500 个开放 PR、每个候选 300 条时间线记录和 300 条评论。达到上限就标明可能不完整。
- 不遍历所有历史关闭 PR、不克隆或执行仓库代码、不核实当前默认分支是否已修复。标题相似度和认领词匹配均可能漏报或误报。
- 未自动解析所有贡献政策，也未解析复杂 monorepo 的分层规则；读取不到文档不表示没有规则。
- 每份文档最多读取 24000 字符，模型输入仅包含每份文档的前 6000 字符与候选摘录。
- 浏览器任务保存在当前服务进程内，最多保留 20 份；重启服务后清空。已下载报告仍由你保管。
- 不自动创建 issue、认领、fork、push 或提交 PR。

## 接下来

1. 用真实仓库人工标注案例，评估重复检测的漏报与误报。
2. 给贡献政策增加逐条引用、适用范围和人工确认状态。
3. 增加 issue URL 定向调研、关闭 PR 与源码定位。
4. 基于用户实际反馈优化候选选择，再考虑更复杂的 Agent 工作流。

这是一个用 AI 辅助开发的个人项目。发布者仍需理解实现、审核输出并维护测试；不应把尚未完成的功能或未经验证的分析写成已有成果。

## 接口参考

- [GitHub issue API](https://docs.github.com/en/rest/issues/issues)
- [GitHub issue timeline API](https://docs.github.com/en/rest/issues/timeline)
- [GitHub repository contents API](https://docs.github.com/en/rest/repos/contents)
- [OpenAI Chat Completions API](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)

## License

[MIT](LICENSE)
