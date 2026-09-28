"""Layers 2 to 4: intent compiler, semantic compressor and language router.  All deterministic, no model call.

The compiler turns a raw request into a structured task (type, languages, token estimates, capabilities); the
compressor removes what the task does not need from the *context* (never from the prompt) and reports what it did;
the language router says in which language the work should run and which the answer must come back in.  Token
counts are estimates from character counts per script and say so: a provider's usage record is the only true count.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from ..errors import OpsError
from ..mandate import TASK_TYPES

OPTIMIZATIONS = ("economy", "balanced", "maximum")

# Characters per token, by script, from public tokenizer behaviour on typical text; estimates only.
CHARS_PER_TOKEN = {"latin": 4.0, "hangul": 1.6, "cjk": 1.1, "other": 3.0}
TOKEN_ESTIMATE_NOTE = "token counts are estimates from character counts; the provider's usage record is the true count"

_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("translation", ("translate", "translation", "번역", "翻訳", "翻译", "into korean", "into english", "영어로", "한국어로")),
    ("extraction", ("extract", "extraction", "추출", "as json", "json", "fields", "parse", "pull out")),
    ("classification", ("classify", "classification", "분류", "label", "categorize", "categorise", "sentiment", "which category")),
    ("summarization", ("summarize", "summarise", "summary", "요약", "tl;dr", "tldr", "key points", "condense")),
    ("coding", ("code", "function", "bug", "refactor", "python", "javascript", "typescript", "sql", "compile", "unit test",
                "코드", "함수", "버그", "```")),
    ("research", ("research", "compare sources", "literature", "survey", "조사", "find sources", "cite")),
    ("reasoning", ("prove", "reason", "step by step", "why does", "derive", "solve", "논리", "증명", "puzzle")),
    ("image_analysis", ("image", "photo", "picture", "screenshot", "이미지", "사진")),
)
_DECOMPOSABLE = frozenset({"extraction", "classification", "summarization", "translation", "research"})
_STRUCTURED = frozenset({"extraction", "classification"})


@dataclass(frozen=True)
class RouteRequest:
    """What a customer sends once (Layer 1). `cost_cap_krw` is the customer's cap on provider cost for this request."""

    idempotency_key: str
    customer_id: str
    prompt: str
    context: str = ""
    task_type: str | None = None          # declared; compiled from the prompt when absent
    optimization: str = "economy"
    quality_min: float = 0.7              # 0..1
    latency_max_ms: int | None = None
    cost_cap_krw: int = 0
    language: str | None = None           # answer language; detected from the prompt when absent
    max_output_tokens: int = 1024
    baseline_catalog_id: str | None = None   # the route the customer would have used; savings are measured against it
    metadata: dict = field(default_factory=dict)

    def validate(self) -> None:
        if not self.idempotency_key or not self.customer_id:
            raise OpsError("a route request needs an idempotency key and a customer")
        if not self.prompt or not self.prompt.strip():
            raise OpsError("a route request needs a prompt")
        if self.task_type is not None and self.task_type not in TASK_TYPES:
            raise OpsError(f"task_type must be one of {TASK_TYPES}, not {self.task_type!r}")
        if self.optimization not in OPTIMIZATIONS:
            raise OpsError(f"optimization must be one of {OPTIMIZATIONS}")
        if not 0 <= self.quality_min <= 1:
            raise OpsError("quality_min must be between 0 and 1")
        if isinstance(self.cost_cap_krw, bool) or not isinstance(self.cost_cap_krw, int) or self.cost_cap_krw <= 0:
            raise OpsError("cost_cap_krw must be a positive integer number of KRW; a request without a cap gets no route")
        if self.max_output_tokens <= 0:
            raise OpsError("max_output_tokens must be positive")
        if self.latency_max_ms is not None and self.latency_max_ms <= 0:
            raise OpsError("latency_max_ms must be positive when given")


