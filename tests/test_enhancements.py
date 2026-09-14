import io
import json
import os
import unittest
from unittest.mock import patch

from contrib_scout.github import ResearchError
from contrib_scout.llm import enhance, estimated_cost, validate_analysis
from contrib_scout.report import markdown
from contrib_scout.research import research
from test_llm import analysis
from test_research import FakeGitHub


class NewReportTests(unittest.TestCase):
    def test_policy_quotes_and_target_are_exported(self):
        report = research("demo/project#42", client=FakeGitHub())
        report["policy"]["findings"] = [
            {
                "id": "policy-doc-1-3",
                "path": "CONTRIBUTING.md",
                "line": 3,
                "categories": ["讨论或审批线索"],
                "quote": "Discuss first.",
                "url": "https://github.com/demo/project/blob/main/CONTRIBUTING.md#L3",
            }
        ]
        text = markdown(report)
        self.assertIn("定向调研：Issue #42", text)
        self.assertIn("近期关闭 PR：0", text)
        self.assertIn("#L3", text)
        self.assertIn("Discuss first.", text)

    def test_policy_source_ids_can_ground_ai_analysis(self):
        report = research("demo/project#42", client=FakeGitHub())
        report["policy"]["findings"] = [{"id": "policy-doc-1-3"}]
        value = analysis()
        value["analyses"][0]["source_ids"].append("policy-doc-1-3")
        self.assertEqual(len(validate_analysis(value, report)[42]["source_ids"]), 2)

    @patch.dict(
        os.environ,
        {"SCOUT_INPUT_PRICE_PER_MILLION": "2", "SCOUT_OUTPUT_PRICE_PER_MILLION": "8"},
    )
    def test_missing_or_invalid_usage_does_not_become_zero_cost(self):
        for usage in [
            {},
            {"prompt_tokens": 1},
            {"prompt_tokens": -1, "completion_tokens": 2},
            {"prompt_tokens": True, "completion_tokens": 2},
        ]:
            self.assertIsNone(estimated_cost(usage))

    @patch.dict(
        os.environ,
        {
            "SCOUT_LLM_BASE_URL": "https://model.example/v1",
            "SCOUT_LLM_API_KEY": "test",
            "SCOUT_LLM_MODEL": "test",
        },
    )
    def test_truncated_model_response_does_not_mutate_candidates(self):
        report = research("demo/project#42", client=FakeGitHub())
        response = {
            "choices": [
                {
                    "finish_reason": "length",
                    "message": {"content": json.dumps(analysis())},
                }
            ]
        }
        with patch(
            "contrib_scout.llm.urlopen",
            return_value=io.BytesIO(json.dumps(response).encode()),
        ):
            with self.assertRaisesRegex(ResearchError, "截断"):
                enhance(report)
        self.assertIsNone(report["candidates"][0]["ai"])


if __name__ == "__main__":
    unittest.main()
