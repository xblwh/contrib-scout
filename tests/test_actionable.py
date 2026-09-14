"""Behavioral regressions for evidence relevance and actionable reports."""

import base64
import unittest

from contrib_scout.github import ResearchError
from contrib_scout.action_plan import problem_sections
from contrib_scout.matching import relevance, shortlist_score
from contrib_scout.references import related_pulls, solution_intent
from contrib_scout.research import assess, research
from contrib_scout.source_hints import (
    SourceInspector,
    mentioned_paths,
    reproduction_excerpt,
)
from test_research import FakeGitHub, issue, pull

SHA = "a" * 40


class MatchTests(unittest.TestCase):
    def test_original_python_path_is_relevant_without_language_name(self):
        match = relevance(
            issue(
                title="Improve generated entry parameters",
                body="Update `scripts/validate_skills.py` and `scripts/sync.mjs`",
                labels=[],
            ),
            ["Python", "TypeScript"],
            "HTML",
        )
        self.assertEqual(match["kind"], "direct")
        self.assertEqual(match["evidence"][0]["kind"], "file_extension")
        self.assertEqual(match["evidence"][0]["terms"], ["Python"])

    def test_same_repo_blob_path_supplies_tech_clue_but_foreign_link_does_not(self):
        for repo, expected in [
            ("demo/project", "direct"),
            ("other/project", "unknown"),
        ]:
            match = relevance(
                issue(
                    title="A client bug",
                    body=f"https://github.com/{repo}/blob/main/src/client.ts",
                    labels=[],
                ),
                ["TypeScript"],
                "HTML",
                "main",
            )
            self.assertEqual(match["kind"], expected)

    def test_native_go_proposal_is_not_typescript_match_from_background(self):
        match = relevance(
            issue(
                title="Create a native Go AI SDK",
                body="Run without a TypeScript runtime",
                labels=[],
            ),
            ["Python", "TypeScript"],
            "TypeScript",
        )
        self.assertEqual(match["kind"], "different_target")
        self.assertEqual(match["evidence"][0]["terms"], ["Go"])

    def test_code_fence_language_can_supply_direct_typescript_evidence(self):
        match = relevance(
            issue(title="A buffer bug", body="```ts\nread(buffer)\n```", labels=[]),
            ["TypeScript"],
            None,
        )
        self.assertEqual(match["kind"], "direct")
        self.assertEqual(match["evidence"][0]["kind"], "code_language")

    def test_foreign_python_repo_link_does_not_make_direct_match(self):
        match = relevance(
            issue(
                title="Gateway behavior",
                body="See anthropics/anthropic-sdk-python#42 and https://github.com/python/cpython",
                labels=[],
            ),
            ["Python"],
            "TypeScript",
        )
        self.assertEqual(match["kind"], "unknown")

    def test_repository_language_is_an_indirect_match(self):
        match = relevance(
            issue(title="Buffer loses a chunk", body="Unexpected output", labels=[]),
            ["Python"],
            "Python",
        )
        self.assertEqual(match["kind"], "repository")
        self.assertEqual(match["evidence"][0]["kind"], "repository_language")

    def test_direct_title_match_outranks_body_and_repository(self):
        direct = issue(title="Python parser bug", body="", labels=[])
        body = issue(title="Parser bug", body="Python", labels=[])
        indirect = issue(title="Parser bug", body="", labels=[])
        self.assertGreater(
            shortlist_score(direct, ["Python"], "Python"),
            shortlist_score(body, ["Python"], "Python"),
        )
        self.assertGreater(
            shortlist_score(body, ["Python"], "Python"),
            shortlist_score(indirect, ["Python"], "Python"),
        )

    def test_unmatched_issues_do_not_pad_the_shortlist(self):
        class Client(FakeGitHub):
            def pages(self, path, max_pages=5):
                if "/issues?" in path:
                    return [
                        issue(),
                        issue(
                            number=7, title="Adjust logo", body="Use blue", labels=[]
                        ),
                    ], False
                return [], False

        report = research("demo/project", limit=8, client=Client())
        self.assertEqual([c["number"] for c in report["candidates"]], [42])
        self.assertEqual(report["selection"]["unmatched_excluded"], 1)
        expanded = research(
            "demo/project", limit=8, client=Client(), include_unmatched=True
        )
        self.assertEqual(len(expanded["candidates"]), 2)

    def test_targeted_issue_keeps_unmatched_issue_with_explanation(self):
        result = research("demo/project#42", stack="Rust", client=FakeGitHub())
        self.assertEqual(len(result["candidates"]), 1)
        self.assertEqual(result["candidates"][0]["relevance"]["kind"], "unknown")
        self.assertTrue(
            any(
                x["kind"] == "check_relevance"
                for x in result["candidates"][0]["action_plan"]
            )
        )

    def test_empty_stack_means_no_preference(self):
        report = research("demo/project", stack="", client=FakeGitHub())
        self.assertEqual(len(report["candidates"]), 1)
        self.assertEqual(report["candidates"][0]["relevance"]["kind"], "not_requested")


