"""Collect source evidence, then apply explicitly limited screening heuristics."""

from datetime import datetime, timezone
import re
import time

from .github import GitHub, ResearchError, parse_repo

STATUS_LABELS = {"investigate": "可继续调研", "review": "需要核实", "hold": "暂缓", "skip": "不适合当前贡献"}
CLAIM = re.compile(r"\b(?:i(?:'m| am) working on|i(?:'d| would) like to work on|assign (?:this (?:issue )?to )?me|i(?:'ll| will) take (?:this|it))\b|我(?:来认领|正在处理|想认领|来修复)", re.I)
NEGATED_CLAIM = re.compile(r"(?:not|no longer|stopped) working|unassign|不再|放弃认领", re.I)
STOPWORDS = {"this", "that", "with", "from", "when", "have", "does", "should", "support", "error", "issue", "fix", "test", "add"}


def tokens(text):
    return {x for x in re.findall(r"[a-z][a-z0-9_+-]{2,}", text.lower()) if x not in STOPWORDS}


def explicit_reference(pull, repo, number):
    body = (pull.get("title") or "") + "\n" + (pull.get("body") or "")
    return bool(re.search(rf"(?<![\w/])#{number}\b", body) or
                re.search(rf"https://github\.com/{re.escape(repo)}/issues/{number}(?!\d)", body))


def shortlist_score(issue, stack):
    labels = [x["name"].lower() for x in issue.get("labels", [])]
    text = " ".join([issue.get("title", ""), issue.get("body") or "", *labels]).lower()
    matches = [term for term in stack if term.lower() in text]
    score = len(matches) * 2
    score += 4 if "good first issue" in labels else 0
    score += 2 if "help wanted" in labels else 0
    score -= 5 if issue.get("assignees") else 0
    return score


def assess(issue, pulls, timeline, comments, repo, stack, *, incomplete=False, archived=False, now=None):
    number = issue["number"]
    sources = [{"id": f"issue-{number}", "label": f"Issue #{number}", "url": issue["html_url"],
                "excerpt": (issue.get("body") or "（无问题描述）")[:6000]}]
    risks, related = [], {}
    status = "investigate"
    if issue.get("assignees"):
        risks.append("已有 assignee：" + ", ".join(x["login"] for x in issue["assignees"]))
        status = "hold"
    for comment in comments:
        body = comment.get("body") or ""
        if CLAIM.search(body) and not NEGATED_CLAIM.search(body):
            sources.append({"id": f"claim-{comment['id']}", "label": "认领线索（需核实是否仍有效）",
                            "url": comment["html_url"], "excerpt": body[:1200]})
            risks.append("评论中出现认领意向；可能已过期，需要人工核实。")
            if status != "hold":
                status = "review"
    for event in timeline:
        source = event.get("source", {}).get("issue", {})
        if event.get("event") != "cross-referenced" or not source.get("pull_request"):
            continue
        url = source.get("html_url", "")
        if not re.fullmatch(r"https://github\.com/[^/]+/[^/]+/pull/\d+", url):
            continue
        merged = bool(source["pull_request"].get("merged_at"))
        related[url] = {"number": source["number"], "title": source.get("title", ""), "url": url,
                        "state": "merged" if merged else source.get("state", "unknown"),
                        "kind": "timeline", "reason": "Issue 时间线关联；是否解决同一问题仍需检查 diff"}
    issue_tokens = tokens(issue["title"])
    for pull in pulls:
        url = pull["html_url"]
        explicit = explicit_reference(pull, repo, number)
        other = tokens(pull["title"])
        overlap = len(issue_tokens & other)
        similar = overlap >= 2 and overlap / max(1, len(issue_tokens | other)) >= 0.35
        if url not in related and (explicit or similar):
            related[url] = {"number": pull["number"], "title": pull["title"], "url": url,
                            "state": pull.get("state", "open"), "kind": "reference" if explicit else "similarity",
                            "reason": "PR 标题/正文引用该 issue" if explicit else "标题词语相似，仅为疑似重复"}
    for index, pull in enumerate(related.values()):
        sources.append({"id": f"related-{number}-{index}", "label": f"相关 PR #{pull['number']}",
                        "url": pull["url"], "excerpt": f"{pull['title']} — {pull['state']}；{pull['reason']}"})
        if pull["state"] == "open" and pull["kind"] != "similarity":
            risks.append(f"存在开放的关联 PR #{pull['number']}；先确认是否与拟改动重叠。")
            status = "hold"
        elif pull["state"] in {"open", "merged"}:
            risks.append(f"相关 PR #{pull['number']} 需要人工比较。")
            if status != "hold":
                status = "review"
    if incomplete:
        risks.append("部分列表未完整读取，不能据此排除重复 PR 或认领。")
        if status != "hold":
            status = "review"
    if issue.get("updated_at"):
        age = ((now or datetime.now(timezone.utc)) - datetime.fromisoformat(issue["updated_at"].replace("Z", "+00:00"))).days
        if age > 180:
            risks.append(f"距最后更新已 {age} 天，需确认问题仍存在。")
            if status != "hold":
                status = "review"
    if archived or issue.get("state") != "open" or issue.get("locked"):
        risks.append("仓库已归档、issue 已关闭或讨论已锁定。")
        status = "skip"
    labels = [x["name"] for x in issue.get("labels", [])]
    searchable = " ".join([issue["title"], issue.get("body") or "", *labels]).lower()
    matches = [term for term in stack if term.lower() in searchable]
    reasons = [f"问题文本/标签包含 {', '.join(matches)}" ] if matches else ["技术栈匹配尚未从问题文本确认"]
    if any(x.lower() == "good first issue" for x in labels):
        reasons.append("维护者标注 good first issue")
    return {"number": number, "title": issue["title"], "url": issue["html_url"], "state": issue.get("state"),
            "created_at": issue.get("created_at"), "updated_at": issue.get("updated_at"),
            "labels": labels, "assignees": [x["login"] for x in issue.get("assignees", [])],
            "status": status, "status_label": STATUS_LABELS[status], "reasons": reasons, "risks": risks,
            "related_prs": list(related.values()), "sources": sources,
            "next_steps": ["阅读贡献规则和认领要求，确认允许当前类型的贡献。", "在当前默认分支复现问题，并检查相关 PR 的实际 diff。", "复现后再确定最小改动与回归测试；本报告未执行代码。"],
            "ai": None}


