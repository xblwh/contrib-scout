"""Small public-repository GitHub client. No GitHub write operations."""

import base64
import json
import os
import re
import subprocess
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


class ResearchError(Exception):
    pass


def parse_repo(value: str) -> str:
    if not isinstance(value, str):
        raise ResearchError("仓库地址必须是文本。")
    value = value.strip().rstrip("/")
    if value.startswith("https://"):
        parsed = urlparse(value)
        if parsed.netloc != "github.com" or parsed.query or parsed.fragment:
            raise ResearchError("请输入 github.com 的公开仓库链接，或 owner/repo。")
        value = parsed.path.lstrip("/")
    if value.endswith(".git"):
        value = value[:-4]
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_.-]{1,100}", value):
        raise ResearchError("仓库格式应为 owner/repo，例如 pydantic/pydantic-ai。")
    if value.split("/")[1] in {".", ".."}:
        raise ResearchError("无效的仓库名称。")
    return value


@dataclass(frozen=True)
class ResearchTarget:
    repo: str
    issue_number: int | None = None


def parse_target(value: str) -> ResearchTarget:
    """Accept a repository, an issue URL, or an owner/repo#number shorthand."""
    if not isinstance(value, str) or len(value) > 250:
        raise ResearchError("调研地址应为不超过 250 字的文本。")
    value = value.strip()
    if value.startswith("https://"):
        parsed = urlparse(value)
        if parsed.netloc != "github.com" or parsed.query:
            raise ResearchError("请输入 github.com 仓库或 issue 链接。")
        match = re.fullmatch(r"/([^/]+/[^/]+)/issues/([1-9]\d{0,9})/?", parsed.path)
        if match:
            if parsed.fragment and not re.fullmatch(
                r"(?:issuecomment-|issue-)\d+", parsed.fragment
            ):
                raise ResearchError("不支持这个 issue 链接锚点，请使用 issue 主链接。")
            return ResearchTarget(parse_repo(match[1]), int(match[2]))
        if "/pull/" in parsed.path:
            raise ResearchError(
                "该链接是 Pull Request；请提供要调研的 issue 或仓库链接。"
            )
    else:
        match = re.fullmatch(r"([^#]+)#([1-9]\d{0,9})", value)
        if match:
            return ResearchTarget(parse_repo(match[1]), int(match[2]))
    return ResearchTarget(parse_repo(value))


class GitHub:
    def __init__(self, use_gh=False):
        self.use_gh = use_gh
        self.requests = 0

    def get(self, path, optional=False):
        if not path.startswith("repos/") or ".." in path.split("/"):
            raise ResearchError("无效的 GitHub API 路径。")
        self.requests += 1
        if self.use_gh:
            try:
                result = subprocess.run(
                    ["gh", "api", "--hostname", "github.com", "-X", "GET", path],
                    text=True,
                    capture_output=True,
                    timeout=25,
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise ResearchError(
                    "无法运行 gh；请检查安装和登录，或去掉 --use-gh。"
                ) from exc
            if result.returncode:
                if optional and "(HTTP 404)" in result.stderr:
                    return None
                raise ResearchError(
                    "GitHub 请求失败；请检查仓库、gh 登录状态和 API 额度。"
                )
            try:
                return json.loads(result.stdout)
            except ValueError as exc:
                raise ResearchError("GitHub 返回了无效 JSON。") from exc
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "contrib-scout/0.3",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        token = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        try:
            with urlopen(
                Request("https://api.github.com/" + path, headers=headers), timeout=25
            ) as response:
                return json.load(response)
        except HTTPError as exc:
            exc.close()
            if exc.code == 404 and optional:
                return None
            messages = {
                401: "GitHub Token 无效。",
                403: "GitHub 拒绝请求或额度不足；请配置 Token 后重试。",
                404: "仓库不存在或不可访问。",
                429: "GitHub 请求过于频繁，请稍后重试。",
            }
            raise ResearchError(
                messages.get(exc.code, f"GitHub 请求失败（HTTP {exc.code}）。")
            ) from exc
        except (URLError, TimeoutError, ValueError) as exc:
            raise ResearchError("GitHub 网络请求失败或响应无效，请稍后重试。") from exc

    def pages(self, path, max_pages=5):
        """Return items and whether the configured page window was exhausted."""
        items = []
        joiner = "&" if "?" in path else "?"
        for page in range(1, max_pages + 1):
            batch = self.get(f"{path}{joiner}per_page=100&page={page}")
            if not isinstance(batch, list):
                raise ResearchError("GitHub 列表响应格式无效。")
            items.extend(batch)
            if len(batch) < 100:
                return items, False
        # Conservative: exactly full final page is also marked potentially incomplete.
        return items, True

    def document(self, repo, path):
        data = self.get(f"repos/{repo}/{path}", optional=True)
        if not data or not isinstance(data, dict) or data.get("encoding") != "base64":
            return None
        try:
            content = base64.b64decode(data.get("content", ""), validate=False).decode(
                "utf-8", errors="replace"
            )
        except (ValueError, TypeError) as exc:
            raise ResearchError("贡献文档内容无法解码。") from exc
        return {
            "path": data.get("path", path),
            "url": data.get("html_url", ""),
            "text": content[:24000],
            "truncated": len(content) > 24000,
        }
