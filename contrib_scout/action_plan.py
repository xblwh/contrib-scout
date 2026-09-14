"""Turn observed facts into checkable next steps, without inventing fixes."""

import re

from .source_hints import reproduction_excerpt


def problem_sections(body):
    sections = []
    heading = None
    buffer = []
    fence = None

    def flush():
        text = "\n".join(buffer).strip()
        if (
            heading
            and text
            and text.lower() not in {"no response", "_no response_", "n/a", "none"}
        ):
            sections.append(
                {"label": heading, "text": text[:900], "truncated": len(text) > 900}
            )

    for line in body.splitlines():
        marker = re.match(r"^\s*(`{3,}|~{3,})", line)
        if marker:
            if fence is None:
                fence = (marker[1][0], len(marker[1]))
            elif marker[1][0] == fence[0] and len(marker[1]) >= fence[1]:
                fence = None
            if heading:
                buffer.append(line)
            continue
        match = re.match(r"^#{1,6}\s+(.+)", line) if not fence else None
        if match:
            flush()
            buffer = []
            name = match[1].strip()
            heading = (
                name
                if re.search(
                    r"expected|actual|reproduc|steps|version|summary|description|期望|预期|实际|复现|版本|要解决|功能",
                    name,
                    re.I,
                )
                else None
            )
        elif heading:
            buffer.append(line)
    flush()
    return sections[:4]


