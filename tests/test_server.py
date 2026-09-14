import json
import threading
import time
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch

from contrib_scout.report import demo_report, markdown
from contrib_scout.server import ScoutServer


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ScoutServer(("127.0.0.1", 0))
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def request(self, path, data=None, headers=None):
        req = Request(
            self.base + path,
            data=json.dumps(data).encode() if data is not None else None,
            headers=headers or {},
        )
        with urlopen(req, timeout=5) as response:
            return json.load(response)

    def test_demo_and_markdown_are_marked_fictional(self):
        data = self.request("/api/demo")
        self.assertTrue(data["report"]["demo"])
        self.assertIn("虚构", data["markdown"])

    def test_foreign_host_rejected(self):
        with self.assertRaises(HTTPError) as error:
            self.request("/api/config", headers={"Host": "evil.test"})
        self.assertEqual(error.exception.code, 403)
        error.exception.close()

    def test_post_without_token_rejected(self):
        with self.assertRaises(HTTPError) as error:
            self.request("/api/research", {"repo": "demo/project"})
        self.assertEqual(error.exception.code, 403)
        error.exception.close()

    def test_cross_origin_post_rejected(self):
        with self.assertRaises(HTTPError) as error:
            self.request(
                "/api/research",
                {"repo": "demo/project"},
                {"X-Scout-Token": self.server.csrf, "Origin": "https://evil.test"},
            )
        self.assertEqual(error.exception.code, 403)
        error.exception.close()

    def test_static_server_does_not_expose_source_or_env(self):
        for path in ["/.env", "/../server.py", "/api/not-found"]:
            with self.subTest(path=path), self.assertRaises(HTTPError) as error:
                self.request(path)
            self.assertEqual(error.exception.code, 404)
            error.exception.close()

    def test_async_job_completes_and_download_text_matches(self):
        with patch("contrib_scout.server.research", return_value=demo_report()):
            created = self.request(
                "/api/research",
                {"repo": "demo/project", "ai": False},
                {"X-Scout-Token": self.server.csrf},
            )
            for _ in range(50):
                job = self.request("/api/jobs/" + created["job_id"])
                if job["state"] != "running":
                    break
                time.sleep(0.01)
            self.assertEqual(job["state"], "complete")
            self.assertEqual(job["markdown"], markdown(job["report"]))
            with urlopen(
                self.base + "/api/jobs/" + created["job_id"] + "/report.md"
            ) as response:
                self.assertIn("attachment;", response.headers["Content-Disposition"])
                self.assertEqual(response.read().decode(), job["markdown"])
            with urlopen(
                self.base + "/api/jobs/" + created["job_id"] + "/report.json"
            ) as response:
                self.assertIn("attachment;", response.headers["Content-Disposition"])
                self.assertEqual(json.load(response), job["report"])

    def test_demo_download_has_attachment_header(self):
        with urlopen(self.base + "/api/demo.md") as response:
            self.assertIn("attachment;", response.headers["Content-Disposition"])
            self.assertIn("虚构", response.read().decode())

    def test_occupied_port_reports_os_error_without_masking_it(self):
        with self.assertRaises(OSError):
            ScoutServer(("127.0.0.1", self.server.server_port))

    def test_parameters_rejected_before_starting_a_job(self):
        for payload in [
            {"repo": "demo/project", "limit": True},
            {"repo": "demo/project", "limit": 9},
            {"repo": "demo/project", "stack": []},
        ]:
            before = len(self.server.jobs)
            with self.assertRaises(HTTPError) as error:
                self.request(
                    "/api/research", payload, {"X-Scout-Token": self.server.csrf}
                )
            self.assertEqual(error.exception.code, 400)
            error.exception.close()
            self.assertEqual(len(self.server.jobs), before)

    def test_json_demo_download_contains_report(self):
        with urlopen(self.base + "/api/demo.json") as response:
            self.assertTrue(json.load(response)["demo"])
            self.assertIn("attachment;", response.headers["Content-Disposition"])


if __name__ == "__main__":
    unittest.main()
