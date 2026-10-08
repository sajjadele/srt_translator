"""دسته‌بندی هوشمند بلاک‌های زیرنویس با پنجره لغزان کانتکست (Sliding Window Context)."""

from __future__ import annotations

from typing import Optional
from .models import SubtitleCue, TranslationBatch, AcademicContext
from ..config import settings


class ContextBatcher:
    """تقسیم زیرنویس‌ها به بسته‌های دارای زمینه جهت پیشگیری از شکستگی جملات."""

    def __init__(
        self,
        batch_size: Optional[int] = None,
        pre_context_size: Optional[int] = None,
        post_context_size: Optional[int] = None,
    ):
        self.batch_size = batch_size or settings.batch_size
        self.pre_context_size = pre_context_size or settings.pre_context_size
        self.post_context_size = post_context_size or settings.post_context_size

    def create_batches(
        self, cues: list[SubtitleCue], context: Optional[AcademicContext] = None
    ) -> list[TranslationBatch]:
        """
        ایجاد لیست دسته‌ها با کانتکست قبل و بعد.
        کانتکست قبل شامل آخرین جملات دسته قبلی، و کانتکست بعد شامل اولین جملات دسته بعدی است.
        """
        if not cues:
            return []

        batches: list[TranslationBatch] = []
        total_cues = len(cues)
        num_batches = (total_cues + self.batch_size - 1) // self.batch_size
        topic = context.topic if context else "General Academic"

        for b_idx in range(num_batches):
            start_i = b_idx * self.batch_size
            end_i = min(start_i + self.batch_size, total_cues)
            active_cues = cues[start_i:end_i]

            # محاسبه کانتکست پیشین (از بلاک‌های قبل از این دسته)
            pre_context: list[str] = []
            if start_i > 0 and self.pre_context_size > 0:
                pre_start = max(0, start_i - self.pre_context_size)
                pre_context = [
                    cues[k].get_output_text() for k in range(pre_start, start_i)
                ]

            # محاسبه کانتکست پسین (از بلاک‌های بعد از این دسته)
            post_context: list[str] = []
            if end_i < total_cues and self.post_context_size > 0:
                post_end = min(total_cues, end_i + self.post_context_size)
                post_context = [
                    cues[k].clean_text for k in range(end_i, post_end)
                ]

            batch = TranslationBatch(
                batch_index=b_idx,
                cues=active_cues,
                pre_context=pre_context,
                post_context=post_context,
                academic_topic=topic,
            )
            batches.append(batch)

        return batches
