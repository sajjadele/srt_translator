"""تست‌های جامع برای موتور ترجمه، واژه‌نامه و زنجیره Fallback و Retry."""

import httpx
import pytest
from unittest.mock import AsyncMock, patch

from app.core.engine import (
    TRIAGE_DAILY_QUOTA,
    TRIAGE_FATAL,
    TRIAGE_MODEL_UNAVAILABLE,
    TRIAGE_OVERLOADED,
    TRIAGE_RATE_LIMIT,
    TRIAGE_TRANSIENT,
    TranslationEngine,
    _extract_json_from_response,
    _humanize_duration,
    _mask_secret,
    _parse_retry_delay,
    _triage_error,
)
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

    # JSON with unescaped LaTeX backslashes (e.g. \Sigma, \alpha, \vec)
    raw_latex = r'''{
  "C1": "$\Sigma F_x = 0$",
  "C2": "زاویه \alpha و بردار \vec{v}"
}'''
    res4 = _extract_json_from_response(raw_latex)
    assert "\\Sigma" in res4["C1"]
    assert "\\alpha" in res4["C2"]

    # Test with \unit (which previously crashed json.loads with Invalid \uXXXX escape)
    # along with \theta, \times, \tau, \rho, \beta, \frac and trailing comma
    raw_physics = r'''{
  "C1": "طول یکه \unit length است",
  "C2": "زاویه \theta و ضرب \times و گشتاور \tau",
  "C3": "چگالی \rho و زاویه \beta و کسر \frac{1}{2}",
}'''
    res5 = _extract_json_from_response(raw_physics)
    assert "\\unit" in res5["C1"]
    assert "\\theta" in res5["C2"]
    assert "\\times" in res5["C2"]
    assert "\\tau" in res5["C2"]
    assert "\\rho" in res5["C3"]

    # Test emergency regex fallback on broken syntax
    raw_broken = 'Some explanation {"C1": "ترجمه اول", "C2": "ترجمه دوم بدون بستن درست'
    res6 = _extract_json_from_response(raw_broken)
    assert res6["C1"] == "ترجمه اول"

    # Invalid JSON without any cues
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


@pytest.mark.asyncio
async def test_translate_batch_with_empty_cues():
    # Cue 2 is completely empty (silence in lecture)
    cues = [
        SubtitleCue(index=1, start_time="00:00:01,000", end_time="00:00:02,000", text="Non-empty text"),
        SubtitleCue(index=2, start_time="00:00:02,000", end_time="00:00:03,000", text="   "),
        SubtitleCue(index=3, start_time="00:00:03,000", end_time="00:00:04,000", text="Another text"),
    ]
    batch = TranslationBatch(batch_index=0, cues=cues)
    engine = TranslationEngine(api_key="test-key", models=["model-a"])

    with patch.object(
        engine, "_call_llm_api", new_callable=AsyncMock
    ) as mock_call:
        # LLM only returns keys for non-empty cues (omitting C2)
        mock_call.return_value = '{"C1": "متن غیرخالی", "C3": "متن دیگر"}'
        result = await engine.translate_batch(batch, AcademicContext())

        assert result["C1"] == "متن غیرخالی"
        assert result["C2"] == ""
        assert result["C3"] == "متن دیگر"


# ---------------------------------------------------------------------------
# طبقه‌بندی خطاهای سرویس LLM (بدنه‌ی خطاهای واقعی Gemini)
# ---------------------------------------------------------------------------

DAILY_QUOTA_BODY = (
    '[{"error":{"code":429,"message":"You exceeded your current quota, please check your '
    'plan and billing details. \\n* Quota exceeded for metric: '
    'generativelanguage.googleapis.com/generate_content_free_tier_requests, limit: 500, '
    'model: gemini-3.5-flash-lite\\nPlease retry in 18h11m8.392204465s.",'
    '"status":"RESOURCE_EXHAUSTED"}}]'
)

RATE_LIMIT_BODY = (
    '[{"error":{"code":429,"message":"You exceeded your current quota...\\n* Quota exceeded '
    'for metric: generativelanguage.googleapis.com/generate_content_requests, limit: 15, '
    'model: gemini-3.1-flash-lite\\nPlease retry in 24s.","status":"RESOURCE_EXHAUSTED"}}]'
)