def enrich_actions(candidate, issue, policy, documents):
    number = candidate["number"]
    issue_id = f"issue-{number}"
    sources = candidate["sources"]
    plan = []

    def add(kind, title, detail, ids):
        plan.append({"kind": kind, "title": title, "detail": detail, "source_ids": ids})

    hints = candidate.get("source_hints", {})
    evidence = candidate["relevance"]["evidence"]
    for index, row in enumerate(evidence):
        source_id = f"match-{number}-{index}"
        row["source_id"] = source_id
        sources.append(
            {
                "id": source_id,
                "label": row["label"],
                "url": row["url"],
                "excerpt": row["excerpt"],
                "category": "match",
            }
        )

    candidate["problem_evidence"] = problem_sections(issue.get("body") or "")
    repro = reproduction_excerpt(issue.get("body") or "")
    candidate["reproduction"] = repro
    if candidate["status"] == "skip":
        add(
            "check_state",
            "先确认问题是否仍适合处理",
            "问题已关闭、讨论锁定或仓库已归档。阅读状态原因，再决定是否继续。",
            [issue_id],
        )
    if candidate["assignees"]:
        add(
            "coordinate",
            "先确认已有负责人的工作范围",
            "当前 assignee："
            + ", ".join(candidate["assignees"])
            + "。先在原问题检查最新进展，避免开始重复实现。",
            [issue_id],
        )
    claims = [source["id"] for source in sources if source["id"].startswith("claim-")]
    if claims:
        add(
            "check_claim",
            "核实认领意向是否仍有效",
            "阅读这些评论及后续回复，确认是否已撤回、完成或转交；关键词命中不代表有效指派。",
            claims,
        )
    work_records = [
        source["id"] for source in sources if source.get("category") == "work_record"
    ]
    if work_records:
        add(
            "check_existing_work",
            "先核实正文里的实现与验证记录",
            "原问题已包含改动及验证章节。检查作者是否已有实现分支、等待提交的 PR 或仅提供方案草稿，确认剩余工作后再开始；本工具没有复核这些验证结果。",
            work_records,
        )
    active = [
        pull
        for pull in candidate["related_prs"]
        if pull["relation"] != "mention" and pull["state"] in {"open", "merged"}
    ]
    for pull in active[:2]:
        name = f"{pull['repository']}#{pull['number']}"
        add(
            "compare_pr",
            "比较 " + name,
            (
                "PR 已合并，先核实当前源码是否仍有原问题。"
                if pull["state"] == "merged"
                else "阅读 PR 的改动范围和讨论，确认是否覆盖你的拟改动。"
            )
            + "依据："
            + pull["relation_label"]
            + "；工具尚未判断实际 diff。",
            [pull["source_id"], issue_id],
        )
    if candidate["relevance"]["kind"] in {"unknown", "repository", "different_target"}:
        add(
            "check_relevance",
            "先确认这个问题所需的技术",
            "当前"
            + candidate["relevance"]["label"]
            + "。根据原文中的模块、复现代码和文件入口确认是否涉及你的技术栈。",
            [issue_id],
        )
    files = hints.get("files", [])
    for index, file in enumerate(files):
        source_id = f"file-{number}-{index}"
        file["source_id"] = source_id
        sources.append(
            {
                "id": source_id,
                "label": file["path"] + "（默认分支快照）",
                "url": file["url"],
                "excerpt": file["excerpt"] or file["note"],
                "category": "file",
            }
        )
    if files:
        add(
            "inspect_files",
            "从已核实的文件入口阅读",
            "问题原文提到的 "
            + "、".join(file["path"] for file in files)
            + " 在默认分支快照中存在。先阅读相关实现及上下文，文件存在不表示它就是根因。",
            [file["source_id"] for file in files] + [issue_id],
        )
    elif hints.get("mentioned_count"):
        add(
            "locate_files",
            "先核实原文中的路径",
            "原文提及 "
            + "、".join(item["path"] for item in hints.get("unverified", [])[:3])
            + "，但本次未确认对应文件。检查下方未核实原因，不把拟新增或过时路径当作现有实现。",
            [issue_id],
        )
    else:
        add(
            "locate_scope",
            "先定位「" + candidate["title"][:90] + "」涉及的模块",
            "问题原文未提供可核实的文件路径。根据它描述的 API 或功能查找实现与测试；当前不能给出可靠的修改文件。",
            [issue_id],
        )
    if repro:
        add(
            "reproduce",
            "检查原文代码后建立最小复现",
            "下方保留问题作者的代码或配置摘录（"
            + (repro["language"] or "未标注语言")
            + "）。先检查依赖、版本和副作用，再在隔离环境比较预期与实际行为；工具没有执行摘录。",
            [issue_id],
        )
    elif candidate["problem_evidence"]:
        first = candidate["problem_evidence"][0]
        add(
            "define_acceptance",
            "把原文诉求转成验收场景",
            "根据「"
            + first["label"]
            + "」里的具体行为建立输入、预期和实际结果。原文摘录见下方；功能提案需先确认维护者认可范围。",
            [issue_id],
        )
    else:
        add(
            "clarify_reproduction",
            "先补齐复现或验收信息",
            "当前未识别出复现代码或明确的行为段落。先阅读完整 issue，整理所需版本、输入和预期结果，再判断能否开始修改。",
            [issue_id],
        )

    # Rule review remains a separate obligation. It never becomes an automatic permission.
    refs = [finding["id"] for finding in policy.get("findings", [])[:3]]
    refs = refs or [doc["id"] for doc in documents[:2]] or [issue_id]
    policy_note = "规则原文、适用范围和审批/认领要求在报告的贡献规则区。"
    if not policy.get("documents_complete") or not policy.get("contributing_found"):
        policy_note = "贡献文档缺失或读取不完整，需先到仓库核实完整规则。"
    if any(doc.get("inherited") for doc in documents):
        policy_note += "本次包含共享规则，需要确认对该仓库的适用范围。"
    add(
        "policy",
        "开始实现前确认贡献规则",
        policy_note + "当前人工确认状态始终为待核实；协作状态不等于贡献许可。",
        refs,
    )
    add(
        "verify_change",
        "完成复现后再确定最小修复与回归验证",
        "让同一个输入在修改前暴露问题、修改后满足已确认的预期；具体测试命令应来自该项目文档，本报告未推测或运行命令。",
        [issue_id],
    )
    candidate["action_plan"] = plan
    candidate["next_steps"] = [step["title"] + "：" + step["detail"] for step in plan]
