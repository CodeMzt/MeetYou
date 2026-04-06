import asyncio
import json
import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.tool_runtime.models import ToolCallResult
from tools.web_search import WebSearchTools


class _FakeContent:
    def __init__(self, text: str):
        self.type = "text"
        self.text = text


class _FakeResult:
    def __init__(self, text: str):
        self.content = [_FakeContent(text)]


class _FakeMCPManager:
    def __init__(self, responses: dict[str, list[str]] | None = None, tool_map: dict[str, str] | None = None):
        self.responses = responses or {}
        self.tool_map = tool_map or {}
        self.calls: list[tuple[str, dict]] = []

    async def call_mcp_tool(self, tool_name: str, arguments: dict):
        self.calls.append((tool_name, dict(arguments)))
        queue = self.responses.get(tool_name, [])
        if not queue:
            raise RuntimeError(f"unexpected tool call: {tool_name}")
        text = queue.pop(0)
        if text.startswith("RAISE:"):
            raise RuntimeError(text.split(":", 1)[1])
        return _FakeResult(text)


class WebSearchToolsTests(unittest.IsolatedAsyncioTestCase):
    async def test_search_web_uses_tavily_search_and_extract(self):
        manager = _FakeMCPManager(
            responses={
                "tavily-search": [
                    json.dumps(
                        {
                            "answer": "Short answer",
                            "results": [
                                {
                                    "title": "Source One",
                                    "url": "https://example.com/one",
                                    "content": "Snippet one",
                                },
                                {
                                    "title": "Source Two",
                                    "url": "https://example.com/two",
                                    "content": "Snippet two",
                                },
                            ],
                        }
                    )
                ],
                "tavily-extract": [
                    json.dumps(
                        {
                            "results": [
                                {
                                    "url": "https://example.com/one",
                                    "title": "Source One",
                                    "raw_content": "Full article one " * 30,
                                }
                            ]
                        }
                    ),
                    json.dumps(
                        {
                            "results": [
                                {
                                    "url": "https://example.com/two",
                                    "title": "Source Two",
                                    "raw_content": "Full article two " * 30,
                                }
                            ]
                        }
                    ),
                ],
            },
            tool_map={
                "tavily-search": "tavily_web",
                "tavily-extract": "tavily_web",
            },
        )
        activities: list[str] = []

        async def on_activity(phase, content, metadata=None):
            del content, metadata
            activities.append(phase)

        tools = WebSearchTools(manager)
        raw = await tools.search_web("latest example news", activity_callback=on_activity)
        payload = json.loads(raw)

        self.assertEqual(payload["search_backend"], "tavily")
        self.assertEqual(payload["topic"], "news")
        self.assertEqual(payload["sources"][0]["reader"], "tavily_extract")
        self.assertEqual(payload["sources"][0]["id"], 1)
        self.assertIn("Answer first", payload["citation_style"])
        self.assertEqual(manager.calls[0][0], "tavily-search")
        self.assertEqual(manager.calls[0][1]["max_results"], 5)
        self.assertEqual(manager.calls[0][1]["topic"], "news")
        self.assertEqual(manager.calls[1][0], "tavily-extract")
        self.assertIn("searching", activities)
        self.assertIn("reading_sources", activities)

    async def test_read_web_page_falls_back_to_playwright(self):
        manager = _FakeMCPManager(
            responses={
                "tavily-extract": [
                    json.dumps({"results": [{"url": "https://example.com/page", "title": "Example", "raw_content": ""}]})
                ],
                "browser_navigate": ["navigated"],
                "browser_snapshot": [
                    "### Page\n- Page URL: https://example.com/page\n- Page Title: Example Page\n### Snapshot\n```yaml\n- heading: Example Page\n- paragraph: Useful rendered content\n```"
                ],
            },
            tool_map={
                "tavily-extract": "tavily_web",
                "browser_navigate": "playwright_web",
                "browser_snapshot": "playwright_web",
            },
        )
        tools = WebSearchTools(manager)
        raw = await tools.read_web_page("https://example.com/page")
        payload = json.loads(raw)

        self.assertEqual(payload["source"]["reader"], "playwright_snapshot")
        self.assertEqual(manager.calls[0][0], "tavily-extract")
        self.assertEqual(manager.calls[1][0], "browser_navigate")
        self.assertEqual(manager.calls[2][0], "browser_snapshot")

    async def test_search_web_parses_human_readable_tavily_output(self):
        manager = _FakeMCPManager(
            responses={
                "tavily-search": [
                    "Answer: Human readable answer\n\n"
                    "Sources:\n"
                    "- Source One: https://example.com/one\n\n"
                    "Detailed Results:\n"
                    "\nTitle: Source One\n"
                    "URL: https://example.com/one\n"
                    "Content: Snippet one\n"
                    "Raw Content: Full article one"
                ],
                "tavily-extract": [
                    "Detailed Results:\n"
                    "\nTitle: Source One\n"
                    "URL: https://example.com/one\n"
                    "Content: Snippet one\n"
                    "Raw Content: Full article one"
                ],
            },
            tool_map={
                "tavily-search": "tavily_web",
                "tavily-extract": "tavily_web",
            },
        )
        tools = WebSearchTools(manager)

        raw = await tools.search_web("example query")
        payload = json.loads(raw)

        self.assertEqual(payload["summary_hint"], "Human readable answer")
        self.assertEqual(payload["sources"][0]["url"], "https://example.com/one")
        self.assertEqual(payload["sources"][0]["reader"], "tavily_extract")

    async def test_search_web_surfaces_backend_text_errors(self):
        manager = _FakeMCPManager(
            responses={"tavily-search": ["Tavily API error: Invalid API key"]},
            tool_map={"tavily-search": "tavily_web"},
        )
        tools = WebSearchTools(manager)

        result = await tools.search_web("example query")
        self.assertIsInstance(result, ToolCallResult)
        self.assertFalse(result.ok)
        self.assertIn("unavailable", result.error.message)
        self.assertEqual(result.error.details["backend_error"], "Tavily API error: Invalid API key")

    async def test_search_web_reports_unavailable_without_tavily(self):
        manager = _FakeMCPManager(tool_map={})
        tools = WebSearchTools(manager)

        result = await tools.search_web("who won")
        self.assertIsInstance(result, ToolCallResult)
        self.assertFalse(result.ok)
        self.assertIn("Tavily", result.error.message)

    async def test_search_web_rejects_direct_url_queries(self):
        manager = _FakeMCPManager(tool_map={"tavily-search": "tavily_web"})
        tools = WebSearchTools(manager)

        result = await tools.search_web("https://example.com")
        self.assertIsInstance(result, ToolCallResult)
        self.assertFalse(result.ok)
        self.assertIn("read_web_page", result.error.message)


if __name__ == "__main__":
    unittest.main()
