"""مدل‌های داده‌ای هسته برای پردازش، دسته‌بندی و مدیریت زیرنویس‌ها."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional


# الگوهای تشخیص افکت‌های صوتی و علائم غیرکلامی در زیرنویس
_SOUND_EFFECT_RE = re.compile(
    r"^(\[[^\]]+\]|\([^\)]+\)|♪+.*♪*|\*+[^\*]+\*+)$", re.IGNORECASE
)


@dataclass
class SubtitleCue:
    """نماینده‌ی یک بلاک زیرنویس درون فایل SRT."""

    index: int
    start_time: str  # قالب: HH:MM:SS,mmm
    end_time: str    # قالب: HH:MM:SS,mmm
    text: str
    translated_text: Optional[str] = None

    @property
    def clean_text(self) -> str:
        """متن تمیز شده بدون فاصله‌های زائد ابتدایی و انتهایی و نشانگرهای نامرئی."""
        return self.text.strip().strip("\u200F\u200E\uFEFF")

    @property
    def is_sound_effect(self) -> bool:
        """بررسی آیا این بلاک فقط افکت صوتی، تشویق، موسیقی یا صدای محیط است."""
        cleaned = self.clean_text
        return bool(_SOUND_EFFECT_RE.match(cleaned))

    def get_output_text(self) -> str:
        """متن خروجی نهایی؛ اگر ترجمه وجود داشت ترجمه وگرنه متن اصلی."""
        if self.translated_text is not None and self.translated_text.strip():
            return self.translated_text.strip()
        return self.clean_text


@dataclass
class SubtitleDocument:
    """سند کامل زیرنویس شامل تمام بلاک‌های مرتب‌شده."""

    filename: str
    cues: list[SubtitleCue] = field(default_factory=list)
    raw_encoding: str = "utf-8"

    @property
    def total_cues(self) -> int:
        return len(self.cues)

    @property
    def is_fully_translated(self) -> bool:
        return bool(self.cues) and all(cue.translated_text is not None for cue in self.cues)

    @property
    def translated_cues_count(self) -> int:
        return sum(1 for cue in self.cues if cue.translated_text is not None)


@dataclass
class AcademicContext:
    """تنظیمات و کانتکست دانشگاهی برای هدایت سبک ترجمه و واژگان تخصصی."""

    topic: str = "General Academic"
    glossary: dict[str, str] = field(default_factory=dict)
    preserve_terms: bool = True


@dataclass
class TranslationBatch:
    """دسته‌ای از بلاک‌های متوالی همراه با کانتکست قبلی و بعدی برای ارسال به مدل."""

    batch_index: int
    cues: list[SubtitleCue]
    pre_context: list[str] = field(default_factory=list)
    post_context: list[str] = field(default_factory=list)
    academic_topic: Optional[str] = None

    @property
    def cue_keys(self) -> list[str]:
        """کلیدهای شناسه در پرامپت (مثلاً C1, C2, ...)."""
        return [f"C{i + 1}" for i in range(len(self.cues))]

    def get_cues_map(self) -> dict[str, str]:
        """دیکشنری کلید به متن اصلی بلاک."""
        return {f"C{i + 1}": cue.clean_text for i, cue in enumerate(self.cues)}
