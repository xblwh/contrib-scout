import argparse
import json
from pathlib import Path
import sys

from .github import GitHub, ResearchError
from .llm import enhance
from .report import demo_report, markdown
from .research import research


def main(argv=None):
    parser = argparse.ArgumentParser(description="Contrib Scout · 开源贡献调研助手")
    sub = parser.add_subparsers(dest="command", required=True)
    scan = sub.add_parser("research", help="调研公开 GitHub 仓库")
    scan.add_argument(
        "repo", nargs="?", help="owner/repo、owner/repo#编号，或 GitHub 仓库/issue URL"
    )
    scan.add_argument("--stack", default="Python, TypeScript")
    scan.add_argument("--limit", type=int, default=3)
    scan.add_argument(
        "--include-unmatched",
        action="store_true",
        help="也保留相关性未确认或目标技术不同的问题",
    )
    scan.add_argument(
        "--no-source-hints",
        action="store_true",
        help="跳过原文文件路径核实，减少 GitHub 请求",
    )
    scan.add_argument("--format", choices=["markdown", "json"], default="markdown")
    scan.add_argument("--out", type=Path)
    scan.add_argument(
        "--use-gh", action="store_true", help="使用本机已登录的 GitHub CLI"
    )
    scan.add_argument(
        "--ai", action="store_true", help="将公开调研材料发送给配置的模型服务"
    )
    scan.add_argument(
        "--demo", action="store_true", help="使用明确标注的虚构演示数据，不发网络请求"
    )
    server = sub.add_parser("serve", help="启动本地浏览器界面")
    server.add_argument("--port", type=int, default=8765)
    server.add_argument("--use-gh", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "serve":
            from .server import serve

            serve(args.port, args.use_gh)
            return 0
        if not args.repo and not args.demo:
            parser.error("research 需要仓库参数，或使用 --demo。")
        if args.demo and args.ai:
            parser.error("--demo 不发送网络请求，请去掉 --ai。")
        report = (
            demo_report()
            if args.demo
            else research(
                args.repo,
                args.stack,
                args.limit,
                GitHub(args.use_gh),
                include_unmatched=args.include_unmatched,
                check_sources=not args.no_source_hints,
            )
        )
        if args.ai:
            try:
                enhance(report)
            except ResearchError as exc:
                report["ai"] = {"enabled": False, "error": str(exc)}
                print(f"AI 分析未完成：{exc}", file=sys.stderr)
        output = (
            json.dumps(report, ensure_ascii=False, indent=2) + "\n"
            if args.format == "json"
            else markdown(report)
        )
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(output, encoding="utf-8")
            print(f"报告已保存：{args.out.resolve()}", file=sys.stderr)
        else:
            print(output, end="")
        return 0
    except (ResearchError, OSError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
