import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.semantic_router import KeywordFallbackAdapter, SemanticDecisionResult, SemanticRouterAgent


class _StubSemanticAdapter:
    adapter_name = "stub_semantic_adapter"

    def __init__(
        self,
        *,
        route_decision: SemanticDecisionResult,
        source_profile: str = "tech_updates",
        active_task_skill: bool = False,
        preload_context: bool = False,
        live_web: bool = False,
    ):
        self._route_decision = route_decision
        self._source_profile = source_profile
        self._active_task_skill = active_task_skill
        self._preload_context = preload_context
        self._live_web = live_web

    def analyze_route(self, request):
        del request
        return self._route_decision

    def classify_source_profile(self, text: str):
        del text
        return SemanticDecisionResult(
            value=self._source_profile,
            confidence="high",
            score=1.0,
            reason=f"Stub selected source profile {self._source_profile}.",
            signals=["stub_profile"],
            adapter_name=self.adapter_name,
        )

    def should_preload_context(self, query: str, goal: str = ""):
        del query, goal
        return SemanticDecisionResult(
            value=self._preload_context,
            confidence="high" if self._preload_context else "low",
            score=1.0 if self._preload_context else 0.0,
            reason="Stub context decision.",
            signals=["stub_context"] if self._preload_context else [],
            adapter_name=self.adapter_name,
        )

    def is_live_web_query(self, query: str):
        del query
        return SemanticDecisionResult(
            value=self._live_web,
            confidence="high" if self._live_web else "low",
            score=1.0 if self._live_web else 0.0,
            reason="Stub live-web decision.",
            signals=["stub_live_web"] if self._live_web else [],
            adapter_name=self.adapter_name,
        )

    def should_activate_skill(self, skill_name: str, content: str, *, mode: str = ""):
        del content, mode
        enabled = skill_name == "task_recognition" and self._active_task_skill
        return SemanticDecisionResult(
            value=enabled,
            confidence="high" if enabled else "low",
            score=1.0 if enabled else 0.0,
            reason="Stub skill decision.",
            signals=["stub_skill"] if enabled else [],
            adapter_name=self.adapter_name,
        )


class SemanticRouterAgentTests(unittest.TestCase):
    def test_prefers_high_confidence_semantic_adapter(self):
        adapter = _StubSemanticAdapter(
            route_decision=SemanticDecisionResult(
                value="research",
                confidence="high",
                score=0.95,
                reason="Stub selected retired research mode.",
                signals=["stub_research"],
                adapter_name="stub_semantic_adapter",
            ),
            source_profile="finance_macro",
            live_web=True,
        )
        agent = SemanticRouterAgent(route_adapters=[adapter], fallback_adapter=KeywordFallbackAdapter())

        result = agent.analyze("Create a research report about finance policy and cite official sources.")

        self.assertEqual(result.mode, "general")
        self.assertEqual(result.source_profile, "finance_macro")
        self.assertTrue(result.prefer_live_web)
        self.assertFalse(result.used_keyword_fallback)
        self.assertEqual(result.adapter_name, "stub_semantic_adapter")
        self.assertIn("Stub selected retired research mode.", result.reason)

    def test_uses_keyword_fallback_when_semantic_signal_is_low(self):
        adapter = _StubSemanticAdapter(
            route_decision=SemanticDecisionResult(
                value="general",
                confidence="low",
                score=0.05,
                reason="Stub had weak routing confidence.",
                signals=[],
                adapter_name="stub_semantic_adapter",
            )
        )
        agent = SemanticRouterAgent(route_adapters=[adapter], fallback_adapter=KeywordFallbackAdapter())

        result = agent.analyze("Analyze E:/demo/report.md and explain the repo directory tree.")

        self.assertEqual(result.mode, "general")
        self.assertTrue(result.used_keyword_fallback)
        self.assertIn("Keyword fallback selected general", result.reason)
        self.assertEqual(result.adapter_name, "keyword_fallback_adapter")

    def test_default_agent_routes_profiles_context_and_skills(self):
        agent = SemanticRouterAgent()

        result = agent.analyze(
            "Create a research report with citations and track source updates for OpenAI policy changes."
        )

        self.assertEqual(result.mode, "general")
        self.assertEqual(result.source_profile, "policy_global")
        self.assertIn("research_grounding", result.active_skills)
        self.assertFalse(result.used_keyword_fallback)
        self.assertTrue(agent.should_preload_context("What did we decide last time about the spec?"))
        self.assertTrue(agent.is_live_web_query("What changed today in https://docs.python.org?"))

    def test_default_agent_classifies_new_source_profiles(self):
        agent = SemanticRouterAgent()

        academic = agent.classify_source_profile("Summarize recent arXiv and IEEE papers about multimodal robotics.")
        engineering = agent.classify_source_profile("Track GitHub trending repos and embedded firmware releases for STM32 and ESP32.")
        world = agent.classify_source_profile("Compare Reuters, AP, and Xinhua coverage on current geopolitics and supply chain shifts.")
        frontier = agent.classify_source_profile("Review Hugging Face daily papers and MIT Technology Review analysis on edge AI.")

        self.assertEqual(academic, "academic_biomed")
        self.assertEqual(engineering, "tech_updates")
        self.assertEqual(world, "policy_global")
        self.assertEqual(frontier, "tech_updates")

    def test_evaluate_skill_activation_returns_reasoned_decision(self):
        agent = SemanticRouterAgent()

        decision = agent.evaluate_skill_activation(
            "knowledge_synthesis",
            "Please summarize these notes, organize the outline, and extract action items.",
            mode="automation",
        )

        self.assertTrue(decision.value)
        self.assertIn(decision.confidence, {"high", "medium"})
        self.assertTrue(decision.reason)


if __name__ == "__main__":
    unittest.main()
