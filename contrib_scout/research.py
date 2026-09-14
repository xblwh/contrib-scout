"""Collect source evidence, then apply explicitly limited screening heuristics."""

from datetime import datetime, timezone
import re
import time

from .github import GitHub, ResearchError, parse_target
from .policy import collect_documents

STATUS_LABELS = {
    "investigate": "可继续调研",
    "review": "需要核实",
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
STOPWORDS = {
    "this",
    "that",
    "with",
    "from",
    "when",
    "have",
    "does",
    "should",
    "support",
    "error",
    "issue",
    "fix",
    "test",
    "add",
}


def tokens(text):
    return {
        x
        for x in re.findall(r"[a-z][a-z0-9_+-]{2,}", text.lower())
        if x not in STOPWORDS
    }


def stack_matches(text, stack):
    return [
        term
        for term in stack
        if re.search(rf"(?<!\w){re.escape(term)}(?!\w)", text, re.I)
    ]


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


def explicit_reference(pull, repo, number):
    body = (pull.get("title") or "") + "\n" + (pull.get("body") or "")
    return bool(
        re.search(rf"(?<![\w/])#{number}\b", body)
        or re.search(rf"(?<![\w/]){re.escape(repo)}#{number}\b", body, re.I)
        or re.search(
            rf"https://github\.com/{re.escape(repo)}/issues/{number}(?!\d)", body, re.I
        )
    )


def shortlist_score(issue, stack):
    labels = [x["name"].lower() for x in issue.get("labels", [])]
    text = " ".join([issue.get("title", ""), issue.get("body") or "", *labels]).lower()
    matches = stack_matches(text, stack)
    score = len(matches) * 2
    score += 4 if "good first issue" in labels else 0
    score += 2 if "help wanted" in labels else 0
    score -= 5 if issue.get("assignees") else 0
    return score


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
    for event in timeline:
        source = event.get("source", {}).get("issue", {})
        if event.get("event") != "cross-referenced" or not source.get("pull_request"):
            continue
        url = source.get("html_url", "")
        if not re.fullmatch(r"https://github\.com/[^/]+/[^/]+/pull/\d+", url):
            continue
        merged = bool(source["pull_request"].get("merged_at"))
        related[url] = {
            "number": source["number"],
            "title": source.get("title", ""),
            "url": url,
            "state": "merged" if merged else source.get("state", "unknown"),
            "kind": "timeline",
            "same_repository": url.lower().startswith(
                f"https://github.com/{repo.lower()}/pull/"
            ),
            "reason": "Issue 时间线关联；是否解决同一问题仍需检查 diff",
        }
    issue_tokens = tokens(issue["title"])
    for pull in pulls:
        url = pull["html_url"]
        explicit = explicit_reference(pull, repo, number)
        other = tokens(pull["title"])
        overlap = len(issue_tokens & other)
        similar = overlap >= 2 and overlap / max(1, len(issue_tokens | other)) >= 0.35
        state = "merged" if pull.get("merged_at") else pull.get("state", "unknown")
        if url in related:
            # The PR endpoint is more explicit about merge state than an issue timeline source.
            related[url]["state"] = state
        elif explicit or similar:
            related[url] = {
                "number": pull["number"],
                "title": pull["title"],
                "url": url,
                "state": state,
                "kind": "reference" if explicit else "similarity",
                "same_repository": True,
                "reason": "PR 标题/正文引用该 issue"
                if explicit
                else "标题词语相似，仅为疑似重复",
            }
    for index, pull in enumerate(related.values()):
        sources.append(
            {
                "id": f"related-{number}-{index}",
                "label": f"相关 PR #{pull['number']}",
                "url": pull["url"],
                "excerpt": f"{pull['title']} — {pull['state']}；{pull['reason']}",
            }
        )
        if (
            pull["state"] == "open"
            and pull["kind"] != "similarity"
            and pull["same_repository"]
        ):
            risks.append(
                f"存在开放的关联 PR #{pull['number']}；先确认是否与拟改动重叠。"
            )
            status = "hold"
        elif pull["state"] in {"open", "merged"}:
            risks.append(
                f"{'已合并的' if pull['state'] == 'merged' else '疑似或跨仓库的'}相关 PR #{pull['number']} 需要人工比较。"
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
        "related_prs": list(related.values()),
        "sources": sources,
        "next_steps": [
            "阅读贡献规则和认领要求，确认允许当前类型的贡献。",
            "在当前默认分支复现问题，并检查相关 PR 的实际 diff。",
            "复现后再确定最小改动与回归测试；本报告未执行代码。",
        ],
        "ai": None,
    }


def research(repo, stack="Python, TypeScript", limit=3, client=None, progress=None):
    started = time.monotonic()
    target, terms = validate_inputs(repo, stack, limit)
    client = client or GitHub()
    progress = progress or (lambda message: None)
    progress("读取仓库与目标问题")
    metadata = client.get(f"repos/{target.repo}")
    if metadata.get("private"):
        raise ResearchError("当前版本仅调研公开仓库。")
    repo = metadata["full_name"]
    prefix = f"repos/{repo}"
    selected = None
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
        selected = sorted(
            issues, key=lambda item: shortlist_score(item, terms), reverse=True
        )[:limit]
        if issues_capped:
            warnings.append(
                "仅从最近更新的 100 条 issue/PR 混合记录中筛选，未覆盖全部开放 issue。"
            )
    else:
        issues, issues_capped = selected, False

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
        if not policy["documents_complete"] or not policy["contributing_found"]:
            candidate["risks"].append("贡献文档缺失或读取不完整，需先核实规则。")
            if candidate["status"] == "investigate":
                candidate["status"] = "review"
        if policy["findings"]:
            candidate["risks"].append(
                "发现贡献规则原文线索，需核实适用范围和前置条件。"
            )
            if candidate["status"] == "investigate":
                candidate["status"] = "review"
        if any(doc.get("inherited") for doc in documents):
            candidate["risks"].append(
                "使用共享贡献规则作为回退来源，适用范围仍待确认。"
            )
            if candidate["status"] == "investigate":
                candidate["status"] = "review"
        candidate["status_label"] = STATUS_LABELS[candidate["status"]]
        candidates.append(candidate)
    order = {"investigate": 0, "review": 1, "hold": 2, "skip": 3}
    candidates.sort(key=lambda item: order[item["status"]])
    progress("整理来源与调研报告")
    return {
        "version": 2,
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
            "policy_reviewed": False,
            "note": "仅在已读取记录中查找线索；未核对源码、运行复现或人工确认贡献政策。近期关闭 PR 有数量上限，时间线也可能缺失关联；未发现线索不代表问题仍未解决。",
        },
        "metrics": {
            "github_requests": client.requests,
            "elapsed_seconds": round(time.monotonic() - started, 2),
        },
        "ai": {"enabled": False},
    }
