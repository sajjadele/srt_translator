"""پارس، نرمال‌سازی و سریال‌سازی مقاوم فایل‌های زیرنویس SRT."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Union
from .models import SubtitleCue, SubtitleDocument
from .bidi_formatter import fix_bidi_text

# الگوی شناسایی خط تایم‌کد زیرنویس
# پشتیبانی از ویرگول (,) و نقطه (.) برای میلی‌ثانیه، و حذف متادیتای احتمالی مختصات
_TIMECODE_LINE_RE = re.compile(
    r"^\s*(\d{1,2}:\d{2}:\d{2}[,.]\d{3})\s*-->\s*(\d{1,2}:\d{2}:\d{2}[,.]\d{3})(?:\s+.*)?$"
)

_INDEX_LINE_RE = re.compile(r"^\s*(\d+)\s*$")


def normalize_timestamp(ts: str) -> str:
    """تبدیل تایم‌استمپ به قالب استاندارد HH:MM:SS,mmm با سه رقم اعشار و ویرگول."""
    ts = ts.strip().replace(".", ",")
    parts = ts.split(":")
    if len(parts) == 3:
        hours = parts[0].zfill(2)
        minutes = parts[1].zfill(2)
        sec_ms = parts[2].split(",")
        sec = sec_ms[0].zfill(2)
        ms = sec_ms[1].ljust(3, "0")[:3] if len(sec_ms) > 1 else "000"
        return f"{hours}:{minutes}:{sec},{ms}"
    return ts


class SrtParser:
    """کلاس پارس و سریال‌سازی فایل‌های SRT با تحمل خطاهای رایج فرمت."""

    @classmethod
    def parse_text(cls, content: str, filename: str = "subtitles.srt") -> SubtitleDocument:
        """پارس محتوای متنی فایل SRT به ساختار شیءگرا."""
        # حذف کاراکتر BOM در صورت وجود
        if content.startswith("\ufeff"):
            content = content[1:]

        # استانداردسازی شکست خطوط
        content = content.replace("\r\n", "\n").replace("\r", "\n")
        lines = content.split("\n")

        cues: list[SubtitleCue] = []
        i = 0
        n = len(lines)
        current_index = 1

        while i < n:
            line = lines[i].strip()
            if not line:
                i += 1
                continue

            # گام ۱: بررسی آیا این خط شماره بلاک است یا مستقیماً تایم‌کد
            tc_match = _TIMECODE_LINE_RE.match(line)
            cue_index = current_index

            if _INDEX_LINE_RE.match(line) and not tc_match:
                # ممکن است خط بعدی تایم‌کد باشد
                if i + 1 < n and _TIMECODE_LINE_RE.match(lines[i + 1].strip()):
                    try:
                        cue_index = int(line)
                    except ValueError:
                        cue_index = current_index
                    i += 1
                    line = lines[i].strip()
                    tc_match = _TIMECODE_LINE_RE.match(line)

            if not tc_match:
                # اگر خط جاری خط زمان‌بندی نبود، ادامه بده
                i += 1
                continue

            start_raw, end_raw = tc_match.group(1), tc_match.group(2)
            start_ts = normalize_timestamp(start_raw)
            end_ts = normalize_timestamp(end_raw)

            # گام ۲: جمع‌آوری متن بلاک تا رسیدن به خط خالی یا بلاک بعدی
            i += 1
            text_lines = []
            while i < n:
                curr = lines[i]
                stripped = curr.strip()
                if not stripped:
                    # پایان این بلاک زیرنویس
                    break
                # اگر خط تایم‌کد دیگری بدون خط خالی دیده شد
                if _TIMECODE_LINE_RE.match(stripped) or (
                    _INDEX_LINE_RE.match(stripped)
                    and i + 1 < n
                    and _TIMECODE_LINE_RE.match(lines[i + 1].strip())
                ):
                    break
                text_lines.append(curr)
                i += 1

            text = "\n".join(text_lines).strip()
            cues.append(
                SubtitleCue(
                    index=current_index,
                    start_time=start_ts,
                    end_time=end_ts,
                    text=text,
                )
            )
            current_index += 1

        if not cues:
            raise ValueError(f"هیچ بلاک زیرنویس معتبری در محتوای «{filename}» یافت نشد.")

        return SubtitleDocument(filename=filename, cues=cues)

    @classmethod
    def parse_file(cls, path: Union[str, Path]) -> SubtitleDocument:
        """خواندن و پارس فایل زیرنویس از دیسک با تشخیص خودکار انکودینگ."""
        p = Path(path)
        if not p.is_file():
            raise FileNotFoundError(f"فایل زیرنویس «{p}» وجود ندارد.")

        raw_bytes = p.read_bytes()
        # تلاش برای انکودینگ‌های رایج
        encodings = ["utf-8-sig", "utf-8", "cp1256", "latin-1"]
        content = ""
        used_encoding = "utf-8"

        for enc in encodings:
            try:
                content = raw_bytes.decode(enc)
                used_encoding = enc
                break
            except UnicodeDecodeError:
                continue

        if not content:
            content = raw_bytes.decode("utf-8", errors="replace")

        doc = cls.parse_text(content, filename=p.name)
        doc.raw_encoding = used_encoding
        return doc

    @classmethod
    def serialize(
        cls,
        doc_or_cues: Union[SubtitleDocument, list[SubtitleCue]],
        use_translated: bool = True,
        apply_bidi_fix: bool = True,
    ) -> str:
        """تبدیل لیست بلاک‌ها به خروجی رشته‌ای با استاندارد رسمی SRT."""
        cues = doc_or_cues.cues if isinstance(doc_or_cues, SubtitleDocument) else doc_or_cues
        blocks = []

        for idx, cue in enumerate(cues, start=1):
            text = cue.get_output_text() if use_translated else cue.clean_text
            if apply_bidi_fix and use_translated:
                text = fix_bidi_text(text)
            # هر بلاک شامل: شماره، زمان‌بندی و متن
            block = f"{idx}\r\n{cue.start_time} --> {cue.end_time}\r\n{text}"
            blocks.append(block)

        return "\r\n\r\n".join(blocks) + "\r\n"

    @classmethod
    def write_file(
        cls,
        doc_or_cues: Union[SubtitleDocument, list[SubtitleCue]],
        output_path: Union[str, Path],
        use_translated: bool = True,
        apply_bidi_fix: bool = True,
    ) -> Path:
        """ذخیره زیرنویس در فایل دیسک با انکودینگ UTF-8 استاندارد."""
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        content = cls.serialize(
            doc_or_cues, use_translated=use_translated, apply_bidi_fix=apply_bidi_fix
        )
        out.write_text(content, encoding="utf-8")
        return out
