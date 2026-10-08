"""مدیریت واژه‌نامه تخصصی و اصطلاحات دانشگاهی برای بهبود دقت ترجمه."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Optional

from ..config import settings

log = logging.getLogger("srt_translator.glossary")


class GlossaryManager:
    """مدیریت دیکشنری تخصصی و استخراج اصطلاحات مرتبط با متن هر بخش."""

    def __init__(self, dict_path: Optional[Path] = None):
        self.dict_path = dict_path or settings.dict_path
        self._base_dict: dict[str, list[str]] = {}
        self._load_base_dictionary()

    def _load_base_dictionary(self) -> None:
        """بارگذاری دیکشنری پایه از فایل JSON."""
        if not self.dict_path.is_file():
            log.warning(f"فایل واژه‌نامه در «{self.dict_path}» یافت نشد.")
            return

        try:
            with open(self.dict_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    self._base_dict = data
                    log.info(f"واژه‌نامه پایه با {len(self._base_dict)} اصطلاح بارگذاری شد.")
        except Exception as e:
            log.error(f"خطا در بارگذاری واژه‌نامه: {e}")

    def find_relevant_terms(
        self,
        text_corpus: str,
        custom_glossary: Optional[dict[str, str]] = None,
        max_terms: int = 25,
    ) -> dict[str, str]:
        """
        جستجوی اصطلاحات تخصصی موجود در متن برای ارسال هدفمند به مدل در قالب پرامپت.
        اولویت با واژه‌نامه اختصاصی کاربر (custom_glossary) است.
        """
        matched: dict[str, str] = {}

        # اولویت ۱: اصطلاحات سفارشی کاربر
        if custom_glossary:
            for en_term, fa_term in custom_glossary.items():
                if re.search(r"\b" + re.escape(en_term) + r"\b", text_corpus, re.IGNORECASE):
                    matched[en_term] = fa_term

        # اولویت ۲: واژه‌نامه پایه پروژه
        text_lower = text_corpus.lower()
        count = len(matched)

        # مرتب‌سازی واژه‌ها بر اساس طول برای تطبیق عبارات چندکلمه‌ای 먼저
        for en_term, fa_candidates in self._base_dict.items():
            if count >= max_terms:
                break
            if en_term in matched or len(en_term) < 3:
                continue

            # جستجوی مرز کلمه
            pattern = r"\b" + re.escape(en_term.lower()) + r"\b"
            if re.search(pattern, text_lower):
                # انتخاب بهترین معادل
                fa_val = fa_candidates[0] if isinstance(fa_candidates, list) and fa_candidates else str(fa_candidates)
                matched[en_term] = fa_val
                count += 1

        return matched

    def format_glossary_prompt(self, terms: dict[str, str]) -> str:
        """فرمت‌بندی اصطلاحات برای درج درون پرامپت مدل."""
        if not terms:
            return ""

        lines = ["MANDATORY TERMINOLOGY MAPPINGS:"]
        for en, fa in terms.items():
            lines.append(f"- {en} -> {fa}")
        return "\n".join(lines)
