"""Explain keyword relevance without equating it with implementation difficulty."""

import re

from .source_hints import mentioned_paths


def stack_matches(text, stack):
    return [
        term
        for term in stack
        if re.search(rf"(?<!\w){re.escape(term)}(?!\w)", text, re.I)
    ]


def relevance(issue, stack, language=None, branch=None):
    evidence = []
    target_languages = []
    title = issue.get("title") or ""
    languages = [
        "Python",
        "TypeScript",
        "JavaScript",
        "Go",
        "Rust",
        "Java",
        "Ruby",
        "C++",
        "C#",
    ]
    for name in languages:
        if re.search(
            rf"\bnative\s+{re.escape(name)}(?!\w)|(?<!\w){re.escape(name)}[- ]native\b|{re.escape(name)}\s*原生",
            title,
            re.I,
        ):
            target_languages.append(name)
    different_target = bool(
        stack
        and target_languages
        and not any(
            name.casefold() == term.casefold()
            for name in target_languages
            for term in stack
        )
    )
    fields = [
        ("title", "问题标题", issue.get("title") or "", 8),
        (
            "labels",
            "问题标签",
            ", ".join(x["name"] for x in issue.get("labels", [])),
            7,
        ),
        ("body", "问题正文", issue.get("body") or "", 4),
    ]
    for field, label, text, weight in fields:
        if field == "body":
            text = re.sub(
                r"https?://\S+|\b[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+#\d+", " ", text
            )
        terms = stack_matches(text, stack)
        if not terms:
            continue
        match = re.search(rf"(?<!\w){re.escape(terms[0])}(?!\w)", text, re.I)
        start = max(0, match.start() - 60)
        evidence.append(
            {
                "kind": field,
                "label": label,
                "terms": terms,
                "excerpt": text[start : start + 180],
                "url": issue["html_url"],
                "weight": weight,
            }
        )
    code_aliases = {
        "python": {"python", "py", "python3"},
        "typescript": {"typescript", "ts", "tsx"},
        "javascript": {"javascript", "js", "jsx"},
        "go": {"go", "golang"},
        "rust": {"rust", "rs"},
    }
    for match in re.finditer(
        r"(?m)^\s*(?:`{3,}|~{3,})([A-Za-z0-9_+-]+)\s*$", issue.get("body") or ""
    ):
        terms = [
            term
            for term in stack
            if match[1].casefold()
            in code_aliases.get(term.casefold(), {term.casefold()})
        ]
        if terms:
            evidence.append(
                {
                    "kind": "code_language",
                    "label": "代码块标注的语言",
                    "terms": terms,
                    "excerpt": match[0].strip(),
                    "url": issue["html_url"],
                    "weight": 6,
                }
            )
    repo = issue["html_url"].removeprefix("https://github.com/").split("/issues/", 1)[0]
    path_languages = {
        "py": "Python",
        "pyi": "Python",
        "ts": "TypeScript",
        "tsx": "TypeScript",
        "js": "JavaScript",
        "jsx": "JavaScript",
        "mjs": "JavaScript",
        "cjs": "JavaScript",
        "go": "Go",
        "rs": "Rust",
        "java": "Java",
        "rb": "Ruby",
    }
    paths = mentioned_paths(issue.get("body") or "", repo, branch)
    matched_paths = [
        row["path"]
        for row in paths
        if any(
            path_languages.get(row["path"].rsplit(".", 1)[-1].casefold(), "").casefold()
            == term.casefold()
            for term in stack
        )
    ]
    if matched_paths:
        names = {
            path_languages[path.rsplit(".", 1)[-1].casefold()].casefold()
            for path in matched_paths
        }
        evidence.append(
            {
                "kind": "file_extension",
                "label": "原文路径的扩展名",
                "terms": [term for term in stack if term.casefold() in names],
                "excerpt": "、".join(matched_paths[:3]),
                "url": issue["html_url"],
                "weight": 5,
            }
        )
    direct = bool(evidence)
    if not direct and language:
        terms = [term for term in stack if term.casefold() == language.casefold()]
        if terms:
            evidence.append(
                {
                    "kind": "repository_language",
                    "label": "仓库主要语言（间接线索）",
                    "terms": terms,
                    "excerpt": f"仓库主要语言为 {language}；尚未确认这个问题具体涉及该语言。",
                    "url": issue["html_url"].split("/issues/", 1)[0],
                    "weight": 1,
                }
            )
    kind = "direct" if direct else "repository" if evidence else "unknown"
    if different_target:
        kind = "different_target"
        evidence = [
            {
                "kind": "target_language",
                "label": "标题中的目标技术",
                "terms": target_languages,
                "excerpt": title,
                "url": issue["html_url"],
                "weight": 0,
            }
        ]
    if not stack:
        kind = "not_requested"
    labels = {
        "direct": "问题文本有匹配线索",
        "repository": "仅仓库语言匹配",
        "unknown": "技术相关性未确认",
        "different_target": "标题目标技术与所填技术栈不同",
        "not_requested": "未设置技术栈筛选",
    }
    evidence.sort(key=lambda row: row["weight"], reverse=True)
    return {
        "kind": kind,
        "label": labels[kind],
        "evidence": [
            {k: v for k, v in row.items() if k != "weight"} for row in evidence
        ],
        "score": max((row["weight"] for row in evidence), default=0),
        "note": "文本命中和仓库语言只说明相关线索，不证明所需技能、难度或工作量。",
    }


def shortlist_score(issue, stack, language=None, branch=None):
    match = relevance(issue, stack, language, branch)
    labels = {x["name"].lower() for x in issue.get("labels", [])}
    # Direct evidence stays ahead of an indirect repository-language match.
    score = match["score"] * 10
    score += 4 if "good first issue" in labels else 0
    score += 2 if "help wanted" in labels else 0
    score -= 8 if issue.get("assignees") else 0
    return score
