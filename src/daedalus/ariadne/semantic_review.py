"""
Ariadne Semantic Review

Causal-slice verification (verification.py) only checks mechanical
correctness: does the diff type-check, lint clean, and pass tests. It has no
opinion on whether the diff actually implements what was asked -- a
confidently wrong implementation (right syntax, wrong business logic, or a
misreading of ambiguous instructions) passes that gate just fine.

This module adds the missing check: given a diff and the intent behind it
(the work package / feature request description it was meant to satisfy),
does it actually do that? Deliberately kept separate from
CausalSliceVerifier -- conflating "is this mechanically safe" with "is this
the right solution" would make the fast, deterministic mechanical gate slower
and fuzzier at the one job it does well.

Two tiers, matching how the orchestrator gates on autonomy mode:
1. LLMJudge: a fast default gate -- one model call reviews the diff against
   its stated intent and returns an explicit verdict + reasoning.
2. Human review: anything the judge flags (or that autonomy policy routes
   there regardless) waits in AriadneBus's NEEDS_REVIEW bucket. Resolving it
   is meant to happen conversationally -- the spawning agent (Daedalus)
   surfaces the diff, states its own read of it, gives a recommendation, and
   the human's answer drives bus.approve_review()/reject_review(). There is
   deliberately no UI built here for that; it's a conversation, not a form.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, Protocol

from .diff_bus import Diff
from .verification import VerificationResult

try:
    from claude_agent_sdk import query
    from claude_agent_sdk.types import ClaudeAgentOptions
    HAS_AGENT_SDK = True
except ImportError:
    HAS_AGENT_SDK = False
    query = None
    ClaudeAgentOptions = None


class ReviewVerdict(str, Enum):
    """Outcome of a semantic review."""
    APPROVED = "approved"          # Diff correctly implements its stated intent
    NEEDS_HUMAN = "needs_human"    # Judge is unsure, unavailable, or policy requires a human
    REJECTED = "rejected"          # Diff does not implement its stated intent


@dataclass
class SemanticReviewResult:
    """Result of a semantic review -- the judge's (or human's) take."""
    diff_id: str
    verdict: ReviewVerdict
    reasoning: str
    reviewer: str  # "llm-judge" or a human identifier
    reviewed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        return {
            "diff_id": self.diff_id,
            "verdict": self.verdict.value,
            "reasoning": self.reasoning,
            "reviewer": self.reviewer,
            "reviewed_at": self.reviewed_at,
        }


class SemanticReviewer(Protocol):
    """
    Interface for anything that can render a semantic verdict on a diff.

    Implementations must fail closed: if a verdict can't be determined
    confidently, return NEEDS_HUMAN, never APPROVED. Silent approval is the
    one failure mode this whole module exists to prevent.
    """

    def review(
        self,
        diff: Diff,
        intent: str,
        verification: Optional[VerificationResult] = None,
    ) -> SemanticReviewResult:
        ...


_REVIEW_PROMPT_TEMPLATE = """\
You are reviewing a code change for correctness against its stated intent.
You are NOT checking syntax, types, or whether tests pass -- that has
already been verified separately. Only judge whether the diff actually does
what it claims to do, completely and correctly.

## Stated intent
{intent}

## Diff
```diff
{diff_content}
```

## Mechanical verification
{verification_summary}

Respond with exactly one verdict line first (APPROVE, REJECT, or ESCALATE),
then a short explanation of your reasoning. Use ESCALATE if the intent is
ambiguous, the diff is too large/unclear to judge confidently, or you are
not sure. Do not guess APPROVE when uncertain.
"""


def _verification_summary(verification: Optional[VerificationResult]) -> str:
    if verification is None:
        return "(not available)"
    return (
        f"typecheck={'pass' if verification.typecheck_passed else 'fail'}, "
        f"lint={'pass' if verification.lint_passed else 'fail'}, "
        f"tests={'pass' if verification.tests_passed else 'fail'} "
        f"({verification.tests_run} run, {verification.tests_failed} failed)"
    )


def _parse_verdict(response_text: str) -> ReviewVerdict:
    first_line = response_text.strip().splitlines()[0].strip().upper() if response_text.strip() else ""
    if first_line.startswith("APPROVE"):
        return ReviewVerdict.APPROVED
    if first_line.startswith("REJECT"):
        return ReviewVerdict.REJECTED
    # ESCALATE, empty, or anything unrecognized -- fail closed.
    return ReviewVerdict.NEEDS_HUMAN


class LLMJudge:
    """
    Default SemanticReviewer: a single model call judges the diff against its
    stated intent.

    Deliberately minimal and headless -- this is a one-shot classification
    call, not an agentic session. It must never take actions or use tools;
    it only reads the diff and renders a verdict.
    """

    def __init__(self, model: Optional[str] = None):
        self.model = model

    def review(
        self,
        diff: Diff,
        intent: str,
        verification: Optional[VerificationResult] = None,
    ) -> SemanticReviewResult:
        if not HAS_AGENT_SDK:
            return SemanticReviewResult(
                diff_id=diff.id,
                verdict=ReviewVerdict.NEEDS_HUMAN,
                reasoning="claude-agent-sdk not installed; cannot run the LLM judge. "
                          "Routed to human review rather than approved unverified.",
                reviewer="llm-judge",
            )

        prompt = _REVIEW_PROMPT_TEMPLATE.format(
            intent=intent or "(no stated intent provided)",
            diff_content=diff.content,
            verification_summary=_verification_summary(verification),
        )

        try:
            response_text = self._run_query(prompt)
        except Exception as e:
            return SemanticReviewResult(
                diff_id=diff.id,
                verdict=ReviewVerdict.NEEDS_HUMAN,
                reasoning=f"LLM judge call failed ({e}); routed to human review rather than "
                          "approved unverified.",
                reviewer="llm-judge",
            )

        return SemanticReviewResult(
            diff_id=diff.id,
            verdict=_parse_verdict(response_text),
            reasoning=response_text.strip(),
            reviewer="llm-judge",
        )

    def _run_query(self, prompt: str) -> str:
        """
        Run a single headless, tool-free query and return its text output.

        Separated out so tests (and future alternative transports) can stub
        just this method rather than the whole review() flow.
        """
        import asyncio

        async def _collect() -> str:
            options = ClaudeAgentOptions(
                allowed_tools=[],
                model=self.model,
            ) if self.model else ClaudeAgentOptions(allowed_tools=[])

            chunks = []
            async for message in query(prompt=prompt, options=options):
                text = getattr(message, "text", None) or str(message)
                chunks.append(text)
            return "\n".join(chunks)

        return asyncio.run(_collect())
