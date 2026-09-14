from datetime import datetime, timezone
import unittest

from contrib_scout.github import GitHub, ResearchError, parse_repo
from contrib_scout.research import assess, research

NOW = datetime(2026, 9, 14, tzinfo=timezone.utc)


def issue(**changes):
    return {
        "number": 42,
        "title": "Python streaming parser loses final chunk",
        "body": "Python example: the final chunk is missing.",
        "html_url": "https://github.com/demo/project/issues/42",
        "state": "open",
        "labels": [{"name": "good first issue"}],
        "assignees": [],
        "created_at": "2026-09-01T00:00:00Z",
        "updated_at": "2026-09-13T00:00:00Z",
        **changes,
    }


def pull(**changes):
    return {
        "number": 99,
        "title": "Preserve Python streaming parser final chunk",
        "body": "Fixes #42",
        "state": "open",
        "html_url": "https://github.com/demo/project/pull/99",
        **changes,
    }


class FakeGitHub:
    requests = 0

    def get(self, path, optional=False):
        if path.endswith("/.github"):
            return None
        if "/issues/" in path:
            return issue()
        return {
            "full_name": "demo/project",
            "html_url": "https://github.com/demo/project",
            "private": False,
            "default_branch": "main",
            "archived": False,
            "license": {"spdx_id": "MIT"},
        }

    def document(self, repo, path):
        return None

    def pages(self, path, max_pages=5):
        if "/pulls?" in path:
            return [], False
        if "/issues?" in path:
            return [issue(), issue(number=10, pull_request={"url": "pr"})], True
        return [], False


