import unittest

from contrib_scout.report import demo_report, markdown


class ReportTests(unittest.TestCase):
    def test_untrusted_titles_cannot_inject_markdown_links_or_html(self):
        report = demo_report()
        report["candidates"][0]["title"] = (
            "[Click](javascript:alert(1)) <script>alert(1)</script>\n# Fake finding"
        )
        text = markdown(report)
        self.assertNotIn("[Click](javascript:", text)
        self.assertNotIn("<script>", text)
        self.assertNotIn("\n# Fake finding", text)
        self.assertIn("\\[Click\\]", text)

    def test_ai_failure_still_exports_collected_evidence(self):
        report = demo_report()
        report["ai"] = {"enabled": False, "error": "模型服务不可用"}
        text = markdown(report)
        self.assertIn("AI 分析失败：模型服务不可用", text)
        self.assertIn("issue-42", text)
        self.assertIn("虚构", text)


if __name__ == "__main__":
    unittest.main()
