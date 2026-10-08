# Feature Specification: Academic SRT Subtitle Translator Bot

**Feature Branch**: `001-academic-srt-translator`  
**Created**: 2026-10-08  
**Status**: Draft  
**Input**: User description: "A translation service for university/educational lecture SRT subtitle files via a Telegram Bot interface, powered by the Tarjoman translation engine principles, translating English subtitles into highly accurate, context-aware academic Persian while preserving exact subtitle synchronization and timing."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Core Subtitle Translation via Telegram Bot (Priority: P1)

As a student or academic researcher, I want to upload an English SRT subtitle file of an educational lecture to a Telegram Bot and receive a fully translated Persian SRT file, so that I can study the lecture in Persian with exact video synchronization.

**Why this priority**: This is the minimum viable product (MVP). Without the ability to send a subtitle file and receive a synchronized, high-quality translated subtitle file, the system provides no value.

**Independent Test**: The user sends a standard English `.srt` file of a short lecture to the bot; the bot processes the file and replies with a valid Persian `.srt` file whose timestamps and cue counts match the original 1:1, and the translated text is coherent and accurate.

**Acceptance Scenarios**:

1. **Given** a user interacts with the Telegram Bot and uploads a valid English `.srt` file, **When** processing completes, **Then** the bot delivers a valid Persian `.srt` file where every subtitle cue has the identical start/end timestamp and sequence index as the source.
2. **Given** an English sentence is fragmented across multiple consecutive subtitle cues, **When** translated, **Then** the Persian translation represents the complete coherent sentence distributed naturally across those cues rather than fragmented word-for-word translations.
3. **Given** subtitle cues containing speaker tags (e.g., `>> Speaker: `) or non-speech audio descriptions (e.g., `[Music]`, `[Applause]`), **When** processed, **Then** the bot either preserves or cleanly handles these cues without mistranslating them into artificial prose.

---

### User Story 2 - Academic Domain Context & Glossary Customization (Priority: P2)

As a university learner studying a specialized subject (e.g., Machine Learning, Quantum Mechanics, Microeconomics), I want to specify the course topic and optional custom terminology preferences when submitting a subtitle file, so that domain-specific technical jargon is translated accurately and consistently throughout the lecture.

**Why this priority**: Academic lecture comprehension depends critically on terminology precision. A generic translation that renders specialized terms incorrectly (e.g., translating "overfitting" literally instead of "بیش‌برازش (overfitting)") severely undermines learning.

**Independent Test**: The user submits an SRT file from a Machine Learning lecture along with the topic "Machine Learning"; the translated output adheres to standard Iranian academic AI terminology (preserving key terms inline in English or providing standard equivalents with parenthesized English).

**Acceptance Scenarios**:

1. **Given** a user provides a course topic (e.g., "Linear Algebra") prior to or alongside file upload, **When** translation occurs, **Then** the system biases translations toward standard academic terminology for that field.
2. **Given** a user specifies custom glossary overrides or preferred term pairs, **When** those terms appear in the subtitle text, **Then** the output strictly uses the user-specified Persian translations.
3. **Given** technical acronyms (e.g., CNN, RNN, API, CPU, GPU) or mathematical expressions ($x_i$, $O(n \log n)$), **When** translated, **Then** the technical tokens and formulas remain intact and are not distorted by text directionality.

---

### User Story 3 - Progress Feedback & Batch Resiliency (Priority: P3)

As a user submitting long lecture subtitles (e.g., 60-90 minute courses with 1,000+ cues), I want to see real-time progress updates and have the system resilient to temporary translation interruptions, so that I know the status of my request and do not lose progress if an interruption occurs.

**Why this priority**: Subtitle translation for long lectures takes several minutes. Without progress feedback, users will think the bot is frozen or restart jobs redundantly.

**Independent Test**: Submit a 1,000-cue subtitle file; observe the bot periodically updating status (e.g., percentage completed or cue count processed), and confirm successful final delivery even if temporary network retries occur.

**Acceptance Scenarios**:

1. **Given** a subtitle job that takes longer than 15 seconds, **When** processing, **Then** the bot periodically updates a status message indicating the percentage or cue progress.
2. **Given** a momentary network or upstream translation failure during a batch of cues, **When** encountered, **Then** the system automatically retries the failed segment without aborting the entire document.
3. **Given** processing is finished, **When** the file is sent, **Then** the bot displays an overview summary (e.g., total cues translated, elapsed time).

