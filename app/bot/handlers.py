"""کنترل‌کننده‌ها و هندلرهای رویدادهای بات تلگرام."""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import time
from pathlib import Path
from typing import Dict

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, FSInputFile, Message

from ..config import settings
from ..core.batcher import ContextBatcher
from ..core.engine import TranslationEngine
from ..core.models import AcademicContext
from ..core.srt_parser import SrtParser
from .keyboards import get_topics_keyboard

log = logging.getLogger("srt_translator.bot")
router = Router()

# نگهداری کانتکست فعال هر کاربر در حافظه: user_id -> AcademicContext
_USER_CONTEXTS: Dict[int, AcademicContext] = {}

# دایرکتوری موقت برای دانلود و تبدیل فایل‌ها
TEMP_DIR = settings.base_dir / "data" / "temp"
TEMP_DIR.mkdir(parents=True, exist_ok=True)


def get_user_context(user_id: int) -> AcademicContext:
    if user_id not in _USER_CONTEXTS:
        _USER_CONTEXTS[user_id] = AcademicContext(topic="General Academic")
    return _USER_CONTEXTS[user_id]


def _format_progress_bar(pct: float, done: int, total: int) -> str:
    """تولید نوار پیشرفت گرافیکی در متن پیام تلگرام."""
    bar_len = 10
    filled = int(bar_len * (pct / 100.0))
    bar = "█" * filled + "░" * (bar_len - filled)
    return f"⏳ **در حال ترجمه تخصصی:**\n`[{bar}]` **{pct:.1f}%** ({done} از {total} بلاک)"


@router.message(CommandStart())
async def handle_start(message: Message) -> None:
    """پیام خوش‌آمدگویی و راهنمای شروع."""
    user = message.from_user
    ctx = get_user_context(user.id if user else 0)

    text = (
        f"سلام {user.first_name if user else 'دوست گرامی'}! 👋\n\n"
        "به **ربات مترجم تخصصی زیرنویس دانشگاهی** خوش آمدید.\n\n"
        "این ربات فایل‌های زیرنویس انگلیسی (`.srt`) ویدیوهای آموزشی و دروس دانشگاهی را با دقت بالا "
        "و با حفظ کامل زمان‌بندی (Sync) به فارسی ترجمه می‌کند.\n\n"
        f"🎯 **زمینه فعلی شما:** `{ctx.topic}`\n\n"
        "💡 **نحوه استفاده:**\n"
        "۱. می‌توانید از دکمه‌های زیر زمینه درس را انتخاب کنید یا با دستور `/topic [نام درس]` آن را تغییر دهید.\n"
        "۲. سپس فایل زیرنویس انگلیسی خود (`.srt`) را ارسال کنید."
    )
    await message.answer(text, reply_markup=get_topics_keyboard(), parse_mode="Markdown")


@router.message(Command("help"))
async def handle_help(message: Message) -> None:
    text = (
        "📖 **راهنمای ربات:**\n\n"
        "🔹 **تغییر موضوع درس:**\n"
        "ارسال دستور `/topic` همراه با نام درس، مثلاً:\n"
        "`/topic Quantum Mechanics`\n"
        "`/topic Microeconomics`\n\n"
        "🔹 **ارسال زیرنویس:**\n"
        "کافی است فایل با پسوند `.srt` را به صورت Document ارسال کنید.\n\n"
        "🔹 **اصول ترجمه:**\n"
        "• اصطلاحات تخصصی استاندارد دانشگاهی حفظ یا با پرانتز درج می‌شوند.\n"
        "• تایم‌کدها و همگامی صدا و تصویر دست‌نخورده باقی می‌مانند."
    )
    await message.answer(text, parse_mode="Markdown")


@router.message(Command("topic"))
async def handle_topic_command(message: Message) -> None:
    """تغییر زمینه موضوعی با دستور متنی."""
    user_id = message.from_user.id if message.from_user else 0
    args = (message.text or "").split(maxsplit=1)

    if len(args) > 1 and args[1].strip():
        new_topic = args[1].strip()
        ctx = get_user_context(user_id)
        ctx.topic = new_topic
        await message.answer(f"✅ زمینه موضوعی با موفقیت به **«{new_topic}»** تغییر یافت.", parse_mode="Markdown")
    else:
        ctx = get_user_context(user_id)
        await message.answer(
            f"🎯 زمینه فعلی: `{ctx.topic}`\n\nلطفاً یکی از گزینه‌های زیر را انتخاب کنید یا دستور را به همراه موضوع بنویسید:\n`/topic Machine Learning`",
            reply_markup=get_topics_keyboard(),
            parse_mode="Markdown",
        )