RETIRED_MODEL_BODY = (
    '[{"error":{"code":404,"message":"This model models/gemini-2.5-flash is no longer available '
    'to new users. Please use models/gemini-3.8-flash."}}]'
)

OVERLOADED_BODY = (
    '[{"error":{"code":503,"message":"This model is currently experiencing high demand.",'
    '"status":"UNAVAILABLE"}}]'
)


def test_parse_retry_delay():
    assert _parse_retry_delay(DAILY_QUOTA_BODY) == pytest.approx(65468.4, abs=1.0)
    assert _parse_retry_delay(RATE_LIMIT_BODY) == pytest.approx(24.0)
    assert _parse_retry_delay("no delay info here") is None


def test_humanize_duration():
    assert _humanize_duration(65460) == "18 ساعت و 11 دقیقه"
    assert _humanize_duration(45) == "45 ثانیه"
    assert _humanize_duration(0) == "چند لحظه"


def test_triage_distinguishes_daily_quota_from_rate_limit():
    # هر دو ۴۲۹ هستند و هر دو کلمه‌ی «quota» دارند، اما رفتارشان کاملاً متفاوت است
    kind_daily, wait_daily = _triage_error(429, DAILY_QUOTA_BODY, "")
    assert kind_daily == TRIAGE_DAILY_QUOTA
    assert wait_daily == 0.0

    kind_rpm, wait_rpm = _triage_error(429, RATE_LIMIT_BODY, "")
    assert kind_rpm == TRIAGE_RATE_LIMIT
    # زمان اعلام‌شده توسط سرویس + کمی بافر
    assert wait_rpm == pytest.approx(25.5)


def test_triage_long_rate_limit_is_treated_as_daily():
    """محدودیت نرخی که سرویس برای مدت طولانی اعلام می‌کند نباید بی‌نهایت تلاش مجدد شود."""
    long_body = RATE_LIMIT_BODY.replace("in 24s", "in 3h2m5s")
    kind, _ = _triage_error(429, long_body, "")
    assert kind == TRIAGE_DAILY_QUOTA


def test_triage_other_categories():
    assert _triage_error(404, RETIRED_MODEL_BODY, "")[0] == TRIAGE_MODEL_UNAVAILABLE
    assert _triage_error(503, OVERLOADED_BODY, "")[0] == TRIAGE_OVERLOADED
    assert _triage_error(403, "API key not valid", "")[0] == TRIAGE_FATAL
    assert _triage_error(400, "", "")[0] == TRIAGE_FATAL
    assert _triage_error(0, "Timeout or network dropped", "")[0] == TRIAGE_TRANSIENT


def _http_error(status_code: int, body: str) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://example.com/chat/completions")
    response = httpx.Response(status_code, text=body, request=request)
    return httpx.HTTPStatusError(f"HTTP {status_code}", request=request, response=response)


@pytest.mark.asyncio
async def test_per_minute_429_does_not_kill_the_model():
    """باگ اصلی: خطای ۴۲۹ دقیقه‌ای نباید مدل را برای ادامه‌ی اجرا از رده خارج کند."""
    cues = [SubtitleCue(index=1, start_time="00:00:01,000", end_time="00:00:02,000", text="Hello")]
    batch = TranslationBatch(batch_index=0, cues=cues)
    engine = TranslationEngine(
        api_key="test-key", models=["model-a"], max_retries_per_model=2, inter_batch_delay=0
    )

    with patch.object(engine, "_call_llm_api", new_callable=AsyncMock) as mock_call:
        mock_call.side_effect = [
            _http_error(429, RATE_LIMIT_BODY),
            '{"C1": "سلام"}',
        ]
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await engine.translate_batch(batch, AcademicContext())

    assert result["C1"] == "سلام"
    # ۴۲۹ دقیقه‌ای نباید کلید را از رده خارج کند
    assert ("model-a", "test-key") not in engine._exhausted_pairs


