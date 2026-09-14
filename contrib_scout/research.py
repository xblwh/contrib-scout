"""Collect source evidence, then apply explicitly limited screening heuristics."""

from datetime import datetime, timezone
import re
import time

from .github import GitHub, ResearchError, parse_target
from .policy import collect_documents
from .matching import relevance, shortlist_score, stack_matches
from .references import explicit_reference as explicit_reference
from .references import hidden_cross_references, prose_lines, related_pulls
from .source_hints import SourceInspector, mentioned_paths
from .action_plan import enrich_actions

STATUS_LABELS = {
    "investigate": "未发现占用线索",
    "review": "协作状态待核实",
    "hold": "暂缓",
    "skip": "不适合当前贡献",
}
CLAIM = re.compile(
    r"\b(?:i(?:'m| am) working on|i(?:'d| would) like to work on|assign (?:this (?:issue )?to )?me|i(?:'ll| will) take (?:this|it))\b|我(?:来认领|正在处理|想认领|来修复)",
    re.I,
)
NEGATED_CLAIM = re.compile(
    r"(?:not|no longer|stopped) working|unassign|不再|放弃认领", re.I
)


def validate_inputs(repo, stack="Python, TypeScript", limit=3):
    target = parse_target(repo)
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 8:
        raise ResearchError("候选数量应为 1–8。")
    if not isinstance(stack, str) or len(stack) > 200:
        raise ResearchError("技术栈应为不超过 200 字的文本。")
    terms = list(
        dict.fromkeys(x.strip() for x in re.split(r"[,，/;；]", stack) if x.strip())
    )[:10]
    return target, terms


