"""تست‌های واحد برای دسته‌بندی و پنجره لغزان کانتکست (Batcher)."""

from app.core.models import SubtitleCue, AcademicContext
from app.core.batcher import ContextBatcher


def test_batcher_single_batch():
    cues = [
        SubtitleCue(index=i, start_time="00:00:01,000", end_time="00:00:02,000", text=f"Sentence {i}")
        for i in range(1, 6)
    ]
    batcher = ContextBatcher(batch_size=10, pre_context_size=2, post_context_size=2)
    batches = batcher.create_batches(cues)

    assert len(batches) == 1
    b0 = batches[0]
    assert len(b0.cues) == 5
    assert b0.pre_context == []
    assert b0.post_context == []
    assert b0.cue_keys == ["C1", "C2", "C3", "C4", "C5"]


def test_batcher_multiple_batches_with_context():
    total_count = 25
    cues = [
        SubtitleCue(index=i, start_time="00:00:01,000", end_time="00:00:02,000", text=f"Cue text {i}")
        for i in range(1, total_count + 1)
    ]
    batcher = ContextBatcher(batch_size=10, pre_context_size=2, post_context_size=2)
    batches = batcher.create_batches(cues, context=AcademicContext(topic="Physics"))

    assert len(batches) == 3  # 10 + 10 + 5
    b0, b1, b2 = batches[0], batches[1], batches[2]

    # Batch 0
    assert len(b0.cues) == 10
    assert b0.pre_context == []
    assert b0.post_context == ["Cue text 11", "Cue text 12"]
    assert b0.academic_topic == "Physics"

    # Batch 1
    assert len(b1.cues) == 10
    assert b1.pre_context == ["Cue text 9", "Cue text 10"]
    assert b1.post_context == ["Cue text 21", "Cue text 22"]

    # Batch 2 (last)
    assert len(b2.cues) == 5
    assert b2.pre_context == ["Cue text 19", "Cue text 20"]
    assert b2.post_context == []
    assert b2.cue_keys == ["C1", "C2", "C3", "C4", "C5"]
