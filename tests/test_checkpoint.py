"""تست‌های ذخیره‌ی پیشرفت و از سرگیری ترجمه."""
import json

import pytest
from unittest.mock import AsyncMock, patch

from app.core.checkpoint import (
    CHECKPOINT_VERSION,
    CheckpointStore,
    TranslationCheckpoint,
    snapshot_document,
    source_fingerprint,
)
from app.core.engine import PartialTranslationError, TranslationEngine
from app.core.models import AcademicContext, SubtitleCue, SubtitleDocument


def _make_doc(count: int) -> SubtitleDocument:
    return SubtitleDocument(
        filename="test.srt",
        cues=[
            SubtitleCue(index=i + 1, start_time="00:00:01,000", end_time="00:00:02,000", text=f"Cue {i + 1}")
            for i in range(count)
        ],
    )


def _json_response(count: int) -> str:
    return json.dumps({f"C{i}": f"ترجمه {i}" for i in range(1, count + 1)}, ensure_ascii=False)


def test_checkpoint_round_trip(tmp_path):
    doc = _make_doc(3)
    for i, cue in enumerate(doc.cues):
        cue.translated_text = f"ترجمه {i + 1}"

    store = CheckpointStore(root=tmp_path)
    cp = snapshot_document(doc, "abc123", topic="Physics")
    store.save(cp)

    loaded = store.load("abc123")
    assert loaded is not None
    stored_version = json.loads((tmp_path / "abc123.json").read_text(encoding="utf-8"))["version"]
    assert stored_version == CHECKPOINT_VERSION
    assert loaded.total_cues == 3
    assert loaded.completed_count == 3
    assert loaded.translations[0] == "ترجمه 1"
    assert loaded.topic == "Physics"
    assert loaded.progress_pct == 100.0


def test_checkpoint_store_clear_and_missing(tmp_path):
    store = CheckpointStore(root=tmp_path)
    assert store.load("nothing-here") is None

    store.save(snapshot_document(_make_doc(1), "xyz"))
    assert store.load("xyz") is not None
    store.clear("xyz")
    assert store.load("xyz") is None


def test_checkpoint_ignores_corrupt_file(tmp_path):
    store = CheckpointStore(root=tmp_path)
    store.root.mkdir(parents=True, exist_ok=True)
    (store.root / "bad.json").write_text("{ not json", encoding="utf-8")
    assert store.load("bad") is None


def test_checkpoint_ignores_other_source(tmp_path):
    store = CheckpointStore(root=tmp_path)
    store.save(snapshot_document(_make_doc(2), "hash-a"))
    assert store.load("hash-b") is None


def test_source_fingerprint_is_content_based(tmp_path):
    a = tmp_path / "a.srt"
    b = tmp_path / "b.srt"
    a.write_text("hello", encoding="utf-8")
    b.write_text("hello", encoding="utf-8")
    c = tmp_path / "c.srt"
    c.write_text("different", encoding="utf-8")
    assert source_fingerprint(a) == source_fingerprint(b)
    assert source_fingerprint(a) != source_fingerprint(c)