def assess(
    issue,
    pulls,
    timeline,
    comments,
    repo,
    stack,
    *,
    incomplete=False,
    archived=False,
    now=None,
):
    number = issue["number"]
    sources = [
        {
            "id": f"issue-{number}",
            "label": f"Issue #{number}",
            "url": issue["html_url"],
            "excerpt": (issue.get("body") or "（无问题描述）")[:6000],
        }
    ]
    risks, related = [], {}
    status = "investigate"
    if issue.get("assignees"):
        risks.append(
            "已有 assignee：" + ", ".join(x["login"] for x in issue["assignees"])
        )
        status = "hold"
    claims = {}
    for comment in comments:
        body = comment.get("body") or ""
        author = (comment.get("user") or {}).get("login")
        if NEGATED_CLAIM.search(body):
            if author:
                claims.pop(author, None)
        elif CLAIM.search(body):
            claims[author or f"unknown-{comment['id']}"] = comment
    for comment in claims.values():
        body = comment.get("body") or ""
        sources.append(
            {
                "id": f"claim-{comment['id']}",
                "label": "认领线索（需核实是否仍有效）",
                "url": comment["html_url"],
                "excerpt": body[:1200],
            }
        )
        risks.append("评论中出现认领意向；可能已过期，需要人工核实。")
        if status != "hold":
            status = "review"
    body = issue.get("body") or ""
    prose = list(prose_lines(body, with_offsets=True))
    implementation = next(
        (
            offset
            for offset, line in prose
            if re.match(
                r"^#{1,6}\s*(?:实现内容|实现细节|改动概要|主要改动|文件变更|改动文件|implementation details|changes proposed|files changed)",
                line,
                re.I,
            )
        ),
        None,
    )
    verification = next(
        (
            offset
            for offset, line in prose
            if re.match(
                r"^#{1,6}\s*(?:验证结果|测试结果|验证清单|verification results|test results)",
                line,
                re.I,
            )
        ),
        None,
    )

    def has_record(offset):
        if offset is None:
            return False
        section = body[offset:].split("\n", 1)
        if len(section) < 2:
            return False
        content = re.split(r"(?m)^#{1,6}\s+", section[1], maxsplit=1)[0]
        return content.strip().strip("_").casefold() not in {
            "",
            "no response",
            "n/a",
            "none",
            "待补充",
            "暂无",
        }

    if has_record(implementation) and has_record(verification):
        sources.append(
            {
                "id": f"work-{number}",
                "label": "问题正文中的实现与验证记录（作者陈述）",
                "url": issue["html_url"],
                "excerpt": body[implementation : implementation + 500]
                + "\n…\n"
                + body[verification : verification + 500],
                "category": "work_record",
            }
        )
        risks.append(
            "问题正文含实现与验证记录，需要确认是否已有改动、分支或待提交方案；这些记录未经本工具验证。"
        )
        if status != "hold":
            status = "review"
    related = related_pulls(issue, pulls, timeline, repo)
    for index, pull in enumerate(related):
        pull["source_id"] = f"related-{number}-{index}"
        name = f"{pull['repository']}#{pull['number']}"
        sources.append(
            {
                "id": pull["source_id"],
                "label": name + " · " + pull["relation_label"],
                "url": pull["url"],
                "excerpt": f"{pull['title']} — {pull['state']}；{pull['reason']}"
                + (
                    f" 原文：{pull['intent_quote'] or pull['scope_quote']}"
                    if pull["intent_quote"] or pull["scope_quote"]
                    else ""
                ),
                "category": "mention"
                if pull["relation"] == "mention"
                else "related_pr",
            }
        )
        if pull["relation"] == "mention":
            continue
        if pull["state"] == "open" and pull["relation"] == "solution_intent":
            risks.append(
                f"{name} 为开放 PR，作者提出解决该 issue 的意图；先核实拟改动是否重叠。"
            )
            status = "hold"
        elif pull["state"] in {"open", "merged", "unknown"}:
            risks.append(
                f"{name}（{pull['state']}）：{pull['relation_label']}，需要比较实际改动。"
            )
            if status != "hold":
                status = "review"
    if incomplete:
        risks.append("部分列表未完整读取，不能据此排除重复 PR 或认领。")
        if status != "hold":
            status = "review"
    if issue.get("updated_at"):
        try:
            age = (
                (now or datetime.now(timezone.utc))
                - datetime.fromisoformat(issue["updated_at"].replace("Z", "+00:00"))
            ).days
        except (ValueError, TypeError):
            age = 0
            risks.append("更新时间无法解析，需要回到 issue 页面核实。")
            if status != "hold":
                status = "review"
        if age > 180:
            risks.append(f"距最后更新已 {age} 天，需确认问题仍存在。")
            if status != "hold":
                status = "review"
    if archived or issue.get("state") != "open" or issue.get("locked"):
        if archived:
            risks.append("仓库已归档。")
        if issue.get("state") != "open":
            risks.append("Issue 已关闭或状态未知；先核实关闭原因与当前源码。")
        if issue.get("locked"):
            risks.append("Issue 讨论已锁定。")
        status = "skip"
    labels = [x["name"] for x in issue.get("labels", [])]
    searchable = " ".join([issue["title"], issue.get("body") or "", *labels]).lower()
    matches = stack_matches(searchable, stack)
    reasons = (
        [f"问题文本/标签包含 {', '.join(matches)}"]
        if matches
        else ["技术栈匹配尚未从问题文本确认"]
    )
    if any(x.lower() == "good first issue" for x in labels):
        reasons.append("维护者标注 good first issue")
    return {
        "number": number,
        "title": issue["title"],
        "url": issue["html_url"],
        "state": issue.get("state"),
        "created_at": issue.get("created_at"),
        "updated_at": issue.get("updated_at"),
        "labels": labels,
        "assignees": [x["login"] for x in issue.get("assignees", [])],
        "status": status,
        "status_label": STATUS_LABELS[status],
        "reasons": reasons,
        "risks": risks,
        "related_prs": related,
        "sources": sources,
        "next_steps": [
            "阅读贡献规则和认领要求，确认允许当前类型的贡献。",
            "在当前默认分支复现问题，并检查相关 PR 的实际 diff。",
            "复现后再确定最小改动与回归测试；本报告未执行代码。",
        ],
        "ai": None,
    }


