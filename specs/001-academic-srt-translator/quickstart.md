# Quickstart & Verification Guide: Academic SRT Subtitle Translator

**Feature**: `001-academic-srt-translator`  
**Date**: 2026-10-08

## 1. Prerequisites & Environment Setup

```bash
# 1. Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure environment variables
cp .env.example .env
# Edit .env with your router / LLM API key and Telegram Bot Token
```

---

## 2. Environment Variables (.env)

```env
# LLM Router Settings (OpenAI-compatible, same as Tarjoman)
LLM_BASE_URL=https://router.bynara.id/v1
LLM_API_KEY=your_router_api_key_here
LLM_MODELS=minimax-m3-free,agnes-2.5-flash,mistral-medium-3-5

# Telegram Bot Token
TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here

# Batching & Runtime
BATCH_SIZE=15
```

---

## 3. Running Automated Tests

```bash
# Run all unit tests
pytest tests/ -v

# Run specific subtitle parser verification
pytest tests/test_srt_parser.py -v

# Run batching & parity verification
pytest tests/test_batcher.py -v
```

---

## 4. Verification Scenario 1: Standalone CLI Test

Test translating an SRT file locally without Telegram:

```bash
# Translate a sample subtitle file
python -m app.cli tests/fixtures/sample_lecture.srt -o sample_lecture_fa.srt --topic "Machine Learning"

# Verify that output file exists and has identical cue count
diff <(grep -c "-->" tests/fixtures/sample_lecture.srt) <(grep -c "-->" sample_lecture_fa.srt)
# Should return 0 difference (100% sync parity)
```

---

## 5. Verification Scenario 2: Telegram Bot Execution

```bash
# Start Telegram bot polling
python -m app.bot.main
```

1. Open your bot in Telegram and send `/start`.
2. Send `/topic Deep Learning` or click an inline button.
3. Attach `tests/fixtures/sample_lecture.srt` and send.
4. Verify the bot sends the progress status and returns `sample_lecture_fa.srt`.
5. Open the output `.srt` file in a media player (VLC or MPV) with a video or inspect text to confirm flawless Persian translation and timing.