class ReferenceIntentTests(unittest.TestCase):
    def test_refs_with_partial_scope_requires_review_without_claiming_a_fix(self):
        pr = pull(
            title="Decouple shared templates",
            body="Refs #42, handling only template drift.",
        )
        candidate = assess(issue(), [pr], [], [], "demo/project", ["Python"])
        self.assertEqual(candidate["status"], "review")
        self.assertEqual(candidate["related_prs"][0]["relation"], "scope_unconfirmed")
        self.assertIn("Refs #42", candidate["sources"][-1]["excerpt"])

    def test_explicit_non_target_mention_is_not_an_association_declaration(self):
        pr = pull(
            title="Fix CLI arguments",
            body="#42 concerns pagination and is not the target of this PR.",
        )
        result = related_pulls(issue(), [pr], [], "demo/project")
        self.assertEqual(result[0]["relation"], "mention")

    def test_negated_related_declaration_remains_a_mention(self):
        result = related_pulls(
            issue(),
            [pull(title="Update documentation", body="Not related to #42.")],
            [],
            "demo/project",
        )
        self.assertEqual(result[0]["relation"], "mention")

    def test_fixing_is_author_intent_without_claiming_auto_close(self):
        result = related_pulls(
            issue(),
            [pull(title="Fix the buffer", body="- fixing : #42")],
            [],
            "demo/project",
        )
        self.assertEqual(result[0]["relation"], "solution_intent")
        self.assertIn("未确认自动关闭", result[0]["reason"])

    def test_fix_title_with_issue_reference_is_preserved(self):
        self.assertIsNotNone(
            solution_intent(
                pull(
                    title="fix(parser): missing final chunk (#42)",
                    body="Correct the buffer flush.",
                ),
                "demo/project",
                42,
            )
        )

    def test_keyword_examples_do_not_create_intent(self):
        for body in [
            "Use `Fixes #42` in the template",
            "For example: Fixes #42",
            "Example: Closes #42",
        ]:
            self.assertIsNone(solution_intent(pull(body=body), "demo/project", 42))
        self.assertIsNotNone(
            solution_intent(
                pull(body="Fixes #42 by correcting the examples."), "demo/project", 42
            )
        )

    def test_plain_cross_repository_example_is_not_a_solution(self):
        source = pull(
            title="Improve our issue research",
            body="Validation example: https://github.com/demo/project/issues/42",
            html_url="https://github.com/other/tool/pull/2",
            state="closed",
            merged_at="2026-09-14T00:00:00Z",
            repository={"private": False},
            pull_request={"url": "api"},
        )
        result = related_pulls(
            issue(),
            [],
            [{"event": "cross-referenced", "source": {"issue": source}}],
            "demo/project",
        )
        self.assertEqual(result[0]["relation"], "mention")
        self.assertEqual(result[0]["repository"], "other/tool")

    def test_cross_repository_closing_reference_preserves_solution_intent(self):
        source = pull(
            title="A fix",
            body="Fixes demo/project#42",
            html_url="https://github.com/other/tool/pull/9",
            repository={"private": False},
            pull_request={"url": "api"},
        )
        result = related_pulls(
            issue(),
            [],
            [{"event": "cross-referenced", "source": {"issue": source}}],
            "demo/project",
        )
        self.assertEqual(result[0]["relation"], "solution_intent")
        self.assertFalse(result[0]["same_repository"])

    def test_same_number_in_foreign_repository_is_not_target(self):
        self.assertIsNone(
            solution_intent(pull(body="Fixes #42"), "demo/project", 42, False)
        )

    def test_quoted_fenced_and_negated_closing_keywords_are_not_intent(self):
        for body in [
            "> Fixes #42",
            "```md\nFixes #42\n```",
            "This does not fix #42",
            "This won't resolve #42",
            "Fixes #420",
            "Fixes other/project#42",
        ]:
            with self.subTest(body=body):
                self.assertIsNone(solution_intent(pull(body=body), "demo/project", 42))

    def test_keyword_case_colon_and_scoped_reference(self):
        for body in [
            "CLOSES: #42",
            "Resolves demo/project#42",
            "Fixed https://github.com/demo/project/issues/42",
        ]:
            with self.subTest(body=body):
                self.assertIsNotNone(
                    solution_intent(pull(body=body), "demo/project", 42)
                )

    def test_private_or_unknown_cross_repository_content_is_not_exported(self):
        for visibility in [True, None]:
            source = pull(
                html_url="https://github.com/secret/project/pull/99",
                pull_request={"url": "api"},
                repository={"private": visibility},
            )
            self.assertEqual(
                related_pulls(
                    issue(),
                    [],
                    [{"event": "cross-referenced", "source": {"issue": source}}],
                    "demo/project",
                ),
                [],
            )


