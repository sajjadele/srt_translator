"""ماژول تخصصی اصلاح چیدمان متن دوجهته (BiDi) برای زیرنویس‌های فارسی.

این ماژول با تزریق هوشمند کاراکترهای نامرئی یونیکد (RLM و LRM)، مشکل چپ‌چین شدن و به‌هم‌ریختگی
پرانتزهای معادل‌های انگلیسی در پخش‌کننده‌های ویدیو (مانند VLC، PotPlayer، تلویزیون‌ها و مرورگرها) را
به طور کامل و دائمی برطرف می‌کند.
"""

from __future__ import annotations

import re

# کاراکترهای نامرئی استاندارد یونیکد جهت مدیریت دوجهته (BiDi)
RLM = "\u200F"  # Right-to-Left Mark (نشانگر قوی راست‌به‌چپ)
LRM = "\u200E"  # Left-to-Right Mark (نشانگر قوی چپ‌به‌راست)

_PERSIAN_CHAR_RE = re.compile(r"[\u0600-\u06FF\uFB50-\uFDFF\uFE70-\uFEFF]")
_PAREN_ENGLISH_RE = re.compile(r"\(([^)]*[a-zA-Z][^)]*)\)")


def fix_bidi_text(text: str) -> str:
    """اصلاح چیدمان دوجهته (BiDi) برای متن زیرنویس فارسی دارای عبارات انگلیسی.
    
    اقدامات:
    ۱. ایزوله‌سازی پرانتزهای دارای عبارات لاتین با RLM و LRM تا پرانتزها برعکس نشده و به سمت مخالف نپرند.
    ۲. تزریق RLM در ابتدای هر خط به عنوان لنگر قطعی راست‌به‌چپ تا خطوطی که با پرانتز، عدد یا کلمه انگلیسی
       شروع می‌شوند در پلیرها چپ‌چین نشوند.
    """
    if not text or not _PERSIAN_CHAR_RE.search(text):
        return text

    # گام ۱: احاطه پرانتزهای انگلیسی با نشانگرهای کنترلی جهت متن
    def _fix_parens(match: re.Match) -> str:
        inner = match.group(1).strip()
        # حذف هرگونه LRM/RLM تکراری قبلی در صورت وجود
        inner_clean = inner.replace(RLM, "").replace(LRM, "")
        return f"{RLM}({LRM}{inner_clean}{LRM}){RLM}"

    processed = _PAREN_ENGLISH_RE.sub(_fix_parens, text)

    # گام ۲: قرار دادن RLM در ابتدای هر خط به عنوان لنگر پایه‌ای RTL
    lines = processed.split("\n")
    fixed_lines = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            fixed_lines.append(line)
            continue
        if not stripped.startswith(RLM):
            fixed_lines.append(f"{RLM}{stripped}")
        else:
            fixed_lines.append(stripped)

    return "\n".join(fixed_lines)
