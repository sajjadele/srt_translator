"""تنظیمات سیستم ترجمه زیرنویس — مدیریت یکپارچه متغیرهای محیطی."""

from __future__ import annotations

import os
from pathlib import Path
from pydantic import BaseModel, Field
from dotenv import load_dotenv

# بارگذاری فایل .env در صورت وجود
load_dotenv()


class Settings(BaseModel):
    """تنظیمات سراسری برنامه با اعتبارسنجی مقادیر."""

    # LLM Router Settings
    llm_base_url: str = Field(
        default_factory=lambda: os.getenv("LLM_BASE_URL", "https://router.bynara.id/v1")
    )
    llm_api_key: str = Field(
        default_factory=lambda: os.getenv("LLM_API_KEY", "")
    )
    llm_models: list[str] = Field(
        default_factory=lambda: [
            m.strip()
            for m in os.getenv(
                "LLM_MODELS", "nemotron-3-super-free"
            ).split(",")
            if m.strip()
        ]
    )

    # Telegram Bot
    telegram_bot_token: str = Field(
        default_factory=lambda: os.getenv("TELEGRAM_BOT_TOKEN", "")
    )

    # Batching & Context Parameters
    batch_size: int = Field(
        default_factory=lambda: int(os.getenv("BATCH_SIZE", "25"))
    )
    pre_context_size: int = Field(
        default_factory=lambda: int(os.getenv("PRE_CONTEXT_SIZE", "2"))
    )
    post_context_size: int = Field(
        default_factory=lambda: int(os.getenv("POST_CONTEXT_SIZE", "2"))
    )
    request_timeout: float = Field(
        default_factory=lambda: float(os.getenv("REQUEST_TIMEOUT", "90.0"))
    )

    # File Paths
    base_dir: Path = Field(
        default_factory=lambda: Path(__file__).resolve().parent.parent
    )
    dict_path: Path = Field(
        default_factory=lambda: (
            Path(__file__).resolve().parent.parent / "data" / "dict" / "en_fa_academic.json"
        )
    )


settings = Settings()
