import json
from pathlib import Path
import re


def demo_report():
    return json.loads(Path(__file__).with_name("demo.json").read_text(encoding="utf-8"))


def clean(text):
    # Keep untrusted titles/excerpts from injecting HTML or breaking report headings.
    text = (
        str(text)
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\r", " ")
        .replace("\n", " ")
    )
    return re.sub(r"([\\`*{}_\[\]()#!|])", r"\\\1", text)


def code_block(text, language=""):
    """Preserve readable code without letting embedded fences end the block."""
    longest = max((len(x) for x in re.findall(r"`+", text)), default=0)
    fence = "`" * max(3, longest + 1)
    language = language if re.fullmatch(r"[A-Za-z0-9_+-]{0,30}", language) else ""
    return [fence + language, text, fence]


def markdown(report):
    repo = report["repository"]
    lines = [
        f"# Contrib Scout · {clean(repo['name'])}",
        "",
        f"采集时间：{report['generated_at']}",
        f"技术栈：{clean(', '.join(report['stack']))}",
        "",
    ]
    if report.get("target", {}).get("issue_number"):
        lines += [f"定向调研：Issue #{report['target']['issue_number']}", ""]
    if report["demo"]:
        lines += ["> 演示数据：仓库、问题和判断均为虚构，不代表真实贡献机会。", ""]
    lines += [
        f"仓库：{repo['url']}",
        f"许可证：{repo['license']} · 默认分支：{repo['default_branch']}",
        "",
        "## 调研范围",
        "",
        report["coverage"]["note"],
        "",
        f"扫描 issue：{report['coverage']['issues_scanned']}；开放 PR：{report['coverage']['open_prs_scanned']}；近期关闭 PR：{report['coverage'].get('closed_prs_scanned', 0)}。",
        "",
    ]
    for warning in report["warnings"]:
        lines.append(f"- {clean(warning)}")
    if report.get("selection"):
        selection = report["selection"]
        lines += [
            "",
            f"本次保留 {len(report['candidates'])} 个候选；排除未匹配的问题 {selection['unmatched_excluded']} 个。候选数量为上限，技术相关性与协作状态分开判断。",
            "",
        ]
    lines += ["", "## 贡献文档", ""]
    for doc in report["documents"]:
        shared = "；共享规则，待确认适用" if doc.get("inherited") else ""
        lines.append(f"- [{clean(doc['path'])}]({doc['url']})（{doc['id']}{shared}）")
    if not report["documents"]:
        lines.append("未读取到文档，请到仓库人工核实贡献要求。")
    if report.get("policy"):
        policy = report["policy"]
        lines += ["", "### 贡献规则原文线索（待人工确认）", "", policy["note"], ""]
        if not policy["findings"]:
            lines.append("未提取到关键词线索，不代表没有贡献限制；请阅读完整文档。")
        for finding in policy["findings"]:
            lines += [
                f"- [{clean(finding['path'])}:{finding['line']}]({finding['url']}) — {' / '.join(finding['categories'])}（{finding['id']}）",
                f"  > {clean(finding['quote'])}{'…（摘录截断）' if finding.get('quote_truncated') else ''}",
            ]
    for item in report["candidates"]:
        lines += [
            "",
            f"## #{item['number']} {clean(item['title'])}",
            "",
            f"**{item['status_label']}** · {item['url']}",
            "",
            f"创建：{item.get('created_at') or '未知'} · 更新：{item.get('updated_at') or '未知'}",
            "",
            "匹配线索：" + "；".join(clean(x) for x in item["reasons"]),
            "",
        ]
        if item.get("relevance"):
            lines += ["相关性：" + clean(item["relevance"]["label"]), ""]
            for evidence in item["relevance"]["evidence"]:
                lines.append(
                    f"- {clean(evidence['label'])}：{clean(evidence['excerpt'])}"
                )
            lines += ["", clean(item["relevance"]["note"]), ""]
        if item.get("policy_check"):
            check = item["policy_check"]
            lines += [
                "贡献规则：待人工确认；协作状态不代表贡献许可。"
                + (
                    "贡献文档缺失或读取不完整。"
                    if not check["documents_complete"]
                    or not check["contributing_found"]
                    else ""
                ),
                "",
            ]
        lines += [f"- 待核实：{clean(risk)}" for risk in item["risks"]]
        if not item["risks"]:
            lines.append(
                "当前扫描范围内未发现上述风险线索；不代表已排除重复或获得贡献许可。"
            )
        lines += ["", "建议下一步：", ""] + [
            f"{i}. {clean(step)}" for i, step in enumerate(item["next_steps"], 1)
        ]
        if item.get("action_plan"):
            lines += ["", "步骤来源 ID：", ""]
            lines += [
                f"- 第 {i} 步：{', '.join(step['source_ids'])}"
                for i, step in enumerate(item["action_plan"], 1)
            ]
        if item.get("source_hints"):
            hints = item["source_hints"]
            lines += ["", "### 文件入口核实", "", clean(hints["note"]), ""]
            for file in hints["files"]:
                lines += [
                    f"- [{clean(file['path'])}]({file['url']}) — {clean(file['note'])}",
                    "",
                ]
                if file["excerpt"]:
                    lines += code_block(file["excerpt"]) + [""]
            for gap in hints["unverified"]:
                lines.append(f"- 未核实 {clean(gap['path'])}：{clean(gap['reason'])}")
            if hints.get("paths_omitted"):
                lines.append(
                    f"另有 {hints['paths_omitted']} 个路径未展示，需阅读完整 issue。"
                )
        if item.get("problem_evidence") or item.get("reproduction"):
            lines += ["", "### 问题作者提供的材料（未验证）", ""]
            for section in item.get("problem_evidence", []):
                lines += [
                    f"{clean(section['label'])}：",
                    f"> {clean(section['text'])}{'…（截断）' if section['truncated'] else ''}",
                    "",
                ]
            if item.get("reproduction"):
                reproduction = item["reproduction"]
                lines += [
                    clean(reproduction["note"]),
                    "",
                ]
                lines += code_block(reproduction["text"], reproduction["language"]) + [
                    "…（截断）" if reproduction["truncated"] else "",
                    "",
                ]
        if item.get("coverage"):
            coverage = item["coverage"]
            lines += [
                "",
                f"问题证据范围：时间线 {coverage['timeline_scanned']} 条；评论 {coverage['comments_scanned']} 条。",
            ]
        if item["ai"]:
            analysis = item["ai"]
            lines += [
                "",
                "### AI 建议（未执行）",
                "",
                clean(analysis["summary"]),
                "",
                clean(analysis["suggested_scope"]),
                "",
                clean(analysis["verification_plan"]),
                "",
                "引用 ID：" + ", ".join(analysis["source_ids"]),
            ]
        lines += ["", "来源：", ""]
        for source in item["sources"]:
            if source.get("category") == "mention":
                continue
            lines += [
                f"- [{clean(source['label'])}]({source['url']})（{source['id']}）",
                f"  > {clean(source['excerpt'][:800])}",
            ]
        mentions = [
            source for source in item["sources"] if source.get("category") == "mention"
        ]
        if mentions:
            lines += ["", "普通引用（不作为占用或已解决的依据）：", ""]
            for source in mentions:
                lines += [
                    f"- [{clean(source['label'])}]({source['url']})（{source['id']}）",
                    f"  > {clean(source['excerpt'][:800])}",
                ]
    lines += [
        "",
        "## 运行信息",
        "",
        f"GitHub 请求：{report['metrics']['github_requests']}；采集耗时：{report['metrics']['elapsed_seconds']} 秒。",
    ]
    if report["ai"].get("enabled"):
        lines += [
            f"AI 模型：{report['ai']['model']}；耗时：{report['ai']['elapsed_seconds']} 秒。",
            "Token 用量：" + json.dumps(report["ai"]["usage"], ensure_ascii=False),
            f"估算费用（USD）：{report['ai']['estimated_cost_usd'] if report['ai']['estimated_cost_usd'] is not None else '未知（价格或用量不完整）'}。",
        ]
    elif report["ai"].get("error"):
        lines += ["AI 分析失败：" + clean(report["ai"]["error"])]
    return "\n".join(lines) + "\n"
