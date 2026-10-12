"""ذخیره و بازیابی پیشرفت ترجمه — جلوگیری از دست رفتن کار هنگام اتمام سهمیه یا قطع شبکه.

هر دسته‌ی ترجمه‌شده بلافاصله روی دیسک ثبت می‌شود، بنابراین اگر سرویس LLM در میانه‌ی
سند شکست بخورد، کارهای انجام‌شده حفظ می‌شود و اجرای بعدی از همان نقطه ادامه می‌یابد.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ..config import settings
from .models import SubtitleDocument

CHECKPOINT_VERSION = 1


def source_fingerprint(source_path: Path | str) -> str:
    """اثر انگشت محتوایی فایل ورودی؛ تضمین می‌کند checkpoint متعلق به همان فایل باشد."""
    path = Path(source_path)
    digest = hashlib.sha256()
    digest.update(str(path.stat().st_size).encode("ascii"))
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()[:16]


@dataclass
class TranslationCheckpoint:
    """وضعیت ترجمه‌ی نیمه‌تمام یک فایل زیرنویس."""

    source_hash: str
    filename: str
    total_cues: int
    translations: dict[int, str] = field(default_factory=dict)
    topic: str = ""
    updated_at: float = field(default_factory=time.time)

    @property
    def completed_count(self) -> int:
        return len(self.translations)

    @property
    def progress_pct(self) -> float:
        if self.total_cues <= 0:
            return 0.0
        return min(100.0, (self.completed_count / self.total_cues) * 100.0)

    def to_dict(self) -> dict:
        return {
            "version": CHECKPOINT_VERSION,
            "source_hash": self.source_hash,
            "filename": self.filename,
            "total_cues": self.total_cues,
            "topic": self.topic,
            "updated_at": self.updated_at,
            "translations": {str(k): v for k, v in self.translations.items()},
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TranslationCheckpoint":
        raw = data.get("translations") or {}
        return cls(
            source_hash=str(data.get("source_hash", "")),
            filename=str(data.get("filename", "")),
            total_cues=int(data.get("total_cues", 0)),
            translations={int(k): str(v) for k, v in raw.items()},
            topic=str(data.get("topic", "")),
            updated_at=float(data.get("updated_at", 0.0) or 0.0),
        )


def snapshot_document(
    doc: SubtitleDocument,
    source_hash: str,
    topic: str = "",
) -> TranslationCheckpoint:
    """ساخت checkpoint از وضعیت فعلی سند (ترجمه‌های خالی هم جزو پیشرفت محسوب می‌شوند)."""
    translations: dict[int, str] = {}
    for position, cue in enumerate(doc.cues):
        if cue.translated_text is not None:
            translations[position] = cue.translated_text
    return TranslationCheckpoint(
        source_hash=source_hash,
        filename=doc.filename,
        total_cues=doc.total_cues,
        translations=translations,
        topic=topic,
        updated_at=time.time(),
    )


class CheckpointStore:
    """مدیریت فایل‌های checkpoint روی دیسک با نوشتن اتمیک."""

    def __init__(self, root: Optional[Path] = None):
        self.root = Path(root) if root else (settings.base_dir / "data" / "checkpoints")

    def _path_for(self, source_hash: str) -> Path:
        return self.root / f"{source_hash}.json"

    def load(self, source_hash: str) -> Optional[TranslationCheckpoint]:
        """خواندن checkpoint معتبر؛ در صورت نبود یا خرابی بودن، None برمی‌گرداند."""
        path = self._path_for(source_hash)
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if int(data.get("version", 0)) != CHECKPOINT_VERSION:
            return None
        checkpoint = TranslationCheckpoint.from_dict(data)
        return checkpoint if checkpoint.source_hash == source_hash else None

    def save(self, checkpoint: TranslationCheckpoint) -> None:
        """ذخیره‌ی اتمیک؛ نوشتن ناقص هرگز نباید checkpoint قبلی را از بین ببرد."""
        self.root.mkdir(parents=True, exist_ok=True)
        target = self._path_for(checkpoint.source_hash)
        tmp_path = target.with_suffix(".json.tmp")
        tmp_path.write_text(
            json.dumps(checkpoint.to_dict(), ensure_ascii=False), encoding="utf-8"
        )
        os.replace(tmp_path, target)

    def clear(self, source_hash: str) -> None:
        try:
            self._path_for(source_hash).unlink(missing_ok=True)
        except OSError:
            pass