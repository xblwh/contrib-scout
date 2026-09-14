"""Check file paths quoted by an issue, without cloning or running its code."""

import base64
import re
from urllib.parse import quote, unquote, urlparse

from .github import ResearchError

EXTENSIONS = r"(?:py|pyi|ts|tsx|js|jsx|mjs|cjs|md|mdx|rst|json|toml|yaml|yml|html|css|go|rs|java|rb|sh)"
FILE_PATTERN = re.compile(
    rf"(?<![\w./~:-])(?:[\w.@-]+/)*[\w.@-]+\.{EXTENSIONS}(?![\w.-])", re.I
)


def safe_path(path):
    return (
        isinstance(path, str)
        and 0 < len(path) <= 220
        and not path.startswith(("/", "~"))
        and all(part not in {"", ".", ".."} for part in path.split("/"))
        and bool(re.fullmatch(r"[A-Za-z0-9_./@-]+", path))
    )


def mentioned_paths(body, repo, branch):
    """Only suggest literal paths; never invent a directory for a bare filename."""
    hints = {}
    urls = re.findall(r"https?://[^\s<>`\])]+", body)
    for url in urls:
        parsed = urlparse(url)
        prefix = f"/{repo}/blob/"
        if parsed.netloc != "github.com" or not parsed.path.casefold().startswith(
            prefix.casefold()
        ):
            continue
        suffix = unquote(parsed.path[len(prefix) :])
        # Ref names can contain slashes. Only a known branch or a full commit is unambiguous.
        if branch and suffix.startswith(branch + "/"):
            path = suffix[len(branch) + 1 :]
        elif re.match(r"^[a-fA-F0-9]{40}/", suffix):
            path = suffix[41:]
        else:
            continue
        if safe_path(path):
            anchor = re.fullmatch(r"L([1-9]\d*)(?:-L\d+)?", parsed.fragment)
            hints[path] = {"path": path, "line": int(anchor[1]) if anchor else None}
    # Remove URLs before extracting raw paths; foreign links must not become local hints.
    text = re.sub(r"https?://[^\s<>`\])]+", " ", body)
    for match in FILE_PATTERN.finditer(text):
        path = match[0]
        if safe_path(path) and path.casefold() not in {
            "node.js",
            "next.js",
            "vue.js",
            "react.js",
            "angular.js",
            "express.js",
        }:
            hints.setdefault(path, {"path": path, "line": None})
    qualified_names = {path.rsplit("/", 1)[-1] for path in hints if "/" in path}
    hints = {
        path: hint
        for path, hint in hints.items()
        if "/" in path or path not in qualified_names
    }

    def priority(hint):
        path = hint["path"]
        name = path.rsplit("/", 1)[-1].casefold()
        if name in {"contributing.md", "agents.md", "claude.md", "ai_policy.md"}:
            return 0
        if "/" in path:
            return 4 if not re.search(r"\.(?:md|mdx|rst)$", name) else 3
        return 1 if name.startswith("readme") else 2

    return sorted(hints.values(), key=priority, reverse=True)


