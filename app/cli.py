"""رابط خط فرمان (CLI) برای ترجمه مستقیم و محلی زیرنویس بدون نیاز به تلگرام."""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

from .config import settings
from .core.batcher import ContextBatcher
from .core.engine import TranslationEngine
from .core.models import AcademicContext
from .core.srt_parser import SrtParser


def _render_cli_progress(pct: float, done: int, total: int) -> None:
    """رندر نوار پیشرفت در محیط ترمینال."""
    bar_len = 30
    filled = int(bar_len * (pct / 100.0))
    bar = "=" * filled + (">" if filled < bar_len else "") + " " * (bar_len - filled - (1 if filled < bar_len else 0))
    sys.stdout.write(f"\r⏳ پیشرفت: [{bar}] {pct:5.1f}% ({done}/{total} بلاک)")
    sys.stdout.flush()


async def async_main(args: argparse.Namespace) -> int:
    input_path = Path(args.input)
    if not input_path.is_file():
        print(f"❌ خطا: فایل ورودی «{input_path}» یافت نشد.", file=sys.stderr)
        return 1

    # تعیین مسیر فایل خروجی
    if args.output:
        output_path = Path(args.output)
    else:
        output_path = input_path.parent / f"{input_path.stem}_fa.srt"

    print(f"📂 در حال خواندن فایل «{input_path.name}»...")
    try:
        doc = SrtParser.parse_file(input_path)
    except Exception as e:
        print(f"❌ خطا در پارس فایل SRT: {e}", file=sys.stderr)
        return 1

    print(f"📊 تعداد کل بلاک‌های زیرنویس: {doc.total_cues}")
    print(f"📚 زمینه موضوعی: {args.topic}")

    context = AcademicContext(topic=args.topic)
    batcher = ContextBatcher(batch_size=args.batch_size)
    engine = TranslationEngine()

    start_time = time.time()

    async def on_progress(pct: float, done: int, total: int) -> None:
        _render_cli_progress(pct, done, total)

    print("🚀 شروع فرآیند ترجمه هوشمند...")
    try:
        translated_doc = await engine.translate_document(
            doc,
            context=context,
            on_progress=on_progress,
            batcher=batcher,
        )
        print()  # خط جدید پس از اتمام نوار پیشرفت
    except Exception as e:
        print(f"\n❌ خطای فرآیند ترجمه: {e}", file=sys.stderr)
        return 1

    elapsed = time.time() - start_time
    SrtParser.write_file(translated_doc, output_path, use_translated=True)

    print(f"✅ ترجمه با موفقیت انجام شد!")
    print(f"⏱ زمان کل: {elapsed:.1f} ثانیه")
    print(f"💾 فایل خروجی ذخیره شد در: {output_path.resolve()}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Academic SRT Subtitle Translator — ترجمه تخصصی زیرنویس به زبان فارسی"
    )
    parser.add_argument("input", help="مسیر فایل زیرنویس ورودی (.srt)")
    parser.add_argument("-o", "--output", help="مسیر ذخیره فایل خروجی (.srt)")
    parser.add_argument("--topic", default="General Academic", help="زمینه یا درس دانشگاهی (مثلاً Machine Learning)")
    parser.add_argument("--batch-size", type=int, default=settings.batch_size, help="تعداد بلاک در هر دسته")

    args = parser.parse_args()
    exit_code = asyncio.run(async_main(args))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
