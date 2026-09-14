import unittest

from contrib_scout.github import ResearchError, parse_target
from contrib_scout.policy import collect_documents, excerpts
from contrib_scout.research import assess, research, stack_matches
from test_research import FakeGitHub, NOW, issue, pull


def document(text, path="CONTRIBUTING.md"):
    return {
        "id": "doc-1",
        "path": path,
        "url": "https://github.com/demo/project/blob/main/" + path,
        "text": text,
        "truncated": False,
    }


class TargetTests(unittest.TestCase):
    def test_issue_url_and_shorthand(self):
        for text in [
            "demo/project#42",
            "https://github.com/demo/project/issues/42/",
            "https://github.com/demo/project/issues/42#issuecomment-123",
        ]:
            with self.subTest(text=text):
                target = parse_target(text)
                self.assertEqual(
                    (target.repo, target.issue_number), ("demo/project", 42)
                )

    def test_repo_still_accepted(self):
        self.assertIsNone(
            parse_target("https://github.com/demo/project.git").issue_number
        )

    def test_wrong_target_types_and_hosts_are_rejected(self):
        for value in [
            None,
            42,
            "demo/project#0",
            "demo/project#-1",
            "demo/project#42/evil",
            "https://github.com/demo/project/pull/42",
            "https://github.com.evil.test/a/b/issues/1",
            "https://github.com/demo/project/issues/42?q=1",
            "https://github.com/demo/project/issues/42#bad",
        ]:
            with self.subTest(value=value), self.assertRaises(ResearchError):
                parse_target(value)

    def test_targeted_issue_bypasses_shortlist(self):
        class Client(FakeGitHub):
            def pages(self, path, max_pages=5):
                if "/issues?" in path:
                    raise AssertionError("Targeted research must not list issues")
                return [], False

        report = research("demo/project#42", client=Client())
        self.assertEqual(report["target"]["mode"], "issue")
        self.assertEqual(report["coverage"]["issues_scanned"], 1)
        self.assertEqual(report["candidates"][0]["number"], 42)

    def test_issue_endpoint_returning_a_pull_request_is_rejected(self):
        class Client(FakeGitHub):
            def get(self, path, optional=False):
                if "/issues/" in path:
                    return issue(pull_request={"url": "pr"})
                return super().get(path, optional)

        with self.assertRaisesRegex(ResearchError, "Pull Request"):
            research("demo/project#42", client=Client())

    def test_closed_issue_has_explicit_reason_and_state(self):
        class Client(FakeGitHub):
            def get(self, path, optional=False):
                if "/issues/" in path:
                    return issue(state="closed")
                return super().get(path, optional)

        candidate = research("demo/project#42", client=Client())["candidates"][0]
        self.assertEqual(candidate["status"], "skip")
        self.assertTrue(any("已关闭" in risk for risk in candidate["risks"]))

    def test_golang_does_not_match_unrelated_substrings(self):
        self.assertEqual(stack_matches("ongoing Django changes", ["Go"]), [])
        self.assertEqual(
            stack_matches("Go, Python and C++ examples", ["Go", "C++", "Java"]),
            ["Go", "C++"],
        )


