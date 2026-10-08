# Implementation Plan: Academic SRT Subtitle Translator

**Branch**: `001-academic-srt-translator` | **Date**: 2026-10-08 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/001-academic-srt-translator/spec.md`

## Summary

Build an asynchronous academic subtitle translation service for university course videos. The core engine is decoupled from the user interface and adapts the proven translation engine from the `tarjoman` project (OpenAI-compatible router, smart Persian terminology rules, model fallback chain). A Telegram Bot (`aiogram 3.x`) provides an intuitive chat interface allowing users to upload `.srt` files, select course topics, receive real-time progress updates, and download the finished Persian `.srt` with 100% timing and cue synchronization.

## Technical Context

**Language/Version**: Python 3.11+  
**Primary Dependencies**: `httpx` (async HTTP client), `aiogram 3.x` (Telegram Bot), `pydantic` (validation/settings), `pytest`, `pytest-asyncio`  
**Storage**: Ephemeral local file storage for incoming/outgoing `.srt` files (cleaned up post-delivery); optional SQLite/JSON memory for user context preferences  
**Testing**: `pytest`, `pytest-asyncio` for parser, batcher, engine fallback, and contracts  
**Target Platform**: Linux server / local developer workstation  
**Project Type**: Hybrid Python Core Library + CLI + Telegram Bot Service  
**Performance Goals**: < 3 minutes for a standard 500-cue lecture subtitle; 100% timestamp and cue count parity  
**Constraints**: Zero timestamp drift, no secrets in code, graceful recovery from LLM rate limits/timeouts  
**Scale/Scope**: Single-user or small research group personal bot, handling multi-thousand cue lecture files reliably  

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Check | Status |
|---|---|---|
| **I. Subtitle Timestamp & Sync Invariance** | Timestamps are parsed and isolated in Python; LLM receives only text payloads; re-serializer maps timestamps 1:1. | **PASSED** |
| **II. Smart-Persian Terminology & Anti-Fragmentation** | Contextual sliding window batching groups sentences across cues; terminology dictionary and prompt rules enforced. | **PASSED** |
| **III. Decoupled Core Architecture** | Core engine (`app.core`) is 100% headless and usable via CLI independently of Telegram. | **PASSED** |
| **IV. Batch Resiliency & Zero Data Loss** | Batches are processed sequentially or in resilient pools with fallback model chains; failures trigger isolated retries. | **PASSED** |
| **V. Privacy & Security** | All credentials loaded via `.env`; temporary files cleaned up immediately upon delivery. | **PASSED** |

## Project Structure

### Documentation (this feature)

```text
specs/001-academic-srt-translator/
├── spec.md              # Feature specification
├── plan.md              # Implementation plan (this file)
├── research.md          # Phase 0 architectural decisions
├── data-model.md        # Phase 1 data entities and lifecycle
├── quickstart.md        # Phase 1 verification and run guide
├── contracts/           # Phase 1 interface specifications
│   ├── core_api.md
│   ├── llm_schema.md
│   └── telegram_interface.md
└── checklists/
    └── requirements.md  # Quality validation checklist
```

### Source Code Layout

```text
srt_translator/
├── app/
│   ├── __init__.py
│   ├── config.py                 # Pydantic/dataclass settings from .env
│   ├── core/
│   │   ├── __init__.py
│   │   ├── models.py             # SubtitleCue, SubtitleDocument, TranslationBatch
│   │   ├── srt_parser.py         # Robust SRT parse, clean, normalize, serialize
│   │   ├── batcher.py            # Context-aware sliding window batching
│   │   ├── engine.py             # Async LLM translation with model fallback
│   │   └── glossary.py           # Academic dictionary & term preservation
│   ├── bot/
│   │   ├── __init__.py
│   │   ├── main.py               # Aiogram bot entry point & polling
│   │   ├── handlers.py           # Commands (/start, /topic) & document receiver
│   │   └── keyboards.py          # Topic selection inline keyboards
│   └── cli.py                    # Standalone terminal translator
├── data/
│   └── dict/
│       └── en_fa_academic.json   # 1,000+ AI & academic technical terms
├── tests/
│   ├── conftest.py
│   ├── fixtures/
│   │   └── sample_lecture.srt    # Academic test fixture
│   ├── test_srt_parser.py        # Parser & serialization tests
│   ├── test_batcher.py           # Context window & parity tests
│   └── test_engine.py            # Mock LLM engine & fallback tests
├── .env.example
├── requirements.txt
└── README.md
```

## Implementation Phases

### Phase 1: Core Foundation & Subtitle Engine
- Step 1: Project setup (`requirements.txt`, `.env.example`, `app/config.py`).
- Step 2: Implement `app/core/models.py` (`SubtitleCue`, `SubtitleDocument`, `AcademicContext`).
- Step 3: Implement `app/core/srt_parser.py` (robust parsing, CRLF/LF normalization, round-trip serialization).
- Step 4: Implement `app/core/glossary.py` with initial dictionary from Tarjoman (`en_fa_dict.json`).
- Step 5: Implement `app/core/batcher.py` (sliding window context generation and JSON prompt formatting).
- Step 6: Implement `app/core/engine.py` (HTTPX async client, structured JSON parsing, fallback chain).
- Step 7: Unit tests for core engine (`tests/test_srt_parser.py`, `tests/test_batcher.py`).

### Phase 2: Standalone CLI
- Step 8: Implement `app/cli.py` for terminal-based translation and verification.
- Step 9: Verify end-to-end translation on `tests/fixtures/sample_lecture.srt`.

### Phase 3: Telegram Bot Adapter
- Step 10: Implement `app/bot/keyboards.py` (inline topic selection).
- Step 11: Implement `app/bot/handlers.py` (file upload handler, progress bar updates, file delivery).
- Step 12: Implement `app/bot/main.py` (bot runner).

### Phase 4: Verification & Polish
- Step 13: End-to-end integration test with live/mock router.
- Step 14: Documentation (`README.md` and user guide).
