"""موتور ترجمه هوشمند زیرنویس — پیاده‌سازی تماس با روتر LLM، زنجیره Fallback و اعتبارسنجی تطابق خروجی."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Awaitable, Callable, Optional

import httpx

from .batcher import ContextBatcher
from .glossary import GlossaryManager
from .models import AcademicContext, SubtitleDocument, TranslationBatch
from ..config import settings

log = logging.getLogger("srt_translator.engine")

# پرامپت سیستمی مادر بر اساس اصول ترجمان و ماهیت زیرنویس‌های آکادمیک
SYSTEM_PROMPT_TEMPLATE = """You are an elite academic English-to-Persian translator specializing in university-level lectures and scientific courses.

Target Academic Domain: {TOPIC}

CRITICAL RULES:
1. SMART-PERSIAN TERMINOLOGY CONTRACT:
   - Keep established technical terms, function/variable names, keywords, and acronyms in English inline (e.g. Backpropagation, Loss Function, Eigenvalue, Gradient Descent, Manifold, CNN, Overfitting).
   - A widely accepted Persian equivalent may appear at most once, in parentheses, at the term's first occurrence.
2. SENTENCE COHESION & ANTI-FRAGMENTATION:
   - English sentences in subtitles are frequently sliced across multiple cues. In Persian, verbs go at the end of sentences (SOV order).
   - Read the entire contextual window (including pre_context and post_context) to understand full complete thoughts before translating.
   - Distribute the translated Persian sentences across the active cues naturally and smoothly.
3. PRESERVE FORMULAS & SYMBOLS:
   - Do NOT translate, modify, or flip mathematical formulas ($x_i$, $\\theta$, $O(n \\log n)$), numbers, programming code statements, or punctuation.
