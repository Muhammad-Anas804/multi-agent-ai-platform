# tests/test_ceo_brain.py
"""
Unit tests for CEOBrain — no LLM calls, all mocked.
Run: pytest tests/ -v
"""
from __future__ import annotations
import pytest
from unittest.mock import MagicMock, patch
from langchain_core.messages import HumanMessage, AIMessage

from agents.ceo_brain import (
    CEOBrain, CEOResponse, RequestType,
    classify_request, parse_response, build_system_prompt,
)


# ─── classify_request ────────────────────────────────────────
class TestClassifyRequest:
    def test_new_idea_start(self):
        assert classify_request("Start an AI fitness startup") == RequestType.NEW_IDEA

    def test_new_idea_build(self):
        assert classify_request("Build a SaaS tool for lawyers") == RequestType.NEW_IDEA

    def test_roadmap(self):
        assert classify_request("Give me a 90-day roadmap") == RequestType.ROADMAP

    def test_decision(self):
        assert classify_request("Should I hire a CTO now?") == RequestType.DECISION

    def test_analysis(self):
        assert classify_request("Analyse the market for EV charging") == RequestType.ANALYSIS

    def test_general_conversation(self):
        assert classify_request("What time is it?") == RequestType.CONVERSATION


# ─── build_system_prompt ─────────────────────────────────────
class TestBuildSystemPrompt:
    def test_no_context(self):
        prompt = build_system_prompt()
        assert "CEO Agent" in prompt
        assert "LONG-TERM MEMORY" not in prompt

    def test_with_context(self):
        prompt = build_system_prompt("User wants to build a fitness app")
        assert "LONG-TERM MEMORY" in prompt
        assert "fitness app" in prompt

    def test_empty_context_ignored(self):
        prompt = build_system_prompt("   ")
        assert "LONG-TERM MEMORY" not in prompt


# ─── parse_response ──────────────────────────────────────────
SAMPLE_RESPONSE = """\
## IDEA ANALYSIS
Great market fit. AI fitness apps are growing 30% YoY.

## STRATEGIC RECOMMENDATION
GO — strong product-market fit with clear ICP.

## ROADMAP
Phase 1: MVP in 8 weeks.
Phase 2: 100 beta users.
Phase 3: Paid launch.

## IMMEDIATE ACTIONS
1. Validate with 10 interviews.
2. Build landing page.
3. Set up waitlist.

## KEY RISKS
1. High competition from incumbents.
2. User retention after month 1.
"""

class TestParseResponse:
    def test_all_sections_parsed(self):
        r = parse_response(SAMPLE_RESPONSE, RequestType.NEW_IDEA)
        assert r.idea_analysis     is not None
        assert r.recommendation    is not None
        assert r.roadmap           is not None
        assert r.immediate_actions is not None
        assert r.key_risks         is not None

    def test_verdict_extracted(self):
        r = parse_response(SAMPLE_RESPONSE, RequestType.NEW_IDEA)
        assert r.verdict == "GO"

    def test_no_go_verdict(self):
        raw = "## STRATEGIC RECOMMENDATION\nNO-GO — market too crowded."
        r   = parse_response(raw, RequestType.NEW_IDEA)
        assert r.verdict == "NO-GO"

    def test_pivot_verdict(self):
        raw = "## STRATEGIC RECOMMENDATION\nPIVOT — target enterprises instead."
        r   = parse_response(raw, RequestType.NEW_IDEA)
        assert r.verdict == "PIVOT"

    def test_missing_sections_are_none(self):
        r = parse_response("Just a plain response with no headers.", RequestType.CONVERSATION)
        assert r.idea_analysis is None
        assert r.roadmap       is None

    def test_has_sections_true(self):
        r = parse_response(SAMPLE_RESPONSE, RequestType.NEW_IDEA)
        assert r.has_sections() is True

    def test_has_sections_false(self):
        r = parse_response("No sections here.", RequestType.CONVERSATION)
        assert r.has_sections() is False

    def test_summary_format(self):
        r = parse_response(SAMPLE_RESPONSE, RequestType.NEW_IDEA)
        assert "new_idea" in r.summary()
        assert "GO"       in r.summary()


# ─── CEOBrain (mocked LLM) ───────────────────────────────────
class TestCEOBrain:
    @pytest.fixture
    def brain(self):
        with patch("agents.ceo_brain.ChatGroq") as MockGroq:
            mock_llm = MagicMock()
            mock_llm.invoke.return_value = MagicMock(content=SAMPLE_RESPONSE)
            MockGroq.return_value = mock_llm
            yield CEOBrain(api_key="test-key"), mock_llm

    def test_think_returns_ceo_response(self, brain):
        agent, _ = brain
        result = agent.think("Start an AI fitness startup")
        assert isinstance(result, CEOResponse)

    def test_think_calls_llm_once(self, brain):
        agent, mock_llm = brain
        agent.think("Build a SaaS tool")
        mock_llm.invoke.assert_called_once()

    def test_think_with_history(self, brain):
        agent, mock_llm = brain
        history = [HumanMessage(content="Hi"), AIMessage(content="Hello")]
        agent.think("Follow-up question", conversation_history=history)
        call_args = mock_llm.invoke.call_args[0][0]
        assert len(call_args) >= 3   # system + 2 history + 1 human

    def test_think_with_long_term_context(self, brain):
        agent, mock_llm = brain
        agent.think("New question", long_term_context="Past goal: fitness app")
        call_args = mock_llm.invoke.call_args[0][0]
        system_content = call_args[0].content
        assert "LONG-TERM MEMORY" in system_content

    def test_think_raises_on_llm_error(self):
        with patch("agents.ceo_brain.ChatGroq") as MockGroq:
            mock_llm = MagicMock()
            mock_llm.invoke.side_effect = Exception("API timeout")
            MockGroq.return_value = mock_llm
            agent = CEOBrain(api_key="test-key")
            with pytest.raises(RuntimeError, match="CEOBrain LLM failed"):
                agent.think("Start something")

    def test_repr(self, brain):
        agent, _ = brain
        assert "CEOBrain" in repr(agent)
        assert "llama3" in repr(agent)