class SourceInspector:
    def __init__(self, client, repo, branch, max_requests=8):
        self.client, self.repo, self.branch = client, repo, branch
        self.remaining = max_requests
        self.max_requests = max_requests
        self.ref = None
        self.ref_checked = False
        self.ref_error = None
        self.cache = {}

    def snapshot(self):
        if not self.ref_checked:
            self.ref_checked = True
            if not self.branch:
                self.ref_error = "仓库默认分支未知，未核实文件。"
                return None
            try:
                data = self.client.get(
                    f"repos/{self.repo}/branches/{quote(self.branch, safe='')}"
                )
                sha = (data.get("commit") or {}).get("sha")
                if not isinstance(sha, str) or not re.fullmatch(
                    r"[a-fA-F0-9]{40}", sha
                ):
                    raise ResearchError("默认分支快照格式无效。")
                self.ref = sha
            except ResearchError as exc:
                self.ref_error = f"默认分支快照读取失败：{exc}"
        return self.ref

    def inspect(self, issue, max_paths=2):
        all_hints = mentioned_paths(issue.get("body") or "", self.repo, self.branch)
        hints = all_hints[:12]
        result = {
            "files": [],
            "unverified": [],
            "mentioned_count": len(all_hints),
            "paths_omitted": max(0, len(all_hints) - len(hints)),
            "snapshot": None,
            "note": "只核实 issue 提及路径在默认分支快照中是否存在；未判断根因、运行源码或执行复现。",
        }
        if not hints:
            return result
        ref = self.snapshot()
        result["snapshot"] = ref
        if not ref:
            result["unverified"] = [
                {**hint, "reason": self.ref_error} for hint in hints
            ]
            return result
        for index, hint in enumerate(hints):
            path = hint["path"]
            if index >= max_paths:
                result["unverified"].append(
                    {**hint, "reason": f"每个问题最多核实 {max_paths} 个原文路径。"}
                )
                continue
            if path not in self.cache:
                if self.remaining <= 0:
                    result["unverified"].append(
                        {
                            **hint,
                            "reason": f"本次报告的 {self.max_requests} 次文件查询预算已用完。",
                        }
                    )
                    continue
                self.remaining -= 1
                try:
                    data = self.client.get(
                        f"repos/{self.repo}/contents/{quote(path, safe='/')}?ref={ref}",
                        optional=True,
                    )
                    self.cache[path] = {"data": data}
                except ResearchError as exc:
                    self.cache[path] = {"error": f"读取失败：{exc}"}
            cached = self.cache[path]
            if "error" in cached:
                result["unverified"].append({**hint, "reason": cached["error"]})
                continue
            data = cached["data"]
            if (
                not isinstance(data, dict)
                or data.get("type") != "file"
                or data.get("path") != path
            ):
                result["unverified"].append(
                    {
                        **hint,
                        "reason": "该路径在默认分支快照中未确认为普通文件；可能为旧路径、拟新增文件或目录。",
                    }
                )
                continue
            content = ""
            if (
                data.get("encoding") == "base64"
                and isinstance(data.get("size"), int)
                and data["size"] <= 200_000
            ):
                try:
                    content = base64.b64decode(data.get("content", "")).decode(
                        "utf-8", errors="replace"
                    )
                except (ValueError, TypeError):
                    pass
            lines = content.splitlines()
            requested_line = hint["line"] or 1
            line = requested_line if requested_line <= len(lines) else 1
            excerpt = "\n".join(lines[max(0, line - 3) : line + 7])[:1600]
            start_line = max(1, line - 2)
            result["files"].append(
                {
                    "path": path,
                    "url": f"https://github.com/{self.repo}/blob/{ref}/{quote(path, safe='/')}"
                    + (f"#L{start_line}" if lines else ""),
                    "excerpt": excerpt,
                    "line": start_line if lines else None,
                    "origin_url": issue["html_url"],
                    "note": "原文行号超过当前文件长度，展示文件开头；请检查历史版本。"
                    if hint["line"] and requested_line > len(lines) and lines
                    else "仅确认文件存在，未读取内容。"
                    if not lines
                    else "路径存在；原文行号在当前快照中可能已变化，摘录未执行。"
                    if hint["line"]
                    else "路径存在，摘录未执行。",
                }
            )
        return result


def reproduction_excerpt(body):
    """Prefer code from the author's reproduction section over earlier error logs."""
    section = ""
    fence = None
    language = ""
    content = []
    blocks = []
    for line in body.splitlines():
        if fence is None:
            heading = re.match(r"^#{1,6}\s+(.+)", line)
            if heading:
                section = heading[1].strip()
            marker = re.match(r"^\s*(`{3,}|~{3,})([^\n]*)$", line)
            if marker:
                fence = (marker[1][0], len(marker[1]))
                language = marker[2].strip()[:30]
                content = []
        elif re.fullmatch(rf"\s*{re.escape(fence[0])}{{{fence[1]},}}\s*", line):
            text = "\n".join(content).strip()
            if text:
                priority = (
                    2
                    if re.search(r"reproduc|复现|steps to", section, re.I)
                    else 1
                    if language.casefold()
                    in {
                        "python",
                        "py",
                        "typescript",
                        "ts",
                        "tsx",
                        "javascript",
                        "js",
                        "sh",
                        "bash",
                        "shell",
                        "go",
                        "rust",
                    }
                    else 0
                )
                blocks.append(
                    (
                        priority,
                        {
                            "language": language,
                            "section": section,
                            "text": text[:1400],
                            "truncated": len(text) > 1400,
                            "note": "问题作者提供的代码或配置摘录，未执行，不能保证可复现。",
                        },
                    )
                )
            fence = None
        else:
            content.append(line)
    return max(blocks, key=lambda item: item[0])[1] if blocks else None
