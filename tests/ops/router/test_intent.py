"""Layers 2-4 are deterministic: task types come from declared types or keywords, languages from scripts, tokens are
labelled estimates, compression never touches the prompt, and the language router never pretends to translate."""

import pytest

from arbitrage.ops.errors import OpsError
from arbitrage.ops.router.intent import (RouteRequest, compile_intent, compress, detect_language, estimate_tokens, language_plan,
                                         TOKEN_ESTIMATE_NOTE)


def req(prompt, **kw):
    defaults = dict(idempotency_key="k", customer_id="c", cost_cap_krw=100)
    defaults.update(kw)
    return RouteRequest(prompt=prompt, **defaults)


@pytest.mark.parametrize("prompt, expected", [
    ("Translate this paragraph into Korean", "translation"),
    ("Extract the invoice fields as JSON", "extraction"),
    ("Classify the sentiment of these reviews", "classification"),
    ("Summarize the meeting notes", "summarization"),
    ("Fix the bug in this Python function", "coding"),
    ("Prove that the sequence converges, step by step", "reasoning"),
    ("이 문서를 요약해줘", "summarization"),
    ("What's a good name for a cat?", "chat"),
])
def test_task_type_is_inferred_from_keywords(prompt, expected):
    intent = compile_intent(req(prompt))
    assert intent.task_type == expected and not intent.declared
    assert TOKEN_ESTIMATE_NOTE in intent.notes


def test_declared_task_type_wins_and_structure_flags_follow():
    intent = compile_intent(req("Translate this", task_type="extraction"))
    assert intent.task_type == "extraction" and intent.declared and intent.structured_output
    assert compile_intent(req("Summarize", context="a\n\nb")).decomposable
    assert not compile_intent(req("Summarize")).decomposable   # nothing to split without context


def test_languages_and_token_estimates():
    assert detect_language("배송이 늦었지만 제품은 좋아요") == "ko"
    assert detect_language("The parcel arrived late") == "en"
    ko, en = estimate_tokens("배송이 늦었지만 제품은 좋아요"), estimate_tokens("The parcel arrived late but works")
    assert ko > 0 and en > 0 and estimate_tokens("") == 0
    assert estimate_tokens("word " * 100) > estimate_tokens("word " * 10)
    intent = compile_intent(req("배송이 늦었지만 제품은 좋아요, 분류해줘", language="en"))
    assert intent.input_language == "ko" and intent.answer_language == "en"


def test_validation_refuses_what_cannot_be_routed():
    with pytest.raises(OpsError, match="cost_cap_krw"):
        req("hi", cost_cap_krw=0).validate()
    with pytest.raises(OpsError, match="task_type"):
        req("hi", task_type="mining").validate()
    with pytest.raises(OpsError, match="optimization"):
        req("hi", optimization="cheapest").validate()
    with pytest.raises(OpsError, match="prompt"):
        req("   ").validate()


def test_compression_drops_repeats_and_keeps_relevant_passages_without_touching_the_prompt():
    dup = compress("Extract totals", "Invoice 12 total 30\n\nInvoice 12 total 30\n\nWeather was fine")
    assert dup.saved_tokens > 0 and "dropped 1 repeated paragraph(s)" in dup.steps and dup.prompt == "Extract totals"
    paragraphs = []
    for i in range(40):
        paragraphs.append(("Invoice %d total %d won due soon " % (i, i * 10)) * 20 if i % 5 == 0 else ("Weather notes and filler line %d " % i) * 20)
    long = compress("Extract the invoice totals", "\n\n".join(paragraphs))
    assert long.tokens_after < long.tokens_before
    assert any("kept" in s for s in long.steps)
    assert "Invoice 0 total 0" in long.context and "Weather notes" not in long.context.split("\n\n")[0]
    assert compress("hello", "").steps == ("nothing to remove",)


def test_language_plan_records_the_estimate_and_never_invents_a_translation_stage():
    ko = language_plan(compile_intent(req("이 문서를 요약해줘")))
    assert ko.process_in == "ko" and ko.answer_in == "ko" and ko.token_ratio > 1.2 and ko.translation_stage is False
    assert "none is built" in ko.reason
    en = language_plan(compile_intent(req("Summarize this")))
    assert en.token_ratio == 1.0 and en.translation_stage is False
    tr = language_plan(compile_intent(req("Translate into Korean: hello", language="ko")))
    assert tr.answer_in == "ko" and tr.reason == "translation is the task itself"
