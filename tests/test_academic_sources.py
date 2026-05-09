from __future__ import annotations

import unittest

from tools.academic_sources import AcademicSourceRegistry


class AcademicSourceRegistryTests(unittest.TestCase):
    def test_builds_read_only_query_urls_and_evidence_ledger(self) -> None:
        payload = AcademicSourceRegistry.search_payload(
            "agent checkpointing",
            adapters=["arxiv", "openalex", "crossref", "semantic_scholar"],
            limit=3,
        )

        self.assertEqual(payload["schema"], "meetyou.academic_search.v1")
        self.assertEqual(payload["status"], "planned_queries")
        self.assertEqual([item["adapter"] for item in payload["adapters"]], ["arxiv", "openalex", "crossref", "semantic_scholar"])
        self.assertIn("agent+checkpointing", payload["adapters"][0]["query_url"])
        self.assertEqual(len(payload["evidence_ledger"]), 4)
        self.assertEqual(payload["evidence_ledger"][0]["verification_status"], "query_url")

    def test_ignores_unknown_adapters_and_bounds_limit(self) -> None:
        queries = AcademicSourceRegistry.build_queries(
            "large language models",
            adapters=["unknown", "arxiv"],
            limit=500,
        )

        self.assertEqual(len(queries), 1)
        self.assertEqual(queries[0].adapter, "arxiv")
        self.assertIn("max_results=50", queries[0].query_url)

    def test_empty_query_returns_no_sources(self) -> None:
        self.assertEqual(AcademicSourceRegistry.build_queries("   "), [])


if __name__ == "__main__":
    unittest.main()
