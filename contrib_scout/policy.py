"""Quote possible contribution constraints; never interpret them as permission."""

import re

from .github import ResearchError

# Categories describe why a line is worth reading, not an automatic policy ruling.
SIGNALS = {
    "approval": (
        "讨论或审批线索",
        re.compile(
            r"(?:discuss|approval|permission).{0,80}(?:before|first|start|submit)|"
            r"(?:before|first).{0,80}(?:discuss|approval|permission)|"
            r"(?:require|obtain|need|seek).{0,35}(?:approval|permission)|先.{0,20}(?:讨论|沟通|批准|开.{0,8}issue)",
            re.I,
        ),
    ),
    "assignment": (
        "认领或指派线索",
        re.compile(
            r"\b(?:claim|assign(?:ed|ment)?)\b.{0,40}\b(?:issues?|yourself)\b|"
            r"\bissues?\b.{0,40}\b(?:claim|assign(?:ed|ment)?)\b|认领|指派",
            re.I,
        ),
    ),
    "ai": (
        "AI 使用规则线索",
        re.compile(
            r"(?=.*\b(?:AI|LLM|ChatGPT|Copilot)\b)(?=.*\b(?:disclos\w*|prohibit\w*|allow\w*|accept\w*|policy|policies|must|forbidden|review|responsib\w*)\b)|"
            r"(?:AI|LLM|人工智能|生成式).{0,70}(?:披露|标注|声明|审核|审查|禁止|不接受|允许|负责|冒领)|"
            r"(?:禁止|不接受|允许|披露|标注|声明|审核|审查).{0,40}(?:AI|LLM|人工智能|生成式)",
            re.I,
        ),
    ),
    "scope": (
        "贡献范围或限制线索",
        re.compile(
            r"typo[- ]only|drive[- ]by|(?:do not|don't|not accept|not allowed|禁止|不接受).{0,70}"
            r"(?:pull request|contribut|PR\b|提交|贡献|文档)|"
            r"(?:pull request|contribut).{0,70}(?:not accept|not allowed|prohibit)",
            re.I,
        ),
    ),
}


def excerpts(documents):
    findings = []
    for doc in documents:
        fence = None
        for number, line in enumerate(doc["text"].splitlines(), 1):
            stripped = line.strip()
            marker = re.match(r"^(`{3,}|~{3,})", stripped)
            if marker:
                if fence is None:
                    fence = marker[1][0]
                elif marker[1][0] == fence:
                    fence = None
                continue
            if fence or not stripped or stripped.startswith(">"):
                continue
            kinds = [
                label for _, (label, pattern) in SIGNALS.items() if pattern.search(line)
            ]
            if kinds:
                findings.append(
                    {
                        "id": f"policy-{doc['id']}-{number}",
                        "document_id": doc["id"],
                        "path": doc["path"],
                        "line": number,
                        "categories": kinds,
                        "quote": line[:1200],
                        "quote_truncated": len(line) > 1200,
                        "url": doc["url"].split("#", 1)[0] + f"#L{number}",
                        "inherited": doc.get("inherited", False),
                    }
                )
    return findings


def collect_documents(client, repo):
    documents, warnings = [], []
    checked_paths = []
    incomplete = False

    def first_document(source_repo, paths, inherited=False):
        nonlocal incomplete
        for path in paths:
            checked_paths.append(f"{source_repo}/{path}")
            try:
                doc = client.document(source_repo, path)
            except ResearchError as exc:
                incomplete = True
                warnings.append(f"文档读取失败：{source_repo}/{path}。{exc}")
                continue
            if doc:
                doc = {
                    **doc,
                    "id": f"doc-{len(documents) + 1}",
                    "repository": source_repo,
                    "inherited": inherited,
                }
                documents.append(doc)
                if doc["truncated"]:
                    incomplete = True
                    warnings.append(
                        f"{source_repo}/{doc['path']} 仅读取前 24000 字符。"
                    )
                return doc
        return None

    first_document(repo, ["readme"])
    contribution_paths = [
        "contents/.github/CONTRIBUTING.md",
        "contents/CONTRIBUTING.md",
        "contents/docs/CONTRIBUTING.md",
    ]
    contributing = first_document(repo, contribution_paths)
    # GitHub can inherit CONTRIBUTING from the owner's public .github repository.
    # If a local request failed, this is only a fallback lead, not proof of inheritance.
    if not contributing:
        shared_repo = repo.split("/")[0] + "/.github"
        if shared_repo.lower() != repo.lower():
            try:
                shared = client.get(f"repos/{shared_repo}", optional=True)
                if shared and not shared.get("private", True):
                    contributing = first_document(
                        shared_repo, contribution_paths, inherited=True
                    )
            except ResearchError as exc:
                incomplete = True
                warnings.append(f"共享贡献规则检查失败。{exc}")
    first_document(repo, ["contents/AGENTS.md"])
    first_document(
        repo,
        [
            "contents/AI_POLICY.md",
            "contents/.github/AI_POLICY.md",
            "contents/docs/AI_POLICY.md",
        ],
    )
    if not contributing:
        warnings.append(
            "常见路径与共享 .github 仓库未找到 CONTRIBUTING；其他规则仍需人工查阅。"
        )
    findings = excerpts(documents)
    if len(findings) > 40:
        warnings.append("贡献规则原文线索仅展示前 40 条，请继续阅读完整文档。")
    policy = {
        "status": "unreviewed",
        "contributing_found": bool(contributing),
        "documents_complete": not incomplete,
        "checked_paths": checked_paths,
        "findings": findings[:40],
        "findings_truncated": len(findings) > 40,
        "note": "以下为关键词命中的原文线索，可能遗漏或误匹配；不是贡献许可或自动政策结论。请结合上下文和适用范围逐条核实。",
    }
    return documents, policy, warnings
