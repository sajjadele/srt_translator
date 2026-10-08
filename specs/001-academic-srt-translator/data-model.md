# Data Model: Academic SRT Subtitle Translator

**Feature**: `001-academic-srt-translator`  
**Date**: 2026-10-08

## Entities & Data Structures

### 1. `SubtitleCue`
Represents an individual subtitle unit (block) within an `.srt` document.

| Field | Type | Description | Validation / Constraints |
|---|---|---|---|
| `index` | `int` | Sequential 1-based cue index | $\ge 1$, monotonically increasing in file |
| `start_time` | `str` | Subtitle appearance timecode | Format: `HH:MM:SS,mmm` (e.g. `00:01:23,450`) |
| `end_time` | `str` | Subtitle disappearance timecode | Format: `HH:MM:SS,mmm`, `end_time > start_time` |
| `text` | `str` | Original English subtitle text | Non-empty after strip; may contain linebreaks |
| `translated_text` | `Optional[str]` | Translated Persian subtitle text | Populated after translation; defaults to `None` |

**Validation Rules**:
- `start_time` and `end_time` are validated against standard SRT regex `^\d{2}:\d{2}:\d{2}[,. ]\d{3}$`.
- When re-serializing to SRT, standard comma `,` separator is enforced.

---

### 2. `SubtitleDocument`
Represents the entire parsed subtitle file.

| Field | Type | Description |
|---|---|---|
| `filename` | `str` | Original filename (e.g. `lecture_01.srt`) |
| `cues` | `list[SubtitleCue]` | Ordered collection of all subtitle cues |
| `raw_encoding` | `str` | Detected character encoding (e.g. `utf-8`, `utf-8-sig`) |

**Computed Properties**:
- `total_cues`: `len(cues)`
- `duration`: Time difference between `cues[-1].end_time` and `cues[0].start_time`.
- `is_fully_translated`: `all(cue.translated_text is not None for cue in cues)`

---

### 3. `TranslationBatch`
Represents a chunk of cues submitted to the LLM for unified, context-aware translation.

| Field | Type | Description |
|---|---|---|
| `batch_index` | `int` | Sequential batch number (0-indexed) |
| `cues` | `list[SubtitleCue]` | Active cues to be translated |
| `pre_context` | `list[str]` | Preceding 1–3 translated lines for continuity |
| `post_context` | `list[str]` | Succeeding 1–2 raw English lines for forward lookahead |
| `academic_topic`| `Optional[str]` | Specified subject area (e.g., "Deep Learning") |

**Lifecycle / State Machine**:
```
PENDING --> IN_PROGRESS --> COMPLETED
                 |
                 +--> RETRY (with next fallback model) --> FAILED
```

---

### 4. `AcademicContext`
User-provided metadata guiding the terminology and style of the translation.

| Field | Type | Default | Description |
|---|---|---|---|
| `topic` | `str` | `"General Academic"` | Domain field (e.g. "Linear Algebra", "NLP") |
| `glossary` | `dict[str, str]`| `{}` | User-defined English-Persian terminology pairs |
| `preserve_terms`| `bool` | `True` | Whether to maintain technical acronyms inline |

---

### 5. `TelegramJob`
Represents an in-flight translation request initiated by a Telegram user.

| Field | Type | Description |
|---|---|---|
| `job_id` | `str` | Unique UUID for the translation task |
| `chat_id` | `int` | Telegram chat ID for notifications |
| `message_id` | `int` | ID of the status message being updated |
| `original_filename`| `str` | Name of the uploaded file |
| `context` | `AcademicContext` | Active academic context for this user |
| `status` | `str` | `queued` \| `translating` \| `uploading` \| `done` \| `error` |
| `progress_pct` | `float` | Completion percentage (0.0 to 100.0) |
| `started_at` | `float` | Unix timestamp of job start |