class PolicyTests(unittest.TestCase):
    def test_quotes_have_real_line_numbers_and_categories(self):
        text = "# Rules\n\nPlease discuss changes before submitting a PR.\nDisclose AI assistance.\n"
        findings = excerpts([document(text)])
        self.assertEqual([item["line"] for item in findings], [3, 4])
        self.assertTrue(findings[0]["url"].endswith("#L3"))
        self.assertEqual(findings[0]["quote"], text.splitlines()[2])
        self.assertIn("AI 使用规则线索", findings[1]["categories"])

    def test_code_and_blockquotes_are_not_policy_findings(self):
        text = "```text\nNo AI contributions allowed.\n```\n> Assign this to me.\nGeneral introduction."
        self.assertEqual(excerpts([document(text)]), [])

    def test_product_ai_mentions_and_claim_filenames_are_not_rules(self):
        text = "AI programming assistant.\n把 AI 编程对话整理为证据链。\nRead claim-evidence-ledger.md for Claim scoring."
        self.assertEqual(excerpts([document(text, "README.md")]), [])

    def test_no_signal_is_not_approval(self):
        docs, policy, warnings = collect_documents(FakeGitHub(), "demo/project")
        self.assertEqual(policy["status"], "unreviewed")
        self.assertFalse(policy["contributing_found"])
        self.assertTrue(warnings)

    def test_public_shared_guideline_is_marked_as_fallback(self):
        class Client(FakeGitHub):
            def get(self, path, optional=False):
                if path.endswith("/.github"):
                    return {"private": False}
                return super().get(path, optional)

            def document(self, repo, path):
                if repo == "demo/.github" and path == "contents/CONTRIBUTING.md":
                    return document("Please claim an issue before starting.")

        docs, policy, _ = collect_documents(Client(), "demo/project")
        self.assertTrue(policy["contributing_found"])
        self.assertTrue(docs[0]["inherited"])
        self.assertEqual(docs[0]["repository"], "demo/.github")

    def test_private_shared_repository_is_never_read(self):
        class Client(FakeGitHub):
            def get(self, path, optional=False):
                return {"private": True}

            def document(self, repo, path):
                if repo == "demo/.github":
                    raise AssertionError("Must not read private shared rules")

        _, policy, _ = collect_documents(Client(), "demo/project")
        self.assertFalse(policy["contributing_found"])

    def test_shared_guidelines_without_keyword_still_need_scope_review(self):
        class Client(FakeGitHub):
            def get(self, path, optional=False):
                if path.endswith("/.github"):
                    return {"private": False}
                return super().get(path, optional)

            def document(self, repo, path):
                if repo == "demo/.github" and path == "contents/CONTRIBUTING.md":
                    return document("Test every change.")

        report = research("demo/project#42", client=Client())
        self.assertEqual(report["policy"]["findings"], [])
        candidate = report["candidates"][0]
        self.assertEqual(candidate["status"], "investigate")
        self.assertEqual(candidate["policy_check"]["status"], "unreviewed")
        self.assertTrue(any(doc["inherited"] for doc in report["documents"]))
        self.assertTrue(any("共享" in step for step in candidate["next_steps"]))

    def test_local_guidelines_take_precedence(self):
        class Client(FakeGitHub):
            def get(self, path, optional=False):
                raise AssertionError("No inherited lookup needed")

            def document(self, repo, path):
                if path == "contents/.github/CONTRIBUTING.md":
                    return document("Test every change.", ".github/CONTRIBUTING.md")

        docs, policy, _ = collect_documents(Client(), "demo/project")
        self.assertTrue(policy["contributing_found"])
        self.assertFalse(docs[0]["inherited"])

    def test_failed_policy_read_stays_visible_separate_from_occupancy(self):
        class Client(FakeGitHub):
            def document(self, repo, path):
                raise ResearchError("Temporarily unavailable")

        report = research("demo/project#42", client=Client())
        self.assertFalse(report["policy"]["documents_complete"])
        self.assertEqual(report["candidates"][0]["status"], "investigate")
        self.assertFalse(report["candidates"][0]["policy_check"]["documents_complete"])
        self.assertEqual(
            report["candidates"][0]["policy_check"]["status"], "unreviewed"
        )


class RelatedPullTests(unittest.TestCase):
    def test_closed_pull_merge_field_changes_assessment(self):
        result = assess(
            issue(),
            [pull(state="closed", merged_at="2026-09-12T00:00:00Z")],
            [],
            [],
            "demo/project",
            ["Python"],
            now=NOW,
        )
        self.assertEqual(result["status"], "review")
        self.assertEqual(result["related_prs"][0]["state"], "merged")

    def test_full_repo_shorthand_is_matched_case_insensitively(self):
        result = assess(
            issue(),
            [pull(title="An unrelated title", body="Fixes DEMO/PROJECT#42")],
            [],
            [],
            "demo/project",
            [],
            now=NOW,
        )
        self.assertEqual(result["status"], "hold")

    def test_recent_closed_pulls_are_collected(self):
        class Client(FakeGitHub):
            def pages(self, path, max_pages=5):
                if "/pulls?state=closed" in path:
                    return [
                        pull(state="closed", merged_at="2026-09-12T00:00:00Z")
                    ], False
                return super().pages(path, max_pages)

        report = research("demo/project#42", client=Client())
        self.assertEqual(report["coverage"]["closed_prs_scanned"], 1)
        self.assertEqual(report["candidates"][0]["related_prs"][0]["state"], "merged")

    def test_same_authors_later_withdrawal_clears_old_claim(self):
        comments = [
            {
                "id": 1,
                "body": "I'd like to work on this.",
                "user": {"login": "alice"},
                "html_url": "https://github.com/demo/project/issues/42#issuecomment-1",
            },
            {
                "id": 2,
                "body": "I'm no longer working on this.",
                "user": {"login": "alice"},
                "html_url": "https://github.com/demo/project/issues/42#issuecomment-2",
            },
        ]
        result = assess(issue(), [], [], comments, "demo/project", [], now=NOW)
        self.assertEqual(result["status"], "investigate")

    def test_another_authors_withdrawal_does_not_clear_claim(self):
        comments = [
            {
                "id": 1,
                "body": "I'd like to work on this.",
                "user": {"login": "alice"},
                "html_url": "https://github.com/demo/project/issues/42#issuecomment-1",
            },
            {
                "id": 2,
                "body": "Please unassign me.",
                "user": {"login": "bob"},
                "html_url": "https://github.com/demo/project/issues/42#issuecomment-2",
            },
        ]
        result = assess(issue(), [], [], comments, "demo/project", [], now=NOW)
        self.assertEqual(result["status"], "review")


if __name__ == "__main__":
    unittest.main()