@router.callback_query(F.data.startswith("topic:"))
async def handle_topic_callback(callback: CallbackQuery) -> None:
    """انتخاب زمینه موضوعی از دکمه‌های شیشه‌ای."""
    user_id = callback.from_user.id
    if not callback.data:
        return

    topic_val = callback.data.split(":", 1)[1]
    ctx = get_user_context(user_id)
    ctx.topic = topic_val

    await callback.answer(f"موضوع به {topic_val} تنظیم شد.")
    if callback.message and isinstance(callback.message, Message):
        await callback.message.edit_text(
            f"✅ زمینه موضوعی ترجمه به **«{topic_val}»** تنظیم شد.\n\nحالا می‌توانید فایل `.srt` خود را ارسال کنید.",
            reply_markup=get_topics_keyboard(),
            parse_mode="Markdown",
        )


@router.message(F.document)
async def handle_srt_document(message: Message) -> None:
    """دریافت، اعتبارسنجی و پردازش فایل زیرنویس ارسالی."""
    doc_file = message.document
    if not doc_file or not doc_file.file_name:
        return

    filename = doc_file.file_name
    if not filename.lower().endswith(".srt"):
        await message.reply(
            "⚠️ فرمت فایل نامعتبر است! لطفاً فقط فایل زیرنویس با پسوند **`.srt`** ارسال کنید.",
            parse_mode="Markdown",
        )
        return

    user_id = message.from_user.id if message.from_user else 0
    ctx = get_user_context(user_id)

    # ایجاد پوشه کار موقت اختصاصی برای این جاب
    job_id = f"{user_id}_{int(time.time())}"
    job_dir = TEMP_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    input_path = job_dir / filename
    output_filename = f"{Path(filename).stem}_fa.srt"
    output_path = job_dir / output_filename

    status_msg = await message.reply(
        f"📥 **دریافت شد:** `{filename}`\n"
        f"📚 **موضوع درس:** `{ctx.topic}`\n\n"
        "⏳ در حال دانلود و اعتبارسنجی فایل...",
        parse_mode="Markdown",
    )

    start_time = time.time()
    try:
        # دانلود فایل از تلگرام
        bot = message.bot
        if not bot:
            raise RuntimeError("Bot instance is unavailable.")

        await bot.download(doc_file, destination=input_path)

        # پارس اولیه
        subtitle_doc = SrtParser.parse_file(input_path)
        total_cues = subtitle_doc.total_cues

        await status_msg.edit_text(
            f"📥 **فایل:** `{filename}`\n"
            f"📊 **تعداد بلاک‌ها:** {total_cues}\n"
            f"📚 **موضوع درس:** `{ctx.topic}`\n\n"
            f"🚀 **شروع فرآیند ترجمه هوشمند...**",
            parse_mode="Markdown",
        )

        last_update_time = 0.0

        async def on_progress(pct: float, done: int, total: int) -> None:
            nonlocal last_update_time
            now = time.time()
            # کنترل نرخ ویرایش پیام (حداقل ۳ ثانیه فاصله بین ویرایش‌ها جهت رعایت محدودیت تلگرام)
            if (now - last_update_time >= 3.0) or (done == total):
                last_update_time = now
                progress_text = (
                    f"📥 **فایل:** `{filename}`\n"
                    f"📚 **موضوع درس:** `{ctx.topic}`\n\n"
                    + _format_progress_bar(pct, done, total)
                )
                try:
                    await status_msg.edit_text(progress_text, parse_mode="Markdown")
                except Exception as e:
                    log.debug(f"Progress message edit throttled: {e}")

        # اجرای ترجمه
        engine = TranslationEngine()
        batcher = ContextBatcher()
        translated_doc = await engine.translate_document(
            subtitle_doc, context=ctx, on_progress=on_progress, batcher=batcher
        )

        # ذخیره فایل ترجمه شده
        SrtParser.write_file(translated_doc, output_path, use_translated=True)
        elapsed = time.time() - start_time

        # ارسال فایل نهایی برای کاربر
        caption = (
            f"✅ **ترجمه تخصصی پایان یافت!**\n\n"
            f"🎯 **تعداد بلاک‌های همگام:** {total_cues}\n"
            f"⏱ **مدت زمان:** {elapsed:.1f} ثانیه\n"
            f"📚 **زمینه درسی:** {ctx.topic}"
        )
        final_doc = FSInputFile(path=output_path, filename=output_filename)
        await message.reply_document(document=final_doc, caption=caption, parse_mode="Markdown")

        # به‌روزرسانی پیام وضعیت
        await status_msg.edit_text("✨ فرآیند ترجمه با موفقیت تکمیل شد و فایل برای شما ارسال گردید.")

    except Exception as exc:
        log.error(f"خطا در پردازش زیرنویس برای کاربر {user_id}: {exc}", exc_info=True)
        await status_msg.edit_text(
            f"❌ **متأسفانه در فرآیند ترجمه خطایی رخ داد:**\n`{str(exc)}`\n\n"
            "لطفاً از صحت فایل یا کلید API اطمینان حاصل کرده و دوباره تلاش کنید.",
            parse_mode="Markdown",
        )
    finally:
        # پاک‌سازی فایل‌های موقت (T025)
        try:
            if job_dir.exists():
                shutil.rmtree(job_dir, ignore_errors=True)
        except Exception as e:
            log.warning(f"Failed to cleanup temp dir {job_dir}: {e}")