4. STRICT STRUCTURED OUTPUT:
   - You MUST output a strictly valid JSON object mapping every single cue key (C1, C2, ...) to its translated Persian text.
   - Do NOT include markdown code fences (```json), greetings, or extra explanations. Output raw JSON only.
{GLOSSARY_SECTION}"""


def _extract_json_from_response(raw_text: str) -> dict[str, str]:
    """استخراج و تمیزکاری دیکشنری JSON از پاسخ مدل."""
    text = raw_text.strip()
    # حذف تگ‌های احتمالی مارک‌داون
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    # تلاش برای پارس مستقیم
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return {str(k): str(v) for k, v in data.items()}
    except json.JSONDecodeError:
        pass

    # تلاش با regex برای یافتن آکولادها
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(0))
            if isinstance(data, dict):
                return {str(k): str(v) for k, v in data.items()}
        except json.JSONDecodeError:
            pass

    raise ValueError(f"پاسخ مدل به فرمت معتبر JSON تبدیل نشد: {text[:200]}...")


class TranslationEngine:
    """موتور ترجمه آسنکرون با پشتیبانی از چند مدل، زنجیره Fallback و Retry هوشمند."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        models: Optional[list[str]] = None,
        timeout: Optional[float] = None,
        max_retries_per_model: int = 2,
        glossary_manager: Optional[GlossaryManager] = None,
    ):
        self.base_url = (base_url or settings.llm_base_url).rstrip("/")
        self.api_key = api_key or settings.llm_api_key
        self.models = models or settings.llm_models
        self.timeout = timeout or settings.request_timeout
        self.max_retries_per_model = max_retries_per_model
        self.glossary = glossary_manager or GlossaryManager()

    def _build_system_prompt(self, batch: TranslationBatch, context: AcademicContext) -> str:
        """ایجاد پرامپت سیستمی سفارشی بر اساس موضوع و اصطلاحات مرتبط."""
        all_text = " ".join(cue.clean_text for cue in batch.cues)
        relevant_terms = self.glossary.find_relevant_terms(
            all_text, custom_glossary=context.glossary
        )
        glossary_sec = ""
        if relevant_terms:
            glossary_sec = "\n" + self.glossary.format_glossary_prompt(relevant_terms)

        topic = context.topic or batch.academic_topic or "General Academic"
        return SYSTEM_PROMPT_TEMPLATE.format(TOPIC=topic, GLOSSARY_SECTION=glossary_sec)

    def _build_user_payload(self, batch: TranslationBatch) -> str:
        """ایجاد بدنه پیام کاربر شامل زمینه و بلاک‌های هدف."""
        payload = {
            "cues_to_translate": batch.get_cues_map(),
        }
        if batch.pre_context:
            payload["pre_context_dialogue"] = batch.pre_context
        if batch.post_context:
            payload["post_context_dialogue"] = batch.post_context

        return json.dumps(payload, ensure_ascii=False, indent=2)

    async def _call_llm_api(self, client: httpx.AsyncClient, model: str, system_prompt: str, user_payload: str) -> str:
        """ارسال درخواست به اندپوینت chat/completions."""
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        body = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_payload},
            ],
            "temperature": 0.2,
        }

        resp = await client.post(url, json=body, headers=headers, timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]

    async def translate_batch(
        self,
        batch: TranslationBatch,
        context: AcademicContext,
        client: Optional[httpx.AsyncClient] = None,
    ) -> dict[str, str]:
        """ترجمه یک دسته از بلاک‌ها با Retry داخلی و پیمایش زنجیره Fallback در صورت بروز خطا."""
        system_prompt = self._build_system_prompt(batch, context)
        user_payload = self._build_user_payload(batch)
        expected_keys = set(batch.cue_keys)

        close_client = False
        if client is None:
            client = httpx.AsyncClient()
            close_client = True

        last_error: Optional[Exception] = None

        try:
            for model_name in self.models:
                for attempt in range(self.max_retries_per_model):
                    try:
                        log.info(
                            f"در حال ترجمه دسته {batch.batch_index} با مدل {model_name} (تلاش {attempt + 1})..."
                        )
                        raw_resp = await self._call_llm_api(client, model_name, system_prompt, user_payload)
                        parsed_dict = _extract_json_from_response(raw_resp)

                        # اعتبارسنجی تطابق کلیدها
                        missing = expected_keys - set(parsed_dict.keys())
                        if missing:
                            log.warning(
                                f"مدل {model_name} کلیدهای {missing} را بازنگرداند."
                            )
                            if attempt < self.max_retries_per_model - 1:
                                await asyncio.sleep(1.0)
                                continue
                            break  # رفتن به مدل بعدی

                        # موفقیت در ترجمه
                        return {k: parsed_dict[k] for k in expected_keys}

                    except Exception as ex:
                        log.warning(
                            f"خطا در مدل {model_name} (تلاش {attempt + 1}): {ex}"
                        )
                        last_error = ex
                        if attempt < self.max_retries_per_model - 1:
                            await asyncio.sleep(1.5 * (attempt + 1))
                            continue
                        break  # تلاش‌های این مدل پایان یافت، برو به مدل بعدی

            # اگر همه مدل‌ها پس از تمام تلاش‌ها شکست خوردند
            raise RuntimeError(
                f"همه مدل‌های موجود در زنجیره fallback شکست خوردند. آخرین خطا: {last_error}"
            )
        finally:
            if close_client:
                await client.aclose()

    async def translate_document(
        self,
        doc: SubtitleDocument,
        context: Optional[AcademicContext] = None,
        on_progress: Optional[Callable[[float, int, int], Awaitable[None]]] = None,
        batcher: Optional[ContextBatcher] = None,
    ) -> SubtitleDocument:
        """ترجمه کامل یک سند زیرنویس با مدیریت پیشرفت و گزارش درصد."""
        ctx = context or AcademicContext()
        b_mgr = batcher or ContextBatcher()
        batches = b_mgr.create_batches(doc.cues, context=ctx)

        total_cues = doc.total_cues
        translated_so_far = 0

        async with httpx.AsyncClient() as client:
            for batch in batches:
                # ترجمه این دسته
                trans_map = await self.translate_batch(batch, ctx, client=client)

                # انتساب ترجمه به بلاک‌ها
                for i, cue in enumerate(batch.cues):
                    key = f"C{i + 1}"
                    cue.translated_text = trans_map.get(key, cue.clean_text)

                translated_so_far += len(batch.cues)
                progress_pct = (translated_so_far / total_cues) * 100.0

                if on_progress:
                    await on_progress(progress_pct, translated_so_far, total_cues)

        return doc