class ResearchTests(unittest.TestCase):
    def assess(self, item=None, pulls=None, timeline=None, comments=None, **kw):
        return assess(
            item or issue(),
            pulls or [],
            timeline or [],
            comments or [],
            "demo/project",
            ["Python"],
            now=NOW,
            **kw,
        )

    def test_repo_normalization(self):
        self.assertEqual(
            parse_repo("https://github.com/pydantic/pydantic-ai.git/"),
            "pydantic/pydantic-ai",
        )

    def test_only_repo_urls_accepted(self):
        for value in [
            "https://evil.test/o/r",
            "https://github.com/a/b/issues/1",
            "a/..",
            "a/b?x=1",
            "--help",
            "https://user@github.com/a/b",
            "http://127.0.0.1/a/b",
        ]:
            with self.subTest(value=value), self.assertRaises(ResearchError):
                parse_repo(value)

    def test_cross_repository_timeline_reference_needs_comparison(self):
        source = {
            "number": 99,
            "title": "Alternative implementation",
            "state": "open",
            "html_url": "https://github.com/other/project/pull/99",
            "pull_request": {},
        }
        result = self.assess(
            timeline=[
                {
                    "event": "cross-referenced",
                    "source": {"issue": {**source, "pull_request": {"url": "api"}}},
                }
            ]
        )
        self.assertEqual(result["status"], "review")
        self.assertEqual(result["related_prs"][0]["kind"], "timeline")

    def test_explicit_reference_blocks_even_with_different_title(self):
        result = self.assess(pulls=[pull(title="Fix buffer handling")])
        self.assertEqual(result["status"], "hold")

    def test_foreign_repo_shorthand_is_not_same_issue(self):
        result = self.assess(
            pulls=[pull(title="Entirely unrelated", body="Fixes other/project#42")]
        )
        self.assertEqual(result["status"], "investigate")

    def test_issue_number_boundary(self):
        result = self.assess(
            pulls=[pull(title="Entirely unrelated", body="Fixes #420")]
        )
        self.assertEqual(result["related_prs"], [])

    def test_similarity_is_a_lead_not_confirmed_duplicate(self):
        result = self.assess(pulls=[pull(body="")])
        self.assertEqual(result["status"], "review")
        self.assertEqual(result["related_prs"][0]["kind"], "similarity")

    def test_assigned_issue_on_hold(self):
        self.assertEqual(
            self.assess(issue(assignees=[{"login": "alice"}]))["status"], "hold"
        )

    def test_claim_comment_creates_cited_risk(self):
        result = self.assess(
            comments=[
                {
                    "id": 3,
                    "body": "I'd like to work on this issue.",
                    "html_url": "https://github.com/demo/project/issues/42#issuecomment-3",
                }
            ]
        )
        self.assertEqual(result["status"], "review")
        self.assertEqual(result["sources"][1]["id"], "claim-3")

    def test_withdrawn_claim_not_treated_as_current(self):
        result = self.assess(
            comments=[
                {
                    "id": 3,
                    "body": "I'm no longer working on this. Please unassign me.",
                    "html_url": "https://github.com/demo/project/issues/42#issuecomment-3",
                }
            ]
        )
        self.assertEqual(result["status"], "investigate")

    def test_closed_unmerged_pull_is_not_open_blocker(self):
        result = self.assess(pulls=[pull(state="closed")])
        self.assertEqual(result["status"], "investigate")
        self.assertEqual(result["related_prs"][0]["state"], "closed")

    def test_merged_related_pull_requires_check(self):
        result = self.assess(
            timeline=[
                {
                    "event": "cross-referenced",
                    "source": {
                        "issue": {
                            "number": 99,
                            "title": "Fix this",
                            "state": "closed",
                            "html_url": "https://github.com/demo/project/pull/99",
                            "pull_request": {"merged_at": "2026-09-13T00:00:00Z"},
                        }
                    },
                }
            ]
        )
        self.assertEqual(result["status"], "review")

    def test_incomplete_duplicate_scan_never_looks_clear(self):
        self.assertEqual(self.assess(incomplete=True)["status"], "review")

    def test_archived_and_closed_candidates_are_skipped(self):
        self.assertEqual(self.assess(archived=True)["status"], "skip")
        self.assertEqual(self.assess(issue(state="closed"))["status"], "skip")

    def test_stale_issue_not_presented_as_fresh(self):
        self.assertEqual(
            self.assess(issue(updated_at="2024-01-01T00:00:00Z"))["status"], "review"
        )

    def test_issues_endpoint_filters_pull_requests_and_discloses_window(self):
        report = research("demo/project", client=FakeGitHub())
        self.assertEqual(report["coverage"]["issues_scanned"], 1)
        self.assertEqual(len(report["candidates"]), 1)
        self.assertFalse(report["coverage"]["issue_window_complete"])
        self.assertFalse(report["coverage"]["source_code_checked"])
        self.assertTrue(
            any("CONTRIBUTING" in message for message in report["warnings"])
        )

    def test_comment_failure_preserves_report_and_marks_gap(self):
        class BrokenComments(FakeGitHub):
            def pages(self, path, max_pages=5):
                if path.endswith("/comments"):
                    raise ResearchError("测试网络失败")
                return super().pages(path, max_pages)

        report = research("demo/project", client=BrokenComments())
        self.assertEqual(report["candidates"][0]["status"], "review")
        self.assertTrue(any("comments" in message for message in report["warnings"]))

    def test_pagination_stops_after_short_page(self):
        client = GitHub()
        calls = []

        def get(path):
            calls.append(path)
            return list(range(100)) if "&page=1" in path else [101]

        client.get = get
        items, capped = client.pages("repos/a/b/pulls?state=open")
        self.assertEqual(len(items), 101)
        self.assertFalse(capped)
        self.assertEqual(len(calls), 2)

    def test_full_page_at_cap_is_conservatively_incomplete(self):
        client = GitHub()
        client.get = lambda path: list(range(100))
        _, capped = client.pages("repos/a/b/pulls", max_pages=1)
        self.assertTrue(capped)

    def test_private_repository_rejected_before_data_collection(self):
        client = FakeGitHub()
        client.get = lambda path: {"private": True}
        with self.assertRaises(ResearchError):
            research("demo/project", client=client)

    def test_limit_type_and_range(self):
        for limit in [0, 9, True, "3"]:
            with self.subTest(limit=limit), self.assertRaises(ResearchError):
                research("demo/project", limit=limit, client=FakeGitHub())


if __name__ == "__main__":
    unittest.main()