@dataclass(frozen=True)
class Intent:
    task_type: str
    input_language: str
    answer_language: str
    prompt_tokens: int
    context_tokens: int
    capabilities: tuple[str, ...]        # e.g. ("structured_output", "long_context", "vision")
    structured_output: bool
    decomposable: bool
    declared: bool                       # the customer named the task type
    notes: tuple[str, ...] = ()

    @property
    def input_tokens(self) -> int:
        return self.prompt_tokens + self.context_tokens

    def as_dict(self) -> dict:
        return {"task_type": self.task_type, "input_language": self.input_language, "answer_language": self.answer_language,
                "prompt_tokens": self.prompt_tokens, "context_tokens": self.context_tokens, "capabilities": list(self.capabilities),
                "structured_output": self.structured_output, "decomposable": self.decomposable, "declared": self.declared,
                "notes": list(self.notes)}


# -- scripts and tokens ------------------------------------------------------------------------------------

def _script(ch: str) -> str:
    o = ord(ch)
    if 0xAC00 <= o <= 0xD7A3 or 0x1100 <= o <= 0x11FF or 0x3130 <= o <= 0x318F:
        return "hangul"
    if 0x4E00 <= o <= 0x9FFF or 0x3040 <= o <= 0x30FF or 0x3400 <= o <= 0x4DBF:
        return "cjk"
    if ch.isascii() and (ch.isalnum() or ch in " .,;:!?'\"()-_/\\[]{}<>=+*&%$#@^~`|"):
        return "latin"
    return "other"


def script_shares(text: str) -> dict[str, float]:
    counts = {"latin": 0, "hangul": 0, "cjk": 0, "other": 0}
    letters = 0
    for ch in text:
        if ch.isspace():
            continue
        counts[_script(ch)] += 1
        letters += 1
    return {k: (v / letters if letters else 0.0) for k, v in counts.items()}


def estimate_tokens(text: str) -> int:
    """Characters divided by the per-script ratio; an estimate, never a bill."""
    if not text:
        return 0
    total = 0.0
    for ch in text:
        if ch.isspace():
            total += 0.25
        else:
            total += 1.0 / CHARS_PER_TOKEN[_script(ch)]
    return max(1, round(total))


def detect_language(text: str) -> str:
    shares = script_shares(text)
    if shares["hangul"] >= 0.2:
        return "ko"
    if shares["cjk"] >= 0.2:
        return "zh"
    return "en"


# -- Layer 2: intent compiler ------------------------------------------------------------------------------

def compile_intent(request: RouteRequest) -> Intent:
    request.validate()
    text = f"{request.prompt}\n{request.context[:2000]}".lower()
    notes: list[str] = [TOKEN_ESTIMATE_NOTE]
    if request.task_type:
        task_type, declared = request.task_type, True
    else:
        task_type, declared = "chat", False
        for candidate, words in _KEYWORDS:
            if any(w in text for w in words):
                task_type = candidate
                break
        notes.append(f"task type {task_type} inferred from keywords; declare task_type to override")
    input_language = detect_language(request.prompt)
    answer_language = request.language or input_language
    prompt_tokens = estimate_tokens(request.prompt)
    context_tokens = estimate_tokens(request.context)
    caps: list[str] = []
    if task_type in _STRUCTURED:
        caps.append("structured_output")
    if prompt_tokens + context_tokens > 32_000:
        caps.append("long_context")
    if task_type == "image_analysis":
        caps.append("vision")
    if task_type == "coding":
        caps.append("code")
    return Intent(task_type, input_language, answer_language, prompt_tokens, context_tokens, tuple(caps),
                  task_type in _STRUCTURED, task_type in _DECOMPOSABLE and context_tokens > 0, declared, tuple(notes))


# -- Layer 3: semantic compressor --------------------------------------------------------------------------

@dataclass(frozen=True)
class Compressed:
    prompt: str
    context: str
    tokens_before: int
    tokens_after: int
    steps: tuple[str, ...]

    @property
    def saved_tokens(self) -> int:
        return self.tokens_before - self.tokens_after

    def as_dict(self) -> dict:
        return {"tokens_before": self.tokens_before, "tokens_after": self.tokens_after, "saved_tokens": self.saved_tokens,
                "steps": list(self.steps)}


_WORD = re.compile(r"[\w가-힣]{2,}", re.UNICODE)
STOP = frozenset({"the", "and", "for", "that", "this", "with", "from", "are", "was", "were", "have", "has", "not", "you",
                  "your", "our", "but", "all", "any", "can", "will", "into", "about", "what", "which", "there", "their"})