def research(
    repo,
    stack="Python, TypeScript",
    limit=3,
    client=None,
    progress=None,
    *,
    include_unmatched=False,
    check_sources=True,
):
    started = time.monotonic()
    target, terms = validate_inputs(repo, stack, limit)
    if not isinstance(include_unmatched, bool) or not isinstance(check_sources, bool):
        raise ResearchError("筛选与文件核实选项必须为布尔值。")
    client = client or GitHub()
    progress = progress or (lambda message: None)
    progress("读取仓库与目标问题")
    metadata = client.get(f"repos/{target.repo}")
    if metadata.get("private"):
        raise ResearchError("当前版本仅调研公开仓库。")
    repo = metadata["full_name"]
    prefix = f"repos/{repo}"
    selected = None
    selection = {
        "include_unmatched": include_unmatched,
        "unmatched_excluded": 0,
        "matched_available": 0,
        "requested": limit,
    }
    if target.issue_number is not None:
        issue = client.get(f"{prefix}/issues/{target.issue_number}")
        if "pull_request" in issue:
            raise ResearchError("该编号实际是 Pull Request；请提供 issue 编号。")
        selected = [issue]
    progress("读取贡献文档与规则线索")
    documents, policy, warnings = collect_documents(client, repo)

    def fetch_list(path, label, max_pages):
        try:
            values, capped = client.pages(path, max_pages=max_pages)
            if capped:
                warnings.append(f"{label}可能不完整（最多 {max_pages * 100} 条）。")
            return values, capped
        except ResearchError as exc:
            warnings.append(f"{label}读取失败。{exc}")
            return [], True

    progress("检查开放与近期关闭的 PR")
    open_pulls, open_capped = fetch_list(
        prefix + "/pulls?state=open&sort=updated&direction=desc", "开放 PR 列表", 5
    )
    closed_pulls, closed_capped = fetch_list(
        prefix + "/pulls?state=closed&sort=updated&direction=desc",
        "近期关闭 PR 列表",
        1,
    )
    if selected is None:
        # Issue listing failure is fatal: an empty candidate list would imply no issues.
        entries, issues_capped = client.pages(
            prefix + "/issues?state=open&sort=updated&direction=desc", max_pages=1
        )
        issues = [item for item in entries if "pull_request" not in item]
        matches = {
            item["number"]: relevance(
                item, terms, metadata.get("language"), metadata.get("default_branch")
            )
            for item in issues
        }
        eligible = [
            item
            for item in issues
            if include_unmatched
            or matches[item["number"]]["kind"] not in {"unknown", "different_target"}
        ]
        selection["unmatched_excluded"] = len(issues) - len(eligible)
        selection["matched_available"] = sum(
            match["kind"] in {"direct", "repository"} for match in matches.values()
        )
        selected = sorted(
            eligible,
            key=lambda item: shortlist_score(
                item, terms, metadata.get("language"), metadata.get("default_branch")
            ),
            reverse=True,
        )[:limit]
        if issues_capped:
            warnings.append(
                "仅从最近更新的 100 条 issue/PR 混合记录中筛选，未覆盖全部开放 issue。"
            )
    else:
        issues, issues_capped = selected, False
        selection["requested"] = 1
        selection["matched_available"] = int(
            relevance(
                selected[0],
                terms,
                metadata.get("language"),
                metadata.get("default_branch"),
            )["kind"]
            in {"direct", "repository"}
        )

    inspector = SourceInspector(client, repo, metadata.get("default_branch"))
    candidates = []
    for index, issue in enumerate(selected, 1):
        progress(
            f"核对 issue #{issue['number']} 的时间线与评论（{index}/{len(selected)}）"
        )
        incomplete = open_capped or closed_capped
        records = []
        detail_coverage = {}
        for endpoint in ("timeline", "comments"):
            batch, capped = fetch_list(
                f"{prefix}/issues/{issue['number']}/{endpoint}",
                f"Issue #{issue['number']} 的 {endpoint}",
                3,
            )
            incomplete |= capped
            records.append(batch)
            detail_coverage[f"{endpoint}_scanned"] = len(batch)
            detail_coverage[f"{endpoint}_complete"] = not capped
        omitted = hidden_cross_references(records[0], repo)
        detail_coverage["cross_references_omitted"] = omitted
        if omitted:
            incomplete = True
            warnings.append(
                f"Issue #{issue['number']} 有 {omitted} 条跨仓库引用未确认公开可见，已省略其内容；关联检查存在缺口。"
            )
        candidate = assess(
            issue,
            open_pulls + closed_pulls,
            records[0],
            records[1],
            repo,
            terms,
            incomplete=incomplete,
            archived=metadata.get("archived", False),
        )
        candidate["coverage"] = detail_coverage
        candidate["relevance"] = relevance(
            issue, terms, metadata.get("language"), metadata.get("default_branch")
        )
        candidate["reasons"] = [candidate["relevance"]["label"]] + [
            row["label"] + "：" + ", ".join(row["terms"])
            for row in candidate["relevance"]["evidence"]
        ]
        candidate["policy_check"] = {
            "status": "unreviewed",
            "documents_complete": policy["documents_complete"],
            "contributing_found": policy["contributing_found"],
            "finding_count": len(policy["findings"]),
        }
        candidate["status_label"] = STATUS_LABELS[candidate["status"]]
        candidates.append(candidate)
    order = {"investigate": 0, "review": 1, "hold": 2, "skip": 3}
    candidates.sort(key=lambda item: order[item["status"]])
    issues_by_number = {item["number"]: item for item in selected}
    if check_sources:
        # Give each selected issue one lookup before spending a second on any issue.
        for candidate in candidates:
            progress(f"核实 issue #{candidate['number']} 的首个文件入口")
            inspector.inspect(issues_by_number[candidate["number"]], max_paths=1)
    progress("核实其余文件入口并整理行动建议" if check_sources else "整理行动建议")
    for candidate in candidates:
        item = issues_by_number[candidate["number"]]
        if check_sources:
            candidate["source_hints"] = inspector.inspect(item)
        else:
            paths = mentioned_paths(
                item.get("body") or "", repo, metadata.get("default_branch")
            )
            candidate["source_hints"] = {
                "files": [],
                "unverified": [
                    {**path, "reason": "本次未启用文件路径核实。"}
                    for path in paths[:12]
                ],
                "mentioned_count": len(paths),
                "paths_omitted": max(0, len(paths) - 12),
                "snapshot": None,
                "note": "本次未启用文件路径核实。",
            }
        enrich_actions(candidate, item, policy, documents)
    progress("整理来源与调研报告")
    return {
        "version": 3,
        "selection": selection,
        "demo": False,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "target": {
            "mode": "issue" if target.issue_number else "repository",
            "input": repo + (f"#{target.issue_number}" if target.issue_number else ""),
            "issue_number": target.issue_number,
        },
        "repository": {
            "name": repo,
            "url": metadata["html_url"],
            "description": metadata.get("description") or "",
            "language": metadata.get("language"),
            "stars": metadata.get("stargazers_count", 0),
            "license": (metadata.get("license") or {}).get("spdx_id") or "未识别",
            "archived": metadata.get("archived", False),
            "default_branch": metadata.get("default_branch"),
            "pushed_at": metadata.get("pushed_at"),
        },
        "stack": terms,
        "documents": documents,
        "policy": policy,
        "candidates": candidates,
        "warnings": warnings,
        "coverage": {
            "issues_scanned": len(issues),
            "open_prs_scanned": len(open_pulls),
            "open_prs_complete": not open_capped,
            "closed_prs_scanned": len(closed_pulls),
            "closed_prs_complete": not closed_capped,
            "issue_window_complete": not issues_capped,
            "source_code_checked": False,
            "source_paths_checked": sum(
                len(c["source_hints"]["files"]) for c in candidates
            ),
            "source_snapshot": inspector.ref,
            "source_lookup_enabled": check_sources,
            "policy_reviewed": False,
            "note": "仅在已读取记录中查找线索；文件核实仅确认原文路径与摘录，未判断源码根因、运行复现或人工确认贡献政策。近期关闭 PR 有数量上限，时间线也可能缺失关联；未发现线索不代表问题仍未解决。",
        },
        "metrics": {
            "github_requests": client.requests,
            "elapsed_seconds": round(time.monotonic() - started, 2),
        },
        "ai": {"enabled": False},
    }