@pytest.mark.asyncio
async def test_daily_quota_marks_key_and_reports_reset_time():
    cues = [SubtitleCue(index=1, start_time="00:00:01,000", end_time="00:00:02,000", text="Hello")]
    batch = TranslationBatch(batch_index=0, cues=cues)
    engine = TranslationEngine(
        api_key="test-key", models=["model-a"], max_retries_per_model=4, inter_batch_delay=0
    )

    with patch.object(engine, "_call_llm_api", new_callable=AsyncMock) as mock_call:
        mock_call.side_effect = _http_error(429, DAILY_QUOTA_BODY)
        with pytest.raises(RuntimeError) as exc_info:
            await engine.translate_batch(batch, AcademicContext())

    # سقف روزانه نباید ۴ بار تکرار شود؛ همان بار اول کلید کنار گذاشته می‌شود
    assert mock_call.call_count == 1
    assert ("model-a", "test-key") in engine._exhausted_pairs
    assert "کلید × مدل" in str(exc_info.value)
    assert "18 ساعت و 11 دقیقه" in str(exc_info.value)


@pytest.mark.asyncio
async def test_retired_model_is_skipped_without_retries():
    cues = [SubtitleCue(index=1, start_time="00:00:01,000", end_time="00:00:02,000", text="Hello")]
    batch = TranslationBatch(batch_index=0, cues=cues)
    engine = TranslationEngine(
        api_key="test-key", models=["gemini-2.5-flash", "gemini-3.6-flash"], max_retries_per_model=4
    )

    with patch.object(engine, "_call_llm_api", new_callable=AsyncMock) as mock_call:
        mock_call.side_effect = [
            _http_error(404, RETIRED_MODEL_BODY),
            '{"C1": "سلام"}',
        ]
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await engine.translate_batch(batch, AcademicContext())

    assert result["C1"] == "سلام"
    assert mock_call.call_count == 2
    assert "gemini-2.5-flash" in engine._dead_models
    assert all(m != "gemini-2.5-flash" for m, _ in engine._exhausted_pairs)


# ---------------------------------------------------------------------------
# زنجیره‌ی کلیدهای API — سهمیه در سطح کلید است
# ---------------------------------------------------------------------------

KEY_A = "key-aaaaaaaaaaaaaaaaaaaa"
KEY_B = "key-bbbbbbbbbbbbbbbbbbbb"


def _one_cue_batch():
    cues = [SubtitleCue(index=1, start_time="00:00:01,000", end_time="00:00:02,000", text="Hello")]
    return TranslationBatch(batch_index=0, cues=cues)


def test_mask_secret_never_returns_full_key():
    masked = _mask_secret(KEY_A)
    assert KEY_A not in masked
    assert masked.startswith("key-aa")
    assert "…" in masked
    assert _mask_secret("") == "(تنظیم نشده)"


def test_api_keys_fallback_from_api_key_param():
    engine = TranslationEngine(api_key=KEY_A, models=["m"])
    assert engine.api_keys == [KEY_A]


def test_api_keys_deduplicated_and_labelled():
    engine = TranslationEngine(api_keys=[KEY_A, KEY_B, KEY_A], models=["m"])
    # تکراری‌ها هنگام ساخت برچسب یکسان می‌گیرند ولی لیست حفظ می‌شود
    assert engine._key_label(KEY_A) != engine._key_label(KEY_B)
    assert engine._key_label(KEY_A).startswith("کلید #1")
    assert engine._key_label(KEY_B).startswith("کلید #2")


@pytest.mark.asyncio
async def test_quota_switches_to_second_key():
    """مهم‌ترین رفتار: تمام شدن سهمیه‌ی یک ترکیب نباید ترجمه را متوقف کند."""
    engine = TranslationEngine(
        api_keys=[KEY_A, KEY_B], models=["model-a"], max_retries_per_model=3, inter_batch_delay=0
    )

    with patch.object(engine, "_call_llm_api", new_callable=AsyncMock) as mock_call:
        mock_call.side_effect = [_http_error(429, DAILY_QUOTA_BODY), '{"C1": "سلام"}']
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await engine.translate_batch(_one_cue_batch(), AcademicContext())

    assert result["C1"] == "سلام"
    # فقط جفت (مدل، کلید اول) تمام می‌شود — نه کل کلید
    assert engine._exhausted_pairs == {("model-a", KEY_A)}
    # کلید دوم واقعاً استفاده شده است
    assert mock_call.call_args.kwargs["api_key"] == KEY_B


