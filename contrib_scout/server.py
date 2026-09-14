"""Loopback-only UI server. Bound jobs, requests and same-origin access."""

from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import threading
from urllib.parse import urlparse

from .github import GitHub, ResearchError
from .llm import configured, enhance
from .report import demo_report, markdown
from .research import research

WEB = Path(__file__).with_name("web")


class ScoutServer(ThreadingHTTPServer):
    def __init__(self, address, use_gh=False):
        self.use_gh = use_gh
        self.csrf = secrets.token_urlsafe(32)
        self.executor = ThreadPoolExecutor(max_workers=2)
        self.jobs = {}
        self.jobs_lock = threading.Lock()
        super().__init__(address, Handler)

    def run_job(self, job_id, data):
        try:
            report = research(data["repo"], data.get("stack", "Python, TypeScript"), data.get("limit", 3), GitHub(self.use_gh))
            if data.get("ai"):
                try:
                    enhance(report)
                except ResearchError as exc:
                    report["ai"] = {"enabled": False, "error": str(exc)}
            result = {"state": "complete", "report": report, "markdown": markdown(report)}
        except ResearchError as exc:
            result = {"state": "error", "error": str(exc)}
        except Exception:
            result = {"state": "error", "error": "调研发生内部错误，请检查仓库数据或稍后重试。"}
        with self.jobs_lock:
            self.jobs[job_id] = result

    def server_close(self):
        super().server_close()
        self.executor.shutdown(wait=False, cancel_futures=True)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def send(self, data, status=200, content_type="application/json; charset=utf-8", filename=None):
        body = data if isinstance(data, bytes) else json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if filename:
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def valid_host(self):
        port = self.server.server_port
        return self.headers.get("Host") in {f"127.0.0.1:{port}", f"localhost:{port}"}

    def do_GET(self):
        if not self.valid_host():
            self.send({"error": "Host 不允许。"}, 403)
            return
        path = urlparse(self.path).path
        if path == "/api/config":
            self.send({"ai_configured": configured(), "csrf": self.server.csrf, "use_gh": self.server.use_gh})
        elif path == "/api/demo":
            report = demo_report()
            self.send({"report": report, "markdown": markdown(report)})
        elif path == "/api/demo.md":
            self.send(markdown(demo_report()).encode(), content_type="text/markdown; charset=utf-8", filename="demo-research.md")
        elif path.startswith("/api/jobs/"):
            parts = path.split("/")
            with self.server.jobs_lock:
                job = self.server.jobs.get(parts[3])
            if len(parts) == 5 and parts[4] == "report.md" and job and job["state"] == "complete":
                filename = job["report"]["repository"]["name"].replace("/", "-") + "-research.md"
                self.send(job["markdown"].encode(), content_type="text/markdown; charset=utf-8", filename=filename)
            elif len(parts) == 4 and job:
                self.send(job)
            else:
                self.send({"error": "报告不存在或尚未完成，请重新调研。"}, 404)
        elif path in {"/", "/app.js", "/style.css"}:
            filename, mime = {"/": ("index.html", "text/html"), "/app.js": ("app.js", "text/javascript"),
                              "/style.css": ("style.css", "text/css")}[path]
            self.send((WEB / filename).read_bytes(), content_type=mime + "; charset=utf-8")
        else:
            self.send({"error": "Not found"}, 404)

    def do_POST(self):
        port = self.server.server_port
        origin = self.headers.get("Origin")
        if (not self.valid_host() or self.headers.get("X-Scout-Token") != self.server.csrf
                or (origin and origin not in {f"http://127.0.0.1:{port}", f"http://localhost:{port}"})):
            self.send({"error": "请求来源校验失败，请刷新页面。"}, 403)
            return
        if self.path != "/api/research":
            self.send({"error": "Not found"}, 404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 4096:
                raise ValueError()
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict) or not isinstance(data.get("repo"), str) or len(data["repo"]) > 250:
                raise ValueError()
            from .github import parse_repo
            parse_repo(data["repo"])
            if not isinstance(data.get("ai", False), bool):
                raise ValueError()
            if data.get("ai") and not configured():
                raise ResearchError("请先在服务端配置模型，再启用 AI 分析。")
        except (ValueError, UnicodeError, ResearchError) as exc:
            self.send({"error": str(exc) or "请输入有效的仓库和参数。"}, 400)
            return
        with self.server.jobs_lock:
            if sum(job["state"] == "running" for job in self.server.jobs.values()) >= 2:
                self.send({"error": "已有两项调研在运行，请等待完成。"}, 429)
                return
            if len(self.server.jobs) >= 20:
                oldest = next((key for key, job in self.server.jobs.items() if job["state"] != "running"), None)
                if oldest:
                    del self.server.jobs[oldest]
            job_id = secrets.token_urlsafe(16)
            self.server.jobs[job_id] = {"state": "running"}
        self.server.executor.submit(self.server.run_job, job_id, data)
        self.send({"job_id": job_id}, 202)


def serve(port=8765, use_gh=False):
    server = ScoutServer(("127.0.0.1", port), use_gh)
    print(f"Contrib Scout → http://127.0.0.1:{server.server_port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
