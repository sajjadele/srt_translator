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

# پرامپت سیستمی بهینه‌سازی‌شده برای زیرنویس‌های دانشگاهی
SYSTEM_PROMPT_TEMPLATE = """You are an elite academic English-to-Persian translator specializing in university lectures and scientific courses.

Target Academic Discipline / Subject: {TOPIC}

GUIDELINES FOR ACADEMIC SUBTITLE TRANSLATION:
1. NATURAL ACADEMIC FLUENCY (فارسی سلیس و دانشگاهی):
   - Output must be fluent, natural, formal, and publishable Persian suitable for Iranian university students.
   - Strictly AVOID awkward literal, word-by-word, or machine-translated structures.
   - Combine the cues mentally into full English sentences before translating, then distribute the Persian translation naturally across the cue keys (C1, C2, etc.) so that the sentence flows smoothly across video subtitles.

2. TERMINOLOGY & TECHNICAL JARGON (واژگان تخصصی):
   - Only domain-specific scientific and engineering terms (e.g., Equilibrium, Statics, Stress, Strain, Loss Function, Backpropagation, Eigenvalue) should be treated with academic terminology care.
   - For major technical terms, provide the standard Iranian academic equivalent, optionally followed by the English term in parentheses at first mention (e.g., 'استاتیک (Statics)', 'تعادل (Equilibrium)').
   - NEVER put parenthesized English for basic everyday words (such as chapter, very, for, memory, problem, like, today). Translate common words into standard Persian directly!

3. FORMULAS & SPECIAL NOTATION:
   - Preserve equations ($F = ma$, $\\sigma = E \\cdot \\epsilon$), numbers, coordinate notations (2D, 3D), and mathematical symbols exactly as they are without distortion.

4. STRICT JSON OUTPUT FORMAT:
   - You MUST output a strictly valid JSON object mapping every single cue key (C1, C2, ..., Cn) to its translated Persian text.
   - Every cue key provided in cues_to_translate MUST be present in the output.
   - Output raw JSON only. Do not add markdown backticks, explanations, or greeting.
{GLOSSARY_SECTION}"""


def _extract_json_from_response(raw_text: str) -> dict[str, str]:
    """استخراج و تمیزکاری دیکشنری JSON از پاسخ مدل."""
    text = raw_text.strip()
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    # خنثی‌سازی بک‌اسلش‌های فرمول‌های ریاضی و لاتک (مانند \Sigma یا \theta) که در JSON معتبر نیستند
    cleaned_text = re.sub(r'\\([^"\\/bfnrtu])', r'\\\\\1', text)

    try:
        data = json.loads(cleaned_text)
        if isinstance(data, dict):
            return {str(k): str(v) for k, v in data.items()}
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", cleaned_text, re.DOTALL)
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
        max_retries_per_model: int = 4,
        glossary_manager: Optional[GlossaryManager] = None,
        inter_batch_delay: Optional[float] = None,
    ):
        self.base_url = (base_url or settings.llm_base_url).rstrip("/")
        self.api_key = api_key or settings.llm_api_key
        self.models = models or settings.llm_models
        self.timeout = timeout or settings.request_timeout
        self.max_retries_per_model = max_retries_per_model
        self.glossary = glossary_manager or GlossaryManager()
        self.inter_batch_delay = (
            inter_batch_delay if inter_batch_delay is not None else settings.inter_batch_delay
        )
        self._exhausted_models: set[str] = set()

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
            payload["previous_dialogue_context"] = batch.pre_context
        if batch.post_context:
            payload["upcoming_dialogue_context"] = batch.post_context

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
            "response_format": {"type": "json_object"},
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

        last_error_str: str = "Unknown error"

        try:
            for model_name in self.models:
                if model_name in self._exhausted_models:
                    continue

                for attempt in range(self.max_retries_per_model):
                    try:
                        log.info(
                            f"در حال ترجمه دسته {batch.batch_index} با مدل {model_name} (تلاش {attempt + 1}/{self.max_retries_per_model})..."
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
                                await asyncio.sleep(2.0)
                                continue
                            break

                        # موفقیت در ترجمه
                        return {k: parsed_dict[k] for k in expected_keys}

                    except Exception as ex:
                        err_name = type(ex).__name__
                        err_msg = str(ex) or "Timeout or network dropped"
                        last_error_str = f"[{model_name}] {err_name}: {err_msg}"
                        log.warning(
                            f"خطا در مدل {model_name} (تلاش {attempt + 1}): {last_error_str}"
                        )

                        # در صورت اتمام سقف روزانه، معطل نمان و بلافاصله به مدل بعدی سوئیچ کن
                        is_daily_exhausted = (
                            "per day" in err_msg.lower()
                            or "perday" in err_msg.lower()
                            or "retry in" in err_msg.lower()
                            or ("quota exceeded" in err_msg.lower() and "429" in err_msg)
                        )
                        if is_daily_exhausted:
                            log.warning(
                                f"سقف روزانه مدل {model_name} تمام شده است. سوئیچ فوری به مدل بعدی در زنجیره..."
                            )
                            self._exhausted_models.add(model_name)
                            break

                        # مدیریت هوشمند انواع خطاها: خطای ۴۲۹ (Rate Limit لحظه‌ای) و خطای ۵۰۳ (ترافیک لحظه‌ای سرور)
                        is_overloaded = (
                            "429" in err_msg
                            or "503" in err_msg
                            or "unavailable" in err_msg.lower()
                            or "high demand" in err_msg.lower()
                            or "rate" in err_msg.lower()
                            or "resource_exhausted" in err_msg.lower()
                        )
                        wait_seconds = (7.0 * (attempt + 1)) if is_overloaded else (2.0 * (attempt + 1))

                        if attempt < self.max_retries_per_model - 1:
                            log.info(f"صبر به مدت {wait_seconds:.1f} ثانیه قبل از تلاش مجدد...")
                            await asyncio.sleep(wait_seconds)
                            continue
                        break

            raise RuntimeError(
                f"همه مدل‌های موجود در زنجیره fallback شکست خوردند. آخرین خطا: {last_error_str}"
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
                trans_map = await self.translate_batch(batch, ctx, client=client)

                for i, cue in enumerate(batch.cues):
                    key = f"C{i + 1}"
                    cue.translated_text = trans_map.get(key, cue.clean_text)

                translated_so_far += len(batch.cues)
                progress_pct = (translated_so_far / total_cues) * 100.0

                if on_progress:
                    await on_progress(progress_pct, translated_so_far, total_cues)

                # مکث هوشمند بین بسته‌ها جهت رعایت سقف نرخ درخواست (RPM) در ارائه‌دهندگان رایگان (نظیر جمنای)
                await asyncio.sleep(self.inter_batch_delay)

        return doc