def research(repo, stack="Python, TypeScript", limit=3, client=None):
    started = time.monotonic()
    repo = parse_repo(repo)
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 8:
        raise ResearchError("候选数量应为 1–8。")
    if not isinstance(stack, str) or len(stack) > 200:
        raise ResearchError("技术栈应为不超过 200 字的文本。")
    terms = [x.strip() for x in re.split(r"[,，/;；]", stack) if x.strip()][:10]
    client = client or GitHub()
    prefix = f"repos/{repo}"
    metadata = client.get(prefix)
    if metadata.get("private"):
        raise ResearchError("当前版本仅调研公开仓库。")
    repo = metadata["full_name"]
    prefix = f"repos/{repo}"
    warnings = []
    documents = []
    groups = [["readme"], ["contents/CONTRIBUTING.md", "contents/.github/CONTRIBUTING.md", "contents/docs/CONTRIBUTING.md"],
              ["contents/AGENTS.md"], ["contents/AI_POLICY.md", "contents/.github/AI_POLICY.md"]]
    for paths in groups:
        for path in paths:
            try:
                doc = client.document(repo, path)
            except ResearchError as exc:
                warnings.append(f"文档读取不完整：{path}。{exc}")
                break
            if doc:
                doc["id"] = f"doc-{len(documents) + 1}"
                documents.append(doc)
                if doc["truncated"]:
                    warnings.append(f"{doc['path']} 仅读取前 24000 字符。")
                break
    try:
        pulls, pulls_capped = client.pages(prefix + "/pulls?state=open&sort=updated&direction=desc")
    except ResearchError as exc:
        pulls, pulls_capped = [], True
        warnings.append(f"开放 PR 列表读取失败。{exc}")
    # Bounded shortlist, explicitly reported; the issues endpoint also returns PRs.
    entries, issues_capped = client.pages(prefix + "/issues?state=open&sort=updated&direction=desc", max_pages=1)
    issues = [item for item in entries if "pull_request" not in item]
    selected = sorted(issues, key=lambda item: shortlist_score(item, terms), reverse=True)[:limit]
    if pulls_capped:
        warnings.append("开放 PR 列表可能不完整（最多 500 条），重复检查有缺口。")
    if issues_capped:
        warnings.append("仅从最近更新的 100 条 issue/PR 混合记录中筛选，未覆盖全部开放 issue。")
    if not any("contributing" in doc["path"].lower() for doc in documents):
        warnings.append("常见路径未找到 CONTRIBUTING；需检查 README、组织级规则和其他文档。")
    candidates = []
    for issue in selected:
        incomplete = pulls_capped
        records = []
        for endpoint in ("timeline", "comments"):
            try:
                batch, capped = client.pages(f"{prefix}/issues/{issue['number']}/{endpoint}", max_pages=3)
                incomplete |= capped
                if capped:
                    warnings.append(f"Issue #{issue['number']} 的 {endpoint} 可能不完整（最多 300 条）。")
            except ResearchError as exc:
                batch, incomplete = [], True
                warnings.append(f"Issue #{issue['number']} 的 {endpoint} 读取失败。{exc}")
            records.append(batch)
        candidates.append(assess(issue, pulls, records[0], records[1], repo, terms,
                                 incomplete=incomplete, archived=metadata.get("archived", False)))
    order = {"investigate": 0, "review": 1, "hold": 2, "skip": 3}
    candidates.sort(key=lambda item: order[item["status"]])
    return {"version": 1, "demo": False, "generated_at": datetime.now(timezone.utc).isoformat(),
            "repository": {"name": repo, "url": metadata["html_url"], "description": metadata.get("description") or "",
                           "language": metadata.get("language"), "stars": metadata.get("stargazers_count", 0),
                           "license": (metadata.get("license") or {}).get("spdx_id") or "未识别",
                           "archived": metadata.get("archived", False), "default_branch": metadata.get("default_branch"),
                           "pushed_at": metadata.get("pushed_at")},
            "stack": terms, "documents": documents, "candidates": candidates, "warnings": warnings,
            "coverage": {"issues_scanned": len(issues), "open_prs_scanned": len(pulls), "open_prs_complete": not pulls_capped,
                         "issue_window_complete": not issues_capped, "source_code_checked": False, "policy_reviewed": False,
                         "note": "规则筛选只提供调研线索；未核对源码、复现问题、解析所有贡献政策或穷尽历史关闭 PR。"},
            "metrics": {"github_requests": client.requests, "elapsed_seconds": round(time.monotonic() - started, 2)},
            "ai": {"enabled": False}}