@pytest.mark.asyncio
async def test_quota_exhaustion_does_not_kill_other_models():
    """سهمیه در سطح جفت (کلید × مدل) است: هر مدل سهمیه‌ی مستقل دارد."""
    engine = TranslationEngine(
        api_keys=[KEY_A],
        models=["model-a", "model-b", "model-c"],
        max_retries_per_model=1,
        inter_batch_delay=0,
    )

    with patch.object(engine, "_call_llm_api", new_callable=AsyncMock) as mock_call:
        # ترکیب اول پر است، دومی سالم است
        mock_call.side_effect = [
            _http_error(429, DAILY_QUOTA_BODY),
            _http_error(429, DAILY_QUOTA_BODY),
            '{"C1": "سلام"}',
        ]
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await engine.translate_batch(_one_cue_batch(), AcademicContext())

    assert result["C1"] == "سلام"
    # هر دو ترکیب جداگانه علامت خورده‌اند، ولی هیچ مدلی کشته نشده
    assert engine._exhausted_pairs == {("model-a", KEY_A), ("model-b", KEY_A)}
    assert engine._dead_models == {}


@pytest.mark.asyncio
async def test_all_pairs_exhausted_reports_pairs():
    engine = TranslationEngine(
        api_keys=[KEY_A, KEY_B], models=["model-a"], max_retries_per_model=2, inter_batch_delay=0
    )

    with patch.object(engine, "_call_llm_api", new_callable=AsyncMock) as mock_call:
        mock_call.side_effect = _http_error(429, DAILY_QUOTA_BODY)
        with pytest.raises(RuntimeError) as exc_info:
            await engine.translate_batch(_one_cue_batch(), AcademicContext())

    message = str(exc_info.value)
    assert mock_call.call_count == 2  # هر ترکیب فقط یک بار
    assert engine._exhausted_pairs == {("model-a", KEY_A), ("model-a", KEY_B)}
    assert "2 ترکیب از 2 ترکیب" in message
    assert "LLM_API_KEYS" in message
    # هیچ کلید واقعی نباید در پیام خطا لو برود
    assert KEY_A not in message
    assert KEY_B not in message


@pytest.mark.asyncio
async def test_invalid_key_falls_through_to_next_key():
    """۴۰۱/۴۰۳ یک کلید را می‌کُشد ولی نباید کل زنجیره را متوقف کند."""
    engine = TranslationEngine(
        api_keys=[KEY_A, KEY_B], models=["model-a"], max_retries_per_model=2, inter_batch_delay=0
    )

    with patch.object(engine, "_call_llm_api", new_callable=AsyncMock) as mock_call:
        mock_call.side_effect = [
            _http_error(403, '[{"error":{"code":403,"message":"API key not valid."}}]'),
            '{"C1": "سلام"}',
        ]
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await engine.translate_batch(_one_cue_batch(), AcademicContext())

    assert result["C1"] == "سلام"
    assert KEY_A in engine._dead_keys
    assert mock_call.call_args.kwargs["api_key"] == KEY_B


@pytest.mark.asyncio
async def test_retired_model_not_retried_across_keys():
    """۴۰۴ در سطح مدل است؛ باید یک‌بار بررسی شود، نه برای هر کلید."""
    engine = TranslationEngine(
        api_keys=[KEY_A, KEY_B], models=["gemini-2.5-flash"], max_retries_per_model=2
    )

    with patch.object(engine, "_call_llm_api", new_callable=AsyncMock) as mock_call:
        mock_call.side_effect = _http_error(404, RETIRED_MODEL_BODY)
        with patch("asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(RuntimeError):
                await engine.translate_batch(_one_cue_batch(), AcademicContext())

    assert mock_call.call_count == 1

