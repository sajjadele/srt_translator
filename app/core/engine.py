"""موتور ترجمه هوشمند زیرنویس — پیاده‌سازی تماس با روتر LLM، زنجیره Fallback و اعتبارسنجی تطابق خروجی."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Awaitable, Callable, Optional

import httpx

from .batcher import ContextBatcher
from .checkpoint import CheckpointStore, snapshot_document
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
    """استخراج، تمیزکاری و بازیابی مقاوم دیکشنری JSON از پاسخ مدل."""
    text = raw_text.strip()
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    # تلاش ۱: استخراج مستقیم در صورت معتبر بودن JSON استاندارد
    try:
        data = json.loads(text, strict=False)
        if isinstance(data, dict):
            return {str(k): str(v) for k, v in data.items()}
    except json.JSONDecodeError:
        pass

    # تلاش ۲: تمیزکاری بک‌اسلش‌ها، لاتک، کاماهای اضافی و استخراج بلوک اصلی
    match = re.search(r"\{.*\}", text, re.DOTALL)
    candidate = match.group(0) if match else text

    # حذف کاماهای اضافی قبل از بسته شدن براکت یا کروشه
    cleaned = re.sub(r",\s*([\}\]])", r"\1", candidate)

    # فرار دادن \u هایی که با ۴ رقم هگزادسیمال دنبال نمی‌شوند (نظیر \unit یا \underline در لاتک)
    cleaned = re.sub(r"\\u(?![0-9a-fA-F]{4})", r"\\\\u", cleaned)

    # فرار دادن دستورات لاتک که با حروف کنترلی آغاز می‌شوند (نظیر \theta, \times, \beta, \rho, \frac, \nabla)
    cleaned = re.sub(r"\\([bfrtn][a-zA-Z])", r"\\\\\1", cleaned)

    # فرار دادن سایر بک‌اسلش‌های غیرمجاز JSON (نظیر \Sigma, \alpha, \vec, \hat, \dot)
    cleaned = re.sub(r'\\([^"\\/bfnrtu])', r"\\\\\1", cleaned)

    try:
        data = json.loads(cleaned, strict=False)
        if isinstance(data, dict):
            return {str(k): str(v) for k, v in data.items()}
    except json.JSONDecodeError:
        pass

    # تلاش ۳ (Emergency Fallback): استخراج مستقیم جفت‌کلیدهای C1..Cn از متن با Regex
    # این مکانیزم حتی در صورت وجود نقص نحوی در بدنه یا نقل‌قول‌های نامتقارن، کلیدها را بازیابی می‌کند
    pairs = re.findall(r'"(C\d+)"\s*:\s*"((?:[^"\\]|\\.)*)"', candidate, re.DOTALL)
    if pairs:
        result = {}
        for k, v in pairs:
            clean_v = v.replace('\\"', '"').replace('\\\\', '\\').replace('\\n', '\n')
            result[k] = clean_v
        return result

    # تلاش ۴: الگو با تساهل بیشتر برای رشته‌های چندخطی با کوتیشن بازمانده
    broad_pairs = re.findall(r'"(C\d+)"\s*:\s*"(.*?)"(?=\s*,\s*"C\d+"\s*:|\s*\}\s*$)', candidate, re.DOTALL)
    if broad_pairs:
        result = {}
        for k, v in broad_pairs:
            clean_v = v.replace('\\"', '"').replace('\\\\', '\\').replace('\\n', '\n')
            result[k] = clean_v
        return result

    raise ValueError(f"پاسخ مدل به فرمت معتبر JSON تبدیل نشد: {text[:300]}...")


# ---------------------------------------------------------------------------
# طبقه‌بندی خطاهای سرویس LLM
# ---------------------------------------------------------------------------

# سهمیه‌ی روزانه (Free Tier) در سطح پروژه/کلید است؛ با تعویض مدل برطرف نمی‌شود.
TRIAGE_DAILY_QUOTA = "daily_quota"
# محدودیت نرخ لحظه‌ای (RPM/TPM) — گذراست و باید دوباره تلاش شود.
TRIAGE_RATE_LIMIT = "rate_limit"
# مدل وجود ندارد یا برای این اکانت فعال نیست — تلاش مجدد فایده‌ای ندارد.
TRIAGE_MODEL_UNAVAILABLE = "model_unavailable"
# خطای غیرقابل بازیابی برای این مدل (کلید، مجوز، آرگومان نامعتبر).
TRIAGE_FATAL = "fatal"
# فشار لحظه‌ای سرور (503 / UNAVAILABLE / RESOURCE_EXHAUSTED بدون متریک مشخص).
TRIAGE_OVERLOADED = "overloaded"
# خطای گذرای نامشخص (تایم‌اوت، قطع شبکه و…).
TRIAGE_TRANSIENT = "transient"

# نشانه‌های «سقف روزانه» — باید پیش از نشانه‌های دقیقه‌ای بررسی شوند.
_DAILY_QUOTA_MARKERS = (
    "free_tier_requests",
    "requests per day",
    "per day",
    "perday",
    "per  day",
    "daily",
)

# نشانه‌های «سقف دقیقه‌ای» که با تلاش مجدد قابل بازیابی هستند.
_RATE_LIMIT_MARKERS = (
    "per minute",
    "perminute",
    "requests per minute",
    "generate_content_requests",
)

_MODEL_UNAVAILABLE_MARKERS = (
    "is no longer available",
    "not found",
    "not supported",
    "unsupported model",
    "unknown model",
)

_FATAL_MARKERS = (
    "api key not valid",
    "invalid api key",
    "unauthenticated",
    "permission denied",
    "permission_error",
    "invalid argument",
    "invalid_request_error",
)

_OVERLOADED_MARKERS = (
    "high demand",
    "unavailable",
    "overloaded",
    "internal error",
    "deadline exceeded",
)

# سقف انتظار برای تلاش مجدد؛ هر چیز بزرگ‌تر یعنی اختلال طولانی و باید به مدل بعدی برود.
_MAX_RETRY_WAIT_SECONDS = 120.0

_RETRY_IN_RE = re.compile(r"retry in\s+((?:\d+(?:\.\d+)?\s*[hms])+)", re.IGNORECASE)
_DURATION_PART_RE = re.compile(r"(\d+(?:\.\d+)?)\s*([hms])")
_DURATION_FACTORS = {"h": 3600.0, "m": 60.0, "s": 1.0}


def _parse_retry_delay(text: str) -> Optional[float]:
    """استخراج مدت انتظار پیشنهادی سرویس از متن خطا، مثل «Please retry in 18h11m8s» یا «in 24s»."""
    if not text:
        return None
    match = _RETRY_IN_RE.search(text)
    if not match:
        return None

    total = 0.0
    matched_any = False
    for value, unit in _DURATION_PART_RE.findall(match.group(1)):
        matched_any = True
        total += float(value) * _DURATION_FACTORS[unit.lower()]
    return total if matched_any else None


def _humanize_duration(seconds: float) -> str:
    """تبدیل ثانیه به متن فارسی خوانا، مثل «۱۸ ساعت و ۱۱ دقیقه»."""
    seconds = max(0.0, seconds)
    parts: list[str] = []
    hours, remainder = divmod(int(seconds), 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        parts.append(f"{hours} ساعت")
    if minutes:
        parts.append(f"{minutes} دقیقه")
    if secs and not hours:
        parts.append(f"{secs} ثانیه")
    return " و ".join(parts) if parts else "چند لحظه"


def _mask_secret(value: str) -> str:
    """نمایش غیرقابل‌بازگشت کلید؛ هرگز کلید واقعی وارد لاگ یا پیام خطا نمی‌شود."""
    if not value:
        return "(تنظیم نشده)"
    return f"{value[:6]}…({len(value)} chars)"


def _triage_error(status_code: int, body: str, err_msg: str) -> tuple[str, float]:
    """تشخیص نوع خطای سرویس و تعیین زمان انتظار مناسب.

    تفاوت کلیدی: خطای ۴۲۹ با متریک ``free_tier_requests`` یعنی سقف **روزانه** و
    باید مدل برای ادامه‌ی همین اجرا کنار گذاشته شود، در حالی که خطای ۴۲۹ با
    متریک ``generate_content_requests`` یعنی محدودیت **دقیقه‌ای** و باید صرفاً
    با تأخیر کوتاه دوباره تلاش شود.
    """
    full_text = f"{err_msg} {body}".lower()
    service_delay = _parse_retry_delay(body) or _parse_retry_delay(err_msg)

    # ۱) مدل نامعتبر یا غیرفعال — بدون تلاش مجدد کنار گذاشته می‌شود
    if status_code == 404 or any(m in full_text for m in _MODEL_UNAVAILABLE_MARKERS):
        return TRIAGE_MODEL_UNAVAILABLE, 0.0

    # ۲) سقف روزانه — اول بررسی می‌شود چون متن آن کلمه‌ی «quota» هم دارد
    if status_code == 429 and any(m in full_text for m in _DAILY_QUOTA_MARKERS):
        return TRIAGE_DAILY_QUOTA, 0.0

    # ۳) محدودیت نرخ لحظه‌ای — با احترام به زمان اعلام‌شده توسط سرویس
    if status_code == 429 or any(m in full_text for m in _RATE_LIMIT_MARKERS):
        if service_delay is not None and service_delay > _MAX_RETRY_WAIT_SECONDS:
            return TRIAGE_DAILY_QUOTA, 0.0
        wait = 12.0
        if service_delay is not None:
            wait = max(wait, service_delay + 1.5)
        return TRIAGE_RATE_LIMIT, min(wait, _MAX_RETRY_WAIT_SECONDS)

    # ۴) خطاهای غیرقابل بازیابی برای این مدل
    if any(m in full_text for m in _FATAL_MARKERS) or status_code in (400, 401, 403):
        return TRIAGE_FATAL, 0.0

    # ۵) فشار لحظه‌ای سرور
    if status_code == 503 or any(m in full_text for m in _OVERLOADED_MARKERS):
        return TRIAGE_OVERLOADED, 12.0

    return TRIAGE_TRANSIENT, 4.0


class PartialTranslationError(RuntimeError):
    """ترجمه به‌طور کامل انجام نشد اما بخش قابل‌توجهی از کار حفظ شده است.

    این خطا به‌جای دور ریختن کل سند صادر می‌شود؛ سندِ نیمه‌ترجمه‌شده از طریق
    صفت ``doc`` در دسترس است و checkpoint آن برای ادامه‌ی کار ذخیره شده.
    """

    def __init__(
        self,
        message: str,
        doc: SubtitleDocument,
        completed: int,
        total: int,
        cause: Optional[BaseException] = None,
    ):
        super().__init__(message)
        self.doc = doc
        self.completed = completed
        self.total = total
        self.cause = cause

    @property
    def progress_pct(self) -> float:
        if self.total <= 0:
            return 0.0
        return (self.completed / self.total) * 100.0


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
        api_keys: Optional[list[str]] = None,
    ):
        self.base_url = (base_url or settings.llm_base_url).rstrip("/")
        self.models = models or settings.llm_models
        self.timeout = timeout or settings.request_timeout
        self.max_retries_per_model = max_retries_per_model
        self.glossary = glossary_manager or GlossaryManager()
        self.inter_batch_delay = (
            inter_batch_delay if inter_batch_delay is not None else settings.inter_batch_delay
        )

        # زنجیره‌ی کلیدها: سهمیه در سطح کلید است، پس با اتمام یک کلید سراغ بعدی می‌رویم.
        # LLM_API_KEYS مقدم است و در نبود آن به LLM_API_KEY برمی‌گردیم تا سازگاری حفظ شود.
        keys = [k for k in (api_keys if api_keys is not None else settings.llm_api_keys) if k]
        if not keys and api_key:
            keys = [api_key]
        # تکراری‌ها حذف می‌شوند؛ وگرنه یک سهمیه دو بار در زنجیره شمرده می‌شود
        # و ظرفیت مؤثر نصف می‌گردد.
        self.api_keys: list[str] = list(dict.fromkeys(keys))

        # برچسب‌های نمایشی به‌جای خودِ کلید، تا هیچ رازی وارد لاگ نشود
        self._key_labels: dict[str, str] = {}
        for index, key in enumerate(self.api_keys):
            self._key_labels[key] = f"کلید #{index + 1} ({_mask_secret(key)})"

        self._dead_models: dict[str, str] = {}
        self._exhausted_pairs: set[tuple[str, str]] = set()
        self._dead_keys: set[str] = set()
        self._quota_reset_seconds: Optional[float] = None

    def _key_label(self, api_key: str) -> str:
        """برچسب خوانا و امن برای یک کلید."""
        return self._key_labels.get(api_key, _mask_secret(api_key))

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

    async def _call_llm_api(self, client: httpx.AsyncClient, model: str, system_prompt: str, user_payload: str, api_key: Optional[str] = None) -> str:
        """ارسال درخواست به اندپوینت chat/completions با کلید مشخص‌شده یا کلید جاری."""
        url = f"{self.base_url}/chat/completions"
        key = api_key or (self.api_keys[0] if self.api_keys else "")
        headers = {
            "Authorization": f"Bearer {key}",
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
                if model_name in self._dead_models:
                    continue

                # کلید فقط در صورت خطای احراز هویت کنار گذاشته می‌شود؛ سهمیه‌ی روزانه
                # برای هر جفت (کلید × مدل) جداست، پس با هر مدل سهمیه‌ی تازه داریم.
                available_keys = [k for k in self.api_keys if k not in self._dead_keys]
                if self.api_keys and not available_keys:
                    break

                for api_key in available_keys:
                    # ۴۰۴ در سطح مدل است؛ با یک کلید دیگر هم تکرار نمی‌شود
                    if model_name in self._dead_models:
                        break

                    # این جفت کلید-مدل قبلاً سهمیه‌ی روزانه‌اش تمام شده
                    if (model_name, api_key) in self._exhausted_pairs:
                        continue

                    for attempt in range(self.max_retries_per_model):
                        try:
                            log.info(
                                f"در حال ترجمه دسته {batch.batch_index} با مدل {model_name} (تلاش {attempt + 1}/{self.max_retries_per_model})..."
                            )
                            raw_resp = await self._call_llm_api(
                                client, model_name, system_prompt, user_payload, api_key=api_key
                            )
                            parsed_dict = _extract_json_from_response(raw_resp)

                            # اعتبارسنجی تطابق کلیدها
                            # برای بلاک‌های خالی، از مدل انتظار کلید الزامی نداریم
                            empty_keys = {
                                f"C{i + 1}" for i, cue in enumerate(batch.cues) if not cue.clean_text
                            }
                            required_keys = expected_keys - empty_keys

                            missing = required_keys - set(parsed_dict.keys())
                            if missing:
                                log.warning(
                                    f"مدل {model_name} کلیدهای {missing} را بازنگرداند."
                                )
                                if attempt < self.max_retries_per_model - 1:
                                    await asyncio.sleep(2.0)
                                    continue
                                break

                            # موفقیت در ترجمه (بلاک‌های خالی با رشته تهی پر می‌شوند)
                            result_map: dict[str, str] = {}
                            for k in expected_keys:
                                if k in parsed_dict:
                                    result_map[k] = parsed_dict[k]
                                else:
                                    result_map[k] = ""
                            return result_map

                        except Exception as ex:
                            err_name = type(ex).__name__
                            err_msg = str(ex) or "Timeout or network dropped"
                            resp_body = ""
                            status_code = 0
                            if isinstance(ex, httpx.HTTPStatusError):
                                try:
                                    resp_body = ex.response.text
                                    status_code = ex.response.status_code
                                except Exception:
                                    pass

                            last_error_str = f"[{model_name} | {self._key_label(api_key)}] {err_name}: {err_msg}"
                            if resp_body:
                                last_error_str += f" | {resp_body[:280]}"
                            log.warning(
                                f"خطا در مدل {model_name} (تلاش {attempt + 1}): {last_error_str}"
                            )

                            kind, wait_seconds = _triage_error(status_code, resp_body, err_msg)

                            if kind == TRIAGE_DAILY_QUOTA:
                                reset_in = _parse_retry_delay(resp_body) or _parse_retry_delay(err_msg)
                                if reset_in is not None:
                                    self._quota_reset_seconds = max(self._quota_reset_seconds or 0.0, reset_in)
                                log.warning(
                                    f"سهمیه‌ی روزانه‌ی مدل {model_name} با {self._key_label(api_key)} تمام شد "
                                    f"(سهمیه برای هر جفت کلید×مدل جداست). به ترکیب بعدی می‌رویم..."
                                )
                                self._exhausted_pairs.add((model_name, api_key))
                                break

                            if kind == TRIAGE_MODEL_UNAVAILABLE:
                                log.warning(
                                    f"مدل {model_name} برای این کلید در دسترس نیست (۴۰۴). بدون تلاش مجدد به مدل بعدی می‌رویم."
                                )
                                self._dead_models[model_name] = "مدل در دسترس نیست (۴۰۴)"
                                break

                            if kind == TRIAGE_FATAL:
                                log.warning(
                                    f"خطای غیرقابل بازیابی برای {self._key_label(api_key)} "
                                    f"با مدل {model_name}. به کلید بعدی می‌رویم."
                                )
                                self._dead_keys.add(api_key)
                                if not [k for k in self.api_keys if k not in self._dead_keys]:
                                    self._dead_models[model_name] = f"خطای غیرقابل بازیابی ({status_code})"
                                break

                            # محدودیت نرخ لحظه‌ای، فشار سرور یا خطای گذرا → تلاش مجدد با تأخیر
                            if attempt < self.max_retries_per_model - 1:
                                log.info(
                                    f"صبر به مدت {wait_seconds:.1f} ثانیه قبل از تلاش مجدد (نوع خطا: {kind})..."
                                )
                                await asyncio.sleep(wait_seconds)
                                continue
                            break

            raise RuntimeError(self._build_failure_message(last_error_str))
        finally:
            if close_client:
                await client.aclose()

    def _build_failure_message(self, last_error_str: str) -> str:
        """ساخت پیام خطای مفهومی همراه با دلیل کنار گذاشته شدن هر مدل و کلید."""
        reasons: list[str] = []
        for model_name in self.models:
            if model_name in self._dead_models:
                reasons.append(f"• {model_name}: {self._dead_models[model_name]}")

        key_reasons: list[str] = []
        for key in dict.fromkeys(self.api_keys):
            label = self._key_label(key)
            if key in self._dead_keys:
                key_reasons.append(f"• {label}: کلید نامعتبر یا غیرمجاز")

        pair_reasons: list[str] = []
        for model_name, key in sorted(self._exhausted_pairs):
            pair_reasons.append(f"{model_name} + {self._key_label(key)}")

        parts = ["همه ترکیب‌های مدل/کلید موجود در زنجیره fallback شکست خوردند."]

        if self._exhausted_pairs:
            parts.append(
                f"سهمیه‌ی روزانه برای هر جفت «کلید × مدل» جداگانه است (۵۰۰ درخواست برای هر ترکیب). "
                f"{len(self._exhausted_pairs)} ترکیب از {len(self.models) * len(self.api_keys)} "
                f"ترکیب ممکن تمام شده است."
            )
            if self._quota_reset_seconds:
                parts.append(
                    f"طبق پیام سرویس، سهمیه حدود {_humanize_duration(self._quota_reset_seconds)} دیگر آزاد می‌شود."
                )
            else:
                parts.append("زمان دقیق آزادسازی توسط سرویس اعلام نشده است.")
            parts.append(
                "با افزودن کلید (LLM_API_KEYS) یا مدل (LLM_MODELS) بیشتر می‌توانید ظرفیت روزانه را افزایش دهید."
            )

        if len(self.api_keys) <= 1 and not self._exhausted_pairs:
            parts.append(
                "فقط یک کلید پیکربندی شده است؛ برای افزایش ظرفیت، چند کلید را در LLM_API_KEYS قرار دهید."
            )

        if pair_reasons:
            parts.append("ترکیب‌های تمام‌شده: " + " | ".join(pair_reasons))
        if key_reasons:
            parts.append("وضعیت کلیدها: " + " | ".join(key_reasons))
        if reasons:
            parts.append("وضعیت مدل‌ها: " + " | ".join(reasons))

        parts.append(f"آخرین خطا: {last_error_str}")
        return "\n".join(parts)

    async def translate_document(
        self,
        doc: SubtitleDocument,
        context: Optional[AcademicContext] = None,
        on_progress: Optional[Callable[[float, int, int], Awaitable[None]]] = None,
        batcher: Optional[ContextBatcher] = None,
        checkpoint_store: Optional[CheckpointStore] = None,
        source_hash: Optional[str] = None,
    ) -> SubtitleDocument:
        """ترجمه کامل یک سند زیرنویس با مدیریت پیشرفت، ذخیره‌ی checkpoint و امکان از سرگیری.

        اگر ``checkpoint_store`` و ``source_hash`` داده شوند، پیشرفت پس از هر دسته روی
        دیسک ثبت می‌شود و در اجرای بعدی دسته‌های ترجمه‌شده دوباره ارسال نمی‌شوند.
        در صورت شکست یک دسته، به‌جای دور ریختن کل سند، ``PartialTranslationError``
        با سندِ نیمه‌ترجمه‌شده صادر می‌شود.
        """
        ctx = context or AcademicContext()
        b_mgr = batcher or ContextBatcher()
        resume_enabled = checkpoint_store is not None and bool(source_hash)

        # بازیابی ترجمه‌های قبلی پیش از ساخت دسته‌ها تا کانتکست قبلی از متن فارسی ساخته شود
        if resume_enabled:
            existing = checkpoint_store.load(source_hash)
            if existing and existing.total_cues == doc.total_cues:
                restored = 0
                for position, cue in enumerate(doc.cues):
                    if position in existing.translations:
                        cue.translated_text = existing.translations[position]
                        restored += 1
                if restored:
                    log.info(
                        f"ادامه‌ی ترجمه از checkpoint: {restored} از {doc.total_cues} بلاک از قبل آماده است."
                    )
            elif existing:
                log.warning("checkpoint با تعداد بلاک‌های ناسازگار نادیده گرفته شد.")

        batches = b_mgr.create_batches(doc.cues, context=ctx)

        total_cues = doc.total_cues
        translated_so_far = doc.translated_cues_count

        if translated_so_far and on_progress:
            await on_progress(
                (translated_so_far / total_cues) * 100.0, translated_so_far, total_cues
            )

        async with httpx.AsyncClient() as client:
            for batch in batches:
                # دسته‌ای که در اجرای قبلی کامل شده، نیازی به ارسال مجدد ندارد
                if all(cue.translated_text is not None for cue in batch.cues):
                    continue

                try:
                    trans_map = await self.translate_batch(batch, ctx, client=client)
                except Exception as exc:
                    done = doc.translated_cues_count
                    if done:
                        if resume_enabled:
                            try:
                                checkpoint_store.save(
                                    snapshot_document(doc, source_hash, ctx.topic)
                                )
                            except OSError as save_error:
                                log.warning(f"ذخیره‌ی checkpoint ناموفق بود: {save_error}")

                        raise PartialTranslationError(
                            f"ترجمه پس از {done} از {total_cues} بلاک متوقف شد. "
                            f"نتیجه‌ی نیمه‌کاره ذخیره شد و در اجرای بعدی ادامه پیدا می‌کند.\n"
                            f"علت: {exc}",
                            doc=doc,
                            completed=done,
                            total=total_cues,
                            cause=exc,
                        ) from exc
                    raise

                for i, cue in enumerate(batch.cues):
                    key = f"C{i + 1}"
                    cue.translated_text = trans_map.get(key, cue.clean_text)

                translated_so_far += len(batch.cues)

                if resume_enabled:
                    try:
                        checkpoint_store.save(snapshot_document(doc, source_hash, ctx.topic))
                    except OSError as save_error:
                        log.warning(f"ذخیره‌ی checkpoint ناموفق بود: {save_error}")

                progress_pct = (translated_so_far / total_cues) * 100.0

                if on_progress:
                    await on_progress(progress_pct, translated_so_far, total_cues)

                # مکث هوشمند بین بسته‌ها جهت رعایت سقف نرخ درخواست (RPM) در ارائه‌دهندگان رایگان (نظیر جمنای)
                await asyncio.sleep(self.inter_batch_delay)

        if resume_enabled:
            # ترجمه کامل شد؛ checkpoint پاک می‌شود تا اجرای بعدی از صفر شروع کند
            checkpoint_store.clear(source_hash)

        return doc