---

### Edge Cases

- **Broken or Non-standard SRT Formatting**: Input file has missing cue numbers, irregular blank lines, or CRLF vs LF mixed encodings. The system must parse and normalize them without crashing.
- **Extreme Sentence Spans**: A single speaker sentence spans over 5+ consecutive subtitle cues with pauses. The system must preserve semantic continuity across the cues without dropping cues or merging timestamps.
- **BiDi (Bidirectional) Text Mixing**: English terms, variable names, and numbers embedded inside Persian sentences. Punctuation (periods, commas, colons) and parentheses must not be inverted or visually corrupted in standard video players.
- **Subtitles with HTML/Styling Tags**: Cues containing `<i>...</i>`, `<b>...</b>`, or `<font color="...">` tags. The tags must either be preserved cleanly around the translated words or stripped safely without leaving raw broken tags in the output.
- **Empty or Whitespace-only Cues**: Cues with no spoken dialogue or only punctuation. The system must preserve the cue timing while leaving it appropriately empty or minimal.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST accept `.srt` subtitle files uploaded by users via Telegram chat.
- **FR-002**: System MUST parse input SRT files, extracting cue sequential numbers, start timestamps, end timestamps, and subtitle text.
- **FR-003**: System MUST preserve 100% of the original timestamp timing and cue structure, ensuring the translated SRT file remains synchronized with the source video.
- **FR-004**: System MUST perform context-aware translation by grouping consecutive subtitle cues into coherent contextual windows, preventing fragmented, out-of-context word-by-word translation.
- **FR-005**: System MUST adapt translations to academic university-level tone and terminology, following the Smart-Persian terminology rule (keeping technical terms in English inline, with optional standard Persian equivalents in parentheses at first mention).
- **FR-006**: System MUST allow users to optionally specify course topic / discipline (e.g., Deep Learning, Physics, Macroeconomics) to guide terminology resolution.
- **FR-007**: System MUST support custom glossary matching to ensure user-defined terms are consistently translated throughout the file.
- **FR-008**: System MUST protect mathematical formulas, programming code identifiers, and acronyms from translation or bidirectional text distortion.
- **FR-009**: System MUST provide visible progress feedback to the user in Telegram for multi-step or long-running translation tasks.
- **FR-010**: System MUST deliver the completed translated subtitle file back to the user as a downloadable `.srt` document via Telegram.
- **FR-011**: System MUST support automatic fallback and retries if an upstream translation batch fails, avoiding whole-job failure.
- **FR-012**: System MUST reject files larger than allowable Telegram limits or non-SRT formats with clear, actionable error messages.

### Key Entities

- **SubtitleCue**: Represents an individual subtitle entry with sequence index, start timestamp, end timestamp, source English text, and translated Persian text.
- **SubtitleDocument**: Represents a complete subtitle file containing an ordered sequence of `SubtitleCue` objects and document-level metadata (filename, duration, total cues).
- **TranslationSession**: State machine tracking a user's active request (pending file upload, course topic configuration, processing stage, completed file delivery).
- **AcademicContext**: Configuration parameters for translation, including target field/discipline, specific course title, and custom glossary mapping.
- **TranslationJob**: An asynchronous processing task that slices a `SubtitleDocument` into contextual windows, handles upstream translation requests, validates cue parity, and generates the final output document.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **Timing Accuracy**: 100% of subtitle cues in the generated output have identical start and end timestamps matching the input file.
- **Cue Count Parity**: 100% parity between source cue count and translated cue count (no lost or duplicated cues).
- **Format Validity**: 100% of generated `.srt` files parse cleanly in standard media players (VLC, MPV, PotPlayer) without syntax errors.
- **User Processing Time**: Subtitle files under 500 cues are completely translated and delivered in under 3 minutes under standard network conditions.
- **Academic Translation Quality**: Technical terminology in university course topics is consistently translated, with zero hallucinated or irrelevant output text.
- **Job Reliability**: Greater than 98% of valid subtitle submissions complete successfully without user-facing server crashes.

## Assumptions

- Subtitles are provided in standard UTF-8 or common UTF-16/Windows-1252 encodings that can be auto-detected and converted to UTF-8.
- The Telegram Bot acts as the primary user interface; underlying translation tasks run asynchronously.
- The translation engine utilizes established LLM router infrastructure and terminology rules proven in the Tarjoman project.
