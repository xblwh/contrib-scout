import copy
import io
import json
import os
import unittest
from unittest.mock import patch

from contrib_scout.github import ResearchError
from contrib_scout.llm import enhance, estimated_cost, validate_analysis
from contrib_scout.research import research
from test_research import FakeGitHub


def analysis():
    return {
        "analyses": [
            {
                "issue_number": 42,
                "summary": "需要复现末尾 chunk 丢失。",
                "suggested_scope": "先确认流式读取边界。",
                "verification_plan": "添加覆盖结束信号的回归案例；尚未执行。",
                "source_ids": ["issue-42"],
            }
        ]
    }


class LLMTests(unittest.TestCase):
    def setUp(self):
        self.report = research("demo/project", client=FakeGitHub())

    def test_existing_citations_and_fields_accepted(self):
        value = analysis()
        value["analyses"][0]["status"] = "merged"
        validated = validate_analysis(value, self.report)
        self.assertNotIn("status", validated[42])
        self.assertEqual(self.report["candidates"][0]["state"], "open")

    def test_fabricated_source_rejected(self):
        value = analysis()
        value["analyses"][0]["source_ids"].append("made-up-source")
        with self.assertRaises(ResearchError):
            validate_analysis(value, self.report)

    def test_other_candidates_evidence_not_allowed(self):
        self.report["candidates"].append(
            {
                **copy.deepcopy(self.report["candidates"][0]),
                "number": 43,
                "sources": [{"id": "issue-43"}],
            }
        )
        value = analysis()
        value["analyses"][0]["source_ids"].append("issue-43")
        with self.assertRaises(ResearchError):
            validate_analysis(value, self.report)

    def test_missing_duplicate_and_unknown_issues_rejected(self):
        for value in [
            {"analyses": []},
            {"analyses": analysis()["analyses"] * 2},
            {"analyses": [{**analysis()["analyses"][0], "issue_number": 999}]},
        ]:
            with self.subTest(value=value), self.assertRaises(ResearchError):
                validate_analysis(value, self.report)

    def test_missing_issue_citation_rejected(self):
        self.report["documents"] = [{"id": "doc-1"}]
        value = analysis()
        value["analyses"][0]["source_ids"] = ["doc-1"]
        with self.assertRaises(ResearchError):
            validate_analysis(value, self.report)

    def test_malformed_fields_rejected(self):
        for field, invalid in [
            ("summary", []),
            ("source_ids", [None]),
            ("verification_plan", ""),
            ("issue_number", True),
        ]:
            value = analysis()
            value["analyses"][0][field] = invalid
            with self.subTest(field=field), self.assertRaises(ResearchError):
                validate_analysis(value, self.report)

    @patch.dict(
        os.environ,
        {
            "SCOUT_LLM_BASE_URL": "https://model.example/v1",
            "SCOUT_LLM_API_KEY": "test-key",
            "SCOUT_LLM_MODEL": "test-model",
        },
    )
    def test_mocked_model_request_preserves_facts_and_records_usage(self):
        before = copy.deepcopy(self.report["candidates"][0])
        response = {
            "choices": [{"message": {"content": json.dumps(analysis())}}],
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 50,
                "total_tokens": 150,
            },
        }
        with patch(
            "contrib_scout.llm.urlopen",
            return_value=io.BytesIO(json.dumps(response).encode()),
        ) as mocked:
            enhance(self.report)
            request = mocked.call_args.args[0]
            self.assertEqual(
                request.full_url, "https://model.example/v1/chat/completions"
            )
            self.assertEqual(
                json.loads(request.data)["response_format"], {"type": "json_object"}
            )
        actual = {**self.report["candidates"][0], "ai": None}
        self.assertEqual(actual, before)
        self.assertEqual(self.report["ai"]["usage"]["total_tokens"], 150)

    @patch.dict(os.environ, {}, clear=True)
    def test_missing_config_and_prices_are_explicit(self):
        with self.assertRaises(ResearchError):
            enhance(self.report)
        self.assertIsNone(estimated_cost({"prompt_tokens": 100}))

    @patch.dict(
        os.environ,
        {"SCOUT_INPUT_PRICE_PER_MILLION": "2", "SCOUT_OUTPUT_PRICE_PER_MILLION": "8"},
    )
    def test_cost_uses_user_prices(self):
        self.assertEqual(
            estimated_cost({"prompt_tokens": 1_000_000, "completion_tokens": 500_000}),
            6,
        )


if __name__ == "__main__":
    unittest.main()
