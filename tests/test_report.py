import unittest

from contrib_scout.report import code_block, demo_report, markdown


class ReportTests(unittest.TestCase):
    def test_reproduction_export_preserves_indentation_and_contains_nested_fences(self):
        report = demo_report()
        code = 'def example():\n    return "```"\n# literal example heading'
        report["candidates"][0]["reproduction"] = {
            "text": code,
            "language": "python",
            "note": "未执行",
            "truncated": False,
        }
        text = markdown(report)
        self.assertIn("````python\n" + code + "\n````", text)
        self.assertEqual(code_block("example", "python\n# injected")[0], "```")

    def test_mentions_export_separately_from_actionable_sources(self):
        report = demo_report()
        report["candidates"][0]["sources"].append(
            {
                "id": "mention-1",
                "label": "Validation example",
                "url": "https://github.com/demo/tool/pull/1",
                "excerpt": "Not a fix",
                "category": "mention",
            }
        )
        text = markdown(report)
        self.assertIn("普通引用（不作为占用或已解决的依据）：", text)
        self.assertIn("步骤来源 ID：", text)
        self.assertEqual(text.count("（mention-1）"), 1)

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