def words(text: str) -> set[str]:
    return {w.lower() for w in _WORD.findall(text) if w.lower() not in STOP}


def _paragraphs(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]


def compress(prompt: str, context: str = "", *, keep_ratio: float = 0.35, max_context_tokens: int = 6000,
             passage_threshold_tokens: int = 1500) -> Compressed:
    """Reduce the context without changing the task: normalize whitespace, drop repeated paragraphs, and when the
    context is long keep the paragraphs that share vocabulary with the prompt (at least one, at most `keep_ratio`)."""
    steps: list[str] = []
    before = estimate_tokens(prompt) + estimate_tokens(context)
    clean_prompt = "\n".join(line.rstrip() for line in prompt.strip().splitlines())
    ctx = unicodedata.normalize("NFC", context or "")
    paragraphs = _paragraphs(ctx)
    if len(paragraphs) != len(_paragraphs(context or "")) or ctx != (context or ""):
        steps.append("normalized whitespace")
    seen: set[str] = set()
    unique: list[str] = []
    for p in paragraphs:
        key = " ".join(p.split()).lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(p)
    if len(unique) < len(paragraphs):
        steps.append(f"dropped {len(paragraphs) - len(unique)} repeated paragraph(s)")
    context_tokens = estimate_tokens("\n\n".join(unique))
    if unique and context_tokens > passage_threshold_tokens:
        query = words(prompt)
        ranked = sorted(range(len(unique)), key=lambda i: (-(len(query & words(unique[i])) if query else 0), i))
        keep_n = max(1, int(len(unique) * keep_ratio))
        kept_idx = sorted(ranked[:keep_n])
        kept = [unique[i] for i in kept_idx]
        # never exceed the budget: trim the least relevant paragraph first
        while len(kept) > 1 and estimate_tokens("\n\n".join(kept)) > max_context_tokens:
            kept_idx.remove(max(kept_idx, key=ranked.index))
            kept = [unique[i] for i in kept_idx]
        if len(kept) < len(unique):
            steps.append(f"kept {len(kept)} of {len(unique)} paragraphs by overlap with the prompt")
        unique = kept
    new_context = "\n\n".join(unique)
    after = estimate_tokens(clean_prompt) + estimate_tokens(new_context)
    if not steps:
        steps.append("nothing to remove")
    return Compressed(clean_prompt, new_context, before, after, tuple(steps))


# -- Layer 4: language router --------------------------------------------------------------------------------

# Relative token cost of the same content by language, from the ratios above (English = 1.0). Estimates.
LANGUAGE_TOKEN_RATIO = {"en": 1.0, "ko": CHARS_PER_TOKEN["latin"] / CHARS_PER_TOKEN["hangul"], "zh": CHARS_PER_TOKEN["latin"] / CHARS_PER_TOKEN["cjk"]}


@dataclass(frozen=True)
class LanguagePlan:
    process_in: str
    answer_in: str
    token_ratio: float            # tokens in `process_in` relative to English, estimate
    translation_stage: bool       # a translation step would be needed (not built: no live translation adapter)
    reason: str

    def as_dict(self) -> dict:
        return {"process_in": self.process_in, "answer_in": self.answer_in, "token_ratio": round(self.token_ratio, 2),
                "translation_stage": self.translation_stage, "reason": self.reason}


def language_plan(intent: Intent) -> LanguagePlan:
    """Work runs in the input language; the answer comes back in the requested language.  A cheaper intermediate
    language would need a translation stage, which does not exist yet, so the plan only records the estimate."""
    ratio = LANGUAGE_TOKEN_RATIO.get(intent.input_language, 1.0)
    if intent.task_type == "translation":
        return LanguagePlan(intent.input_language, intent.answer_language, ratio, False, "translation is the task itself")
    if intent.input_language != "en" and ratio > 1.2:
        return LanguagePlan(intent.input_language, intent.answer_language, ratio, False,
                            f"{intent.input_language} costs about {ratio:.1f}x English tokens; a translation stage could cut that "
                            "but none is built, so the work runs in the input language")
    return LanguagePlan(intent.input_language, intent.answer_language, ratio, False, "input language is already the cheapest representation")
