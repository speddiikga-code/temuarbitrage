"""Layer 9: the quality judge.  Structural checks run on every output and can only fail it; a scoring judge (the
simulated one here, a model-based one later, as an adapter) gives the score.  A cheaper output that fails is
escalated to the next route on the plan's ladder, never accepted because it was cheap.
"""

from __future__ import annotations

import json

from .adapters import SimulatedJudge, Verdict
from .intent import Intent, RouteRequest, detect_language


def structural_problems(intent: Intent, request: RouteRequest, output: str) -> list[str]:
    problems: list[str] = []
    text = (output or "").strip()
    if not text:
        return ["empty output"]
    if intent.structured_output and intent.task_type == "extraction":
        candidate = text
        if candidate.startswith("```"):
            candidate = candidate.strip("`").split("\n", 1)[-1] if "\n" in candidate else ""
        try:
            json.loads(candidate)
        except (ValueError, TypeError):
            problems.append("extraction output is not valid JSON")
    if len(text) >= 40 and intent.answer_language in ("ko", "zh", "en"):
        seen = detect_language(text)
        if intent.task_type != "coding" and seen != intent.answer_language:
            problems.append(f"answer is in {seen}, not the requested {intent.answer_language}")
    if text.lower().startswith(("i cannot", "i can't", "as an ai")) and intent.task_type != "chat":
        problems.append("output refuses the task")
    return problems


class QualityJudge:
    """Combines the structural checks with a scoring judge. `judge.mode` must match the action mode."""

    def __init__(self, scorer: SimulatedJudge):
        self.scorer = scorer
        self.mode = scorer.mode
        self.name = scorer.name

    def judge(self, intent: Intent, request: RouteRequest, output: str, quality_min: float) -> Verdict:
        problems = structural_problems(intent, request, output)
        score, reference = self.scorer.score(intent.task_type, request.prompt, output)
        passed = not problems and score >= quality_min
        reasons = tuple(problems) + (() if score >= quality_min else (f"score {score:.2f} below threshold {quality_min:.2f}",))
        return Verdict(score, passed, f"structural+{self.scorer.name}", reasons, 0, self.scorer.name, reference)
