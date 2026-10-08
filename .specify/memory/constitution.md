<!--
Sync Impact Report:
- Version change: 1.0.0 (Ratified)
- Project: Academic SRT Subtitle Translator Bot (srt_translator)
- Principles codified:
  1. Subtitle Timestamp & Sync Invariance (NON-NEGOTIABLE)
  2. Smart-Persian Academic Terminology & Anti-Fragmentation (NON-NEGOTIABLE)
  3. Decoupled Core Engine & Telegram Interface
  4. Batch Resiliency & Zero Data Loss
  5. Privacy, Security & Environment Configuration
-->

# Academic SRT Subtitle Translator Constitution

## Core Principles

### I. Subtitle Timestamp & Sync Invariance (NON-NEGOTIABLE)
The system MUST guarantee 100% preservation of all cue timing, indices, and ordering.
- Timing codes (`00:00:00,000 --> 00:00:00,000`) and cue sequence IDs MUST NEVER be passed to LLMs for alteration.
- LLM translation operates strictly on extracted text payloads, and translations are strictly mapped back 1:1 to original subtitle cues.
- The output file must load and play seamlessly in standard media players without any subtitle desynchronization.

### II. Smart-Persian Academic Terminology & Anti-Fragmentation (NON-NEGOTIABLE)
The system MUST produce natural, publishable-quality academic Persian translations suitable for university-level coursework.
- **Smart Terminology Contract**: Core technical terms and acronyms (e.g., Backpropagation, Eigenvalue, Gradient Descent, CNN) must be preserved in English inline or accompanied by their standard academic Persian equivalent with the English term in parentheses on first mention.
- **Anti-Fragmentation**: Subtitles frequently split a single sentence across multiple cues. The engine MUST translate using contextual sliding windows so sentences are understood as complete thoughts and translated accurately with natural Persian sentence structure (SOV).
- **Directional & Formula Integrity**: Formulas, code variables, and symbols ($x_i$, $\mathcal{O}(n)$, Python keywords) must remain untouched and uncorrupted by RTL/LTR BiDi rendering.

### III. Decoupled Core Engine & Interface Architecture
The translation engine MUST be a standalone, headless Python module that does not depend on Telegram or any specific UI.
- The core pipeline (`SubtitleParser`, `ContextBatcher`, `TranslationEngine`, `SrtSerializer`) can be executed via CLI, script, or import.
- The Telegram Bot (`aiogram`) serves purely as an asynchronous client adapter interacting with the core engine.

### IV. Batch Resiliency & Zero Data Loss
For long educational videos (500 to 2,000+ subtitle cues), network timeouts or rate limits MUST NOT cause the entire job to fail.
- Translations are performed in isolated, manageable batches.
- Transient API errors trigger exponential backoff and model fallback without discarding previously completed batches.

### V. Privacy, Security & Environment Configuration
All LLM endpoints, API tokens, and bot tokens MUST be sourced from environment variables (`.env`).
- No credentials or API keys may ever be hardcoded into source code.
- Temporary files uploaded by users are cleaned up after translation delivery.

## Technical Standards

- **Language & Runtime**: Python 3.11+, typed, async-friendly (`asyncio`, `httpx`, `aiogram 3.x`).
- **Engine Heritage**: Built on verified architecture patterns from `tarjoman` (HTTPX client, model fallback chain, smart academic prompt design).
- **Quality Gates**: Pytest unit and integration test coverage for SRT parsing, batching, and serialization.

**Version**: 1.0.0 | **Ratified**: 2026-10-08
