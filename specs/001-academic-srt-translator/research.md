# Research & Architectural Decisions: Academic SRT Subtitle Translator

**Date**: 2026-10-08  
**Feature**: `001-academic-srt-translator`  
**Status**: Completed

## 1. Subtitle Parsing & Timing Invariance

### Decision
Implement a dedicated, zero-external-dependency robust SRT parser and serializer in `app/core/srt_parser.py`, paired with optional `srt` library compatibility.

### Rationale
- SRT format looks simple, but real-world educational subtitles (e.g. downloaded from YouTube, Coursera, MIT OpenCourseWare) have quirks: UTF-8 with BOM (`\ufeff`), mixed CRLF/LF line endings, missing cue indexes, millisecond delimiters using periods (`.`) instead of commas (`,`), and trailing whitespace.
- By handling parsing internally with a dedicated dataclass (`SubtitleCue(index, start, end, text)`), we guarantee:
  1. Timestamps (`start` and `end`) are never touched or exposed to the LLM.
  2. Complete round-trip serialization fidelity: `parse(text) -> list[SubtitleCue] -> serialize(cues) -> valid .srt`.
  3. Seamless validation of timecodes.

### Alternatives Considered
- *Using pysrt*: Heavy, unmaintained for several years, issues with Python 3.12+ datetime edge cases.
- *Direct string splitting by double newlines*: Fails on subtitles containing internal empty lines or multi-line cue text.

---

## 2. Context-Aware Batching & Anti-Fragmentation (The Grammar Problem)

### Decision
Implement structured window batching in `app/core/batcher.py`:
1. Subtitle cues are grouped into batches of $N$ cues (default: 15–20 cues, ~200–350 tokens).
2. Each batch prompt includes:
   - **Pre-Context**: The previous 2–3 translated cues (read-only, for continuity).
   - **Active Cues**: Numbered as `C1: [text]`, `C2: [text]`, ..., `Cn: [text]`.
   - **Post-Context**: The next 1–2 incoming cues (for forward sentence lookahead).
3. **Structured JSON Output**: The LLM is instructed to respond in JSON format:
   ```json
   {
     "C1": "ترجمه فارسی بلاک ۱",
     "C2": "ترجمه فارسی بلاک ۲",
     ...
     "Cn": "ترجمه فارسی بلاک n"
   }
   ```
4. **Parity Validation**: If any cue key is missing or malformed, the batcher detects the discrepancy immediately and triggers a fallback model or retry.

### Rationale
- In academic English lectures, sentences frequently span multiple cues (e.g., `C1: "If we compute the gradient of"`, `C2: "the cost function with respect to weights,"`, `C3: "we get the following result:"`).
- In Persian (SOV structure), the verb goes to the end. The translator must understand the entire clause before determining the Persian verb conjugation and position.
- Structured JSON output prevents index misalignment, line dropping, or hallucinated extra cues.

### Alternatives Considered
- *Single-line prompt translation*: Causes severe sentence fragmentation; verbs get stuck awkwardly on isolated cues.
- *Translating entire SRT file in one prompt*: Token limits for 1-hour lectures (15,000+ words) exceed reliable structured output limits and increase failure risk on timeouts.

---

## 3. Translation Engine Heritage from Tarjoman

### Decision
Adopt and adapt the battle-tested LLM engine architecture from `tarjoman`:
1. Use `httpx.AsyncClient` with configurable timeout and retry logic.
2. Implement the `LLM_MODELS` comma-separated fallback chain (`[primary, secondary, tertiary]`). If the primary model encounters a 429 (Rate Limit) or 5xx error, it automatically falls back to the next model in the chain.
3. System prompt with the **Smart-Persian Terminology Contract**:
   - Technical terms and acronyms (e.g., *Eigenvector*, *Loss Function*, *Backpropagation*, *Transformer*, *Tensor*) remain inline in English, or include an approved Persian equivalent with the English word in parentheses on first mention.
   - Academic tone, avoiding colloquialisms or clumsy literal machine translation.
   - Formatting protection: variables ($x_i$, $\theta$), formulas, and code tokens are untouched.

### Rationale
- Proven stability and high quality in production with zero code rewrite needed for router communication.
- Supports any OpenAI-compatible router (Bynara, OpenAI, Gemini API, OpenRouter, Groq, Ollama).

---

## 4. Telegram Bot Architecture (aiogram 3.x)

### Decision
Use `aiogram 3.x` with an asynchronous job queue / task dispatch pattern:
1. Long-polling bot runner (`app/bot/main.py`).
2. Conversation state machine for optional context:
   - User sends `/start` -> Bot presents instructions and quick topic buttons (`🤖 Machine Learning`, `💻 Computer Science`, `📐 Mathematics & Physics`, `🌐 General Academic`).
   - User can upload `.srt` directly at any time; if no topic is specified, it defaults to General Academic.
3. Asynchronous job handling:
   - When a `.srt` document is received, the bot downloads it to a temporary buffer/file.
   - Bot sends an initial status message: `⏳ در حال پردازش فایل [نام فایل]...`
   - During processing, the bot edits the message at milestones (e.g., 25%, 50%, 75%, 100%) to inform the user.
   - Upon completion, the translated file `[filename]_fa.srt` is uploaded and sent back to the user, and temporary files are cleaned up.

### Rationale
- `aiogram 3.x` is the most modern, async-native, type-safe Telegram framework in Python.
- Message editing provides an intuitive progress bar without spamming the chat.

---

## 5. Standalone CLI Utility

### Decision
Include `app/cli.py` so the translation engine can be run directly from terminal:
`python -m app.cli input.srt -o output_fa.srt --topic "Machine Learning"`

### Rationale
- Honors Constitution Principle III (Decoupled Core Engine).
- Enables rapid testing, scripting, batch folder processing, and CI without needing Telegram or network bot tokens.
