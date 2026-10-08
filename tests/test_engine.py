"""تست‌های جامع برای موتور ترجمه، واژه‌نامه و زنجیره Fallback و Retry."""

import pytest
from unittest.mock import AsyncMock, patch

from app.core.engine import TranslationEngine, _extract_json_from_response
from app.core.models import SubtitleCue, SubtitleDocument, AcademicContext, TranslationBatch
from app.core.glossary import GlossaryManager


def test_extract_json_valid_and_fenced():
    # Pure JSON
    res1 = _extract_json_from_response('{"C1": "متن ۱", "C2": "متن ۲"}')
    assert res1 == {"C1": "متن ۱", "C2": "متن ۲"}

    # Markdown fenced JSON
    res2 = _extract_json_from_response('```json\n{"C1": "متن ۱", "C2": "متن ۲"}\n```')
    assert res2 == {"C1": "متن ۱", "C2": "متن ۲"}

    # JSON with extra text around it
    res3 = _extract_json_from_response('Here is the translation:\n{"C1": "متن"}\nHope this helps!')
    assert res3 == {"C1": "متن"}

    # Invalid JSON
    with pytest.raises(ValueError):
        _extract_json_from_response("Not a JSON object at all")


def test_glossary_prompt_injection():
    glossary = GlossaryManager()
    terms = glossary.find_relevant_terms(
        "In this machine learning lecture we discuss gradient descent.",
        custom_glossary={"gradient descent": "گرادیان نزولی (Gradient Descent)"}
    )
    assert "gradient descent" in terms
    assert terms["gradient descent"] == "گرادیان نزولی (Gradient Descent)"

    formatted = glossary.format_glossary_prompt(terms)
    assert "MANDATORY TERMINOLOGY MAPPINGS:" in formatted
    assert "gradient descent -> گرادیان نزولی" in formatted


@pytest.mark.asyncio
async def test_translate_batch_success():
    cues = [
        SubtitleCue(index=1, start_time="00:00:01,000", end_time="00:00:02,000", text="Hello world"),
        SubtitleCue(index=2, start_time="00:00:02,000", end_time="00:00:03,000", text="This is a test"),
    ]
    batch = TranslationBatch(batch_index=0, cues=cues)
    engine = TranslationEngine(api_key="test-key", models=["model-a"])

    with patch.object(
        engine, "_call_llm_api", new_callable=AsyncMock
    ) as mock_call:
        mock_call.return_value = '{"C1": "سلام دنیا", "C2": "این یک آزمایش است"}'
        result = await engine.translate_batch(batch, AcademicContext())

        assert result["C1"] == "سلام دنیا"
        assert result["C2"] == "این یک آزمایش است"
        mock_call.assert_called_once()


@pytest.mark.asyncio
async def test_fallback_chain_on_error():
    cues = [SubtitleCue(index=1, start_time="00:00:01,000", end_time="00:00:02,000", text="Gradient descent")]
    batch = TranslationBatch(batch_index=0, cues=cues)
    engine = TranslationEngine(api_key="test-key", models=["failing-model", "working-model"], max_retries_per_model=1)

    with patch.object(
        engine, "_call_llm_api", new_callable=AsyncMock
    ) as mock_call:
        # First call fails, second call succeeds
        mock_call.side_effect = [
            RuntimeError("Rate limit exceeded 429"),
            '{"C1": "گرادیان نزولی"}',
        ]
        result = await engine.translate_batch(batch, AcademicContext())

        assert result["C1"] == "گرادیان نزولی"
        assert mock_call.call_count == 2


@pytest.mark.asyncio
async def test_translate_document_with_progress():
    cues = [
        SubtitleCue(index=1, start_time="00:00:01,000", end_time="00:00:02,000", text="Cue 1"),
        SubtitleCue(index=2, start_time="00:00:02,000", end_time="00:00:03,000", text="Cue 2"),
    ]
    doc = SubtitleDocument(filename="test.srt", cues=cues)
    engine = TranslationEngine(api_key="test-key", models=["model-a"])

    progress_reports = []

    async def on_progress(pct, done, total):
        progress_reports.append((pct, done, total))

    with patch.object(
        engine, "_call_llm_api", new_callable=AsyncMock
    ) as mock_call:
        mock_call.return_value = '{"C1": "ترجمه ۱", "C2": "ترجمه ۲"}'
        translated_doc = await engine.translate_document(doc, on_progress=on_progress)

        assert translated_doc.cues[0].translated_text == "ترجمه ۱"
        assert translated_doc.cues[1].translated_text == "ترجمه ۲"
        assert len(progress_reports) == 1
        assert progress_reports[0] == (100.0, 2, 2)
