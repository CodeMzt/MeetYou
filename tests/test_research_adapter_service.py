from __future__ import annotations

import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from research_adapter import service


class ResearchAdapterServiceTests(unittest.TestCase):
    def tearDown(self) -> None:
        service.RUNS.clear()

    def test_fake_adapter_requires_token_and_returns_cited_report(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "MEETYOU_RESEARCH_ADAPTER_TOKEN": "adapter-token",
                "MEETYOU_RESEARCH_ADAPTER_FAKE": "true",
                "MEETYOU_RESEARCH_PROVIDER": "gpt_researcher",
            },
            clear=False,
        ):
            service.RUNS.clear()
            client = TestClient(service.app)
            self.addCleanup(client.close)

            unauthorized = client.post(
                "/v1/research/runs",
                json={"research_task_id": "rst_test", "topic": "adapter fake"},
            )
            self.assertEqual(unauthorized.status_code, 401)

            health = client.get("/health").json()
            self.assertTrue(health["ready"])
            created = client.post(
                "/v1/research/runs",
                headers={"Authorization": "Bearer adapter-token"},
                json={
                    "schema": "meetyou.research.adapter.run.v1",
                    "provider": "gpt_researcher",
                    "research_task_id": "rst_test",
                    "topic": "adapter fake",
                    "project_sources": [
                        {
                            "source_id": "src_1",
                            "title": "Adapter source",
                            "content": "Adapter fake evidence.",
                        }
                    ],
                },
            )
            self.assertEqual(created.status_code, 200)
            run_id = created.json()["run_id"]

            completed = created.json()
            deadline = time.monotonic() + 3
            while completed.get("status") == "running" and time.monotonic() < deadline:
                time.sleep(0.05)
                completed = client.get(
                    f"/v1/research/runs/{run_id}",
                    headers={"Authorization": "Bearer adapter-token"},
                ).json()

            self.assertEqual(completed["status"], "completed")
            self.assertEqual(completed["sources"][0]["title"], "Adapter source")
            self.assertIn("[1]", completed["report_markdown"])


if __name__ == "__main__":
    unittest.main()