@pytest.mark.asyncio
async def test_partial_failure_keeps_completed_batches(tmp_path):
    """باگ اصلی: خطای وسط کار نباید کل سند را دور بریزد."""
    doc = _make_doc(4)
    engine = TranslationEngine(api_key="k", models=["m"], inter_batch_delay=0)
    store = CheckpointStore(root=tmp_path)

    calls = {"n": 0}

    async def flaky(client, model, system_prompt, user_payload, api_key=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return _json_response(2)
        raise RuntimeError("quota exhausted")

    with patch.object(engine, "_call_llm_api", new_callable=AsyncMock, side_effect=flaky):
        with patch("asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(PartialTranslationError) as exc_info:
                await engine.translate_document(
                    doc,
                    context=AcademicContext(),
                    batcher=_batcher(2),
                    checkpoint_store=store,
                    source_hash="h1",
                )

    err = exc_info.value
    assert err.completed == 2
    assert err.total == 4
    assert err.progress_pct == 50.0
    # سند نیمه‌ترجمه‌شده تحویل داده می‌شود
    assert err.doc.cues[0].translated_text == "ترجمه 1"
    assert err.doc.cues[1].translated_text == "ترجمه 2"
    assert err.doc.cues[2].translated_text is None
    # پیشرفت روی دیسک هم باقی مانده است
    assert store.load("h1").completed_count == 2


@pytest.mark.asyncio
async def test_resume_continues_from_checkpoint(tmp_path):
    """اجرای دوم باید فقط بخش‌های ترجمه‌نشده را ارسال کند."""
    store = CheckpointStore(root=tmp_path)

    first = _make_doc(4)
    engine_a = TranslationEngine(
        api_key="k", models=["m"], inter_batch_delay=0, max_retries_per_model=1
    )
    seen_first = {"n": 0}

    async def half_done(client, model, system_prompt, user_payload, api_key=None):
        seen_first["n"] += 1
        if seen_first["n"] > 1:
            raise RuntimeError("quota exhausted")
        return _json_response(2)

    with patch.object(engine_a, "_call_llm_api", new_callable=AsyncMock, side_effect=half_done):
        with pytest.raises(PartialTranslationError):
            await engine_a.translate_document(
                first,
                context=AcademicContext(),
                batcher=_batcher(2),
                checkpoint_store=store,
                source_hash="resume-me",
            )

    saved = store.load("resume-me")
    assert saved.completed_count == 2

    # اجرای دوم روی سند تازه‌ی همان فایل
    second = _make_doc(4)
    engine_b = TranslationEngine(api_key="k", models=["m"], inter_batch_delay=0)
    seen_payloads = []

    async def record(client, model, system_prompt, user_payload, api_key=None):
        seen_payloads.append(user_payload)
        return _json_response(2)

    with patch.object(engine_b, "_call_llm_api", new_callable=AsyncMock, side_effect=record):
        result = await engine_b.translate_document(
            second,
            context=AcademicContext(),
            batcher=_batcher(2),
            checkpoint_store=store,
            source_hash="resume-me",
        )

    # ۴ بلاک با دسته‌ی ۲تایی = ۲ دسته؛ اجرای اول دسته‌ی اول را ساخت،
    # پس اجرای دوم فقط باید همان یک دسته‌ی باقی‌مانده را ارسال کند.
    assert len(seen_payloads) == 1
    assert '"C1": "Cue 3"' in seen_payloads[0].replace("\n", " ").replace("  ", " ") or "Cue 3" in seen_payloads[0]
    assert "Cue 1" not in seen_payloads[0]
    assert result.cues[0].translated_text == "ترجمه 1"
    assert result.cues[3].translated_text == "ترجمه 2"
    # ترجمه کامل شد → checkpoint پاک شده است
    assert store.load("resume-me") is None


@pytest.mark.asyncio
async def test_checkpoint_cleared_after_full_success(tmp_path):
    store = CheckpointStore(root=tmp_path)
    engine = TranslationEngine(api_key="k", models=["m"], inter_batch_delay=0)

    async def ok(client, model, system_prompt, user_payload, api_key=None):
        return _json_response(4)

    with patch.object(engine, "_call_llm_api", new_callable=AsyncMock, side_effect=ok):
        doc = _make_doc(4)
        await engine.translate_document(
            doc,
            context=AcademicContext(),
            batcher=_batcher(4),
            checkpoint_store=store,
            source_hash="done",
        )

    assert store.load("done") is None


@pytest.mark.asyncio
async def test_first_batch_failure_raises_original_error(tmp_path):
    """وقتی هنوز هیچ پیشرفتی نیست، خطای معمولی بالا می‌رود نه خطای نیمه‌کاره."""
    engine = TranslationEngine(
        api_key="k", models=["m"], inter_batch_delay=0, max_retries_per_model=1
    )
    store = CheckpointStore(root=tmp_path)

    with patch.object(
        engine, "_call_llm_api", new_callable=AsyncMock, side_effect=RuntimeError("boom")
    ):
        with pytest.raises(RuntimeError) as exc_info:
            await engine.translate_document(
                _make_doc(4),
                context=AcademicContext(),
                batcher=_batcher(4),
                checkpoint_store=store,
                source_hash="fresh",
            )

    assert not isinstance(exc_info.value, PartialTranslationError)
    assert "boom" in str(exc_info.value)


def _batcher(batch_size: int):
    from app.core.batcher import ContextBatcher

    return ContextBatcher(batch_size=batch_size)