class SourceClient(FakeGitHub):
    def __init__(self):
        self.calls = []

    def get(self, path, optional=False):
        self.calls.append(path)
        if "/branches/" in path:
            return {"commit": {"sha": SHA}}
        if "/contents/" in path:
            file = path.split("/contents/")[1].split("?")[0]
            if file == "missing.py":
                return None
            text = "def parse():\n    return 'verified source'\n"
            return {
                "type": "file",
                "path": file,
                "size": len(text),
                "encoding": "base64",
                "content": base64.b64encode(text.encode()).decode(),
            }
        return super().get(path, optional)


class SourceHintTests(unittest.TestCase):
    def test_reproduction_section_takes_priority_over_error_json(self):
        result = reproduction_excerpt(
            '### Error\n```json\n{"error": "bad request"}\n```\n'
            '### Reproduction\n```ts\nawait generateText({ prompt: "hi" });\n```'
        )
        self.assertEqual(result["language"], "ts")
        self.assertIn("generateText", result["text"])

    def test_markdown_headings_in_example_are_not_new_problem_sections(self):
        sections = problem_sections(
            '### Reproduction\n```python\n# Actual behavior\nprint("hi")\n```\n'
            "### Expected\nPrint hi"
        )
        self.assertEqual([s["label"] for s in sections], ["Reproduction", "Expected"])
        self.assertIn("# Actual behavior", sections[0]["text"])

    def test_file_opt_out_preserves_path_but_makes_no_file_requests(self):
        class Client(SourceClient):
            def get(self, path, optional=False):
                if "/issues/" in path:
                    return issue(body="`src/parser.py`")
                return super().get(path, optional)

        client = Client()
        candidate = research("demo/project#42", client=client, check_sources=False)[
            "candidates"
        ][0]
        self.assertEqual(candidate["source_hints"]["mentioned_count"], 1)
        self.assertIn("未启用", candidate["source_hints"]["unverified"][0]["reason"])
        self.assertTrue(
            any(s["kind"] == "locate_files" for s in candidate["action_plan"])
        )
        self.assertFalse(
            any("/contents/" in c or "/branches/" in c for c in client.calls)
        )

    def test_source_path_priority_avoids_policy_links_and_bare_duplicates(self):
        text = "https://github.com/demo/project/blob/main/CONTRIBUTING.md `parser.py` `src/parser.py` `Node.js` `docs/usage.md`"
        paths = mentioned_paths(text, "demo/project", "main")
        self.assertEqual(
            [p["path"] for p in paths],
            ["src/parser.py", "docs/usage.md", "CONTRIBUTING.md"],
        )

    def test_unsafe_and_foreign_url_paths_are_not_requested(self):
        text = "../../secret.py /etc/private.py https://github.com/foreign/repo/blob/main/src/foreign.py https://evil.test/private.py `src/parser.py`"
        self.assertEqual(
            mentioned_paths(text, "demo/project", "main"),
            [{"path": "src/parser.py", "line": None}],
        )

    def test_source_urls_pin_to_verified_default_branch_commit(self):
        client = SourceClient()
        inspector = SourceInspector(client, "demo/project", "main")
        result = inspector.inspect(
            issue(body="https://github.com/demo/project/blob/main/src/parser.py#L2")
        )
        self.assertEqual(len(result["files"]), 1)
        self.assertIn(SHA, result["files"][0]["url"])
        self.assertIn("verified source", result["files"][0]["excerpt"])
        self.assertTrue(any(f"?ref={SHA}" in path for path in client.calls))

    def test_missing_path_is_an_explicit_gap_not_a_fabricated_link(self):
        result = SourceInspector(SourceClient(), "demo/project", "main").inspect(
            issue(body="`missing.py`")
        )
        self.assertEqual(result["files"], [])
        self.assertIn("未确认为", result["unverified"][0]["reason"])

    def test_limits_are_global_and_repeated_files_are_cached(self):
        client = SourceClient()
        inspector = SourceInspector(client, "demo/project", "main", max_requests=1)
        first = inspector.inspect(issue(body="`one.py` `two.py` `three.py`"))
        second = inspector.inspect(issue(body="`one.py`"))
        self.assertEqual(len(first["files"]), 1)
        self.assertEqual(len(first["unverified"]), 2)
        self.assertEqual(len(second["files"]), 1)
        self.assertEqual(sum("/contents/" in path for path in client.calls), 1)

    def test_snapshot_failure_does_not_fall_back_to_unpinned_source(self):
        class Client(SourceClient):
            def get(self, path, optional=False):
                raise ResearchError("Unavailable")

        result = SourceInspector(Client(), "demo/project", "main").inspect(
            issue(body="`src/a.py`")
        )
        self.assertEqual(result["files"], [])
        self.assertIn("快照读取失败", result["unverified"][0]["reason"])

    def test_code_excerpt_is_preserved_as_unexecuted_material(self):
        result = reproduction_excerpt("Example:\n```sh\nrm -rf /anything\n```\n")
        self.assertIn("rm -rf", result["text"])
        self.assertIn("未执行", result["note"])

    def test_action_plan_references_only_collected_evidence(self):
        class Client(SourceClient):
            def get(self, path, optional=False):
                if "/issues/" in path:
                    return issue(
                        body="### Expected\nNo lost chunks\n\n`src/parser.py`\n```python\nparse(data)\n```\n"
                    )
                return super().get(path, optional)

        report = research("demo/project#42", client=Client())
        candidate = report["candidates"][0]
        allowed = (
            {source["id"] for source in candidate["sources"]}
            | {doc["id"] for doc in report["documents"]}
            | {finding["id"] for finding in report["policy"]["findings"]}
        )
        for step in candidate["action_plan"]:
            self.assertTrue(step["source_ids"])
            self.assertLessEqual(set(step["source_ids"]), allowed)
        self.assertTrue(
            any(step["kind"] == "inspect_files" for step in candidate["action_plan"])
        )
        self.assertFalse(report["coverage"]["source_code_checked"])
        self.assertFalse(report["coverage"]["policy_reviewed"])


