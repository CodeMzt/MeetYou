import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.authoritative_sources import AuthoritativeSourceRegistry


class _ModeManager:
    def resolve_source_auth_entries(self, source_config):
        del source_config
        return []


class _WebTools:
    pass


class _StubRegistry(AuthoritativeSourceRegistry):
    def __init__(self, payload: str):
        super().__init__(_ModeManager(), _WebTools())
        self.payload = payload
        self.last_url = ""
        self.last_params = None

    async def _get_text(self, url: str, *, params=None, headers=None) -> str:
        del headers
        self.last_url = url
        self.last_params = dict(params or {})
        return self.payload


class AuthoritativeSourceRegistryTests(unittest.IsolatedAsyncioTestCase):
    async def test_rss_atom_feed_parses_atom_query_results(self):
        registry = _StubRegistry(
            """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>Robotics Foundation Models</title>
    <summary>Multimodal planning for embodied agents.</summary>
    <published>2026-04-01T12:00:00Z</published>
    <link rel="alternate" href="https://arxiv.org/abs/2604.00001v1" />
  </entry>
</feed>"""
        )
        source_config = {
            "request_defaults": {
                "endpoint": "https://export.arxiv.org/api/query",
                "query_mode": "query_param",
                "query_param": "search_query",
                "query_prefix": "all:",
                "static_params": {
                    "start": 0,
                    "max_results": 5,
                },
            }
        }

        results = await registry._search_rss_atom_feed(source_config, "robotics", limit=2)

        self.assertEqual(registry.last_url, "https://export.arxiv.org/api/query")
        self.assertEqual(registry.last_params["search_query"], "all:robotics")
        self.assertEqual(results[0]["title"], "Robotics Foundation Models")
        self.assertEqual(results[0]["url"], "https://arxiv.org/abs/2604.00001v1")
        self.assertEqual(results[0]["published_date"], "2026-04-01T12:00:00Z")

    async def test_rss_atom_feed_filters_fixed_feed_and_handles_missing_fields(self):
        registry = _StubRegistry(
            """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <item>
      <title>STM32 power tuning guide</title>
    </item>
    <item>
      <title>General software essay</title>
      <description>Not relevant to firmware.</description>
      <link>https://example.com/post</link>
    </item>
  </channel>
</rss>"""
        )
        source_config = {
            "request_defaults": {
                "endpoint": "https://hackaday.com/blog/feed/",
                "query_mode": "fixed_feed",
            }
        }

        results = await registry._search_rss_atom_feed(source_config, "stm32", limit=5)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["title"], "STM32 power tuning guide")
        self.assertEqual(results[0]["url"], "")
        self.assertEqual(results[0]["summary"], "")


if __name__ == "__main__":
    unittest.main()