class ExistingWorkTests(unittest.TestCase):
    def test_file_change_table_and_test_output_are_author_work_records(self):
        candidate = assess(
            issue(
                body="## 文件变更\n| src/parser.py | 新增检查 |\n## 验证结果\n```text\n12 tests OK\n```\n分支已备好。"
            ),
            [],
            [],
            [],
            "demo/project",
            ["Python"],
        )
        self.assertEqual(candidate["status"], "review")
        self.assertTrue(
            any(s.get("category") == "work_record" for s in candidate["sources"])
        )

    def test_implementation_and_verification_record_require_followup(self):
        candidate = assess(
            issue(body="## 实现内容\n已添加目录检查。\n## 验证结果\n本地校验通过。"),
            [],
            [],
            [],
            "demo/project",
            ["Python"],
        )
        self.assertEqual(candidate["status"], "review")
        self.assertIn("作者陈述", candidate["sources"][-1]["label"])
        self.assertIn("未经本工具验证", candidate["risks"][0])

    def test_empty_template_and_quoted_example_do_not_claim_existing_work(self):
        for body in [
            "## 实现内容\n_No response_\n## 验证结果\n_No response_",
            "```md\n## 实现内容\n已实现\n## 验证结果\n已验证\n```",
        ]:
            candidate = assess(issue(body=body), [], [], [], "demo/project", ["Python"])
            self.assertFalse(
                any(s.get("category") == "work_record" for s in candidate["sources"])
            )


if __name__ == "__main__":
    unittest.main()
