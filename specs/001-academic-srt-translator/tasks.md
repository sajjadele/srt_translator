# Tasks: Academic SRT Subtitle Translator Bot

**Feature**: `001-academic-srt-translator`  
**Input**: Design artifacts from `specs/001-academic-srt-translator/` (spec.md, plan.md, data-model.md, contracts/, quickstart.md)

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization and basic dependencies

- [x] T001 Create project directories (`app/core`, `app/bot`, `data/dict`, `tests/fixtures`)
- [x] T002 Initialize `requirements.txt` (`httpx`, `aiogram`, `pydantic`, `pytest`, `pytest-asyncio`) and `.env.example`
- [x] T003 [P] Configure environment settings loader in `app/config.py`
- [x] T004 [P] Populate academic technical dictionary in `data/dict/en_fa_academic.json` from Tarjoman corpus

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Subtitle parsing, data structures, and context batching engine

**⚠️ CRITICAL**: Must be completed before User Story implementation

- [x] T005 [P] Implement core models (`SubtitleCue`, `SubtitleDocument`, `TranslationBatch`, `AcademicContext`) in `app/core/models.py`
- [x] T006 [P] Implement robust SRT parser, timecode validator, and serializer in `app/core/srt_parser.py`
- [x] T007 [P] Create unit tests for SRT parser and serializer in `tests/test_srt_parser.py`
- [x] T008 Implement academic glossary manager in `app/core/glossary.py`
- [x] T009 Implement context-aware sliding window batcher in `app/core/batcher.py`
- [x] T010 [P] Create unit tests for sliding window batcher in `tests/test_batcher.py`

**Checkpoint**: Foundation verified with unit tests. Subtitle cues parse, serialize, and batch reliably.

---

## Phase 3: User Story 1 - Core Subtitle Translation via Telegram Bot (Priority: P1) 🎯 MVP

**Goal**: Deliver an MVP that accepts an English `.srt` file, translates it into natural academic Persian while preserving exact timestamps, and delivers the translated `.srt` back to the user.

**Independent Test**: Upload an `.srt` file to the Telegram bot (or execute via CLI); receive a valid Persian `.srt` with identical cue count, synchronized timestamps, and publishable academic translation.

- [x] T011 [US1] Implement async LLM translation engine with router and model fallback chain in `app/core/engine.py`
- [x] T012 [P] [US1] Create unit and mock tests for translation engine in `tests/test_engine.py`
- [x] T013 [P] [US1] Implement standalone command-line translator in `app/cli.py`
- [x] T014 [US1] Setup Telegram bot instance, dispatcher, and router in `app/bot/main.py`
- [x] T015 [US1] Implement Telegram document handler for `.srt` upload, translation triggering, and output delivery in `app/bot/handlers.py`
- [x] T016 [US1] Create test fixture `tests/fixtures/sample_lecture.srt` and verify end-to-end translation pipeline

**Checkpoint**: MVP is fully functional. Users can translate SRT files via CLI or Telegram Bot.

---

## Phase 4: User Story 2 - Academic Domain Context & Glossary Customization (Priority: P2)

**Goal**: Allow users to specify course topics (e.g., Linear Algebra, Machine Learning) and apply domain-specific terminology rules and custom glossaries.

**Independent Test**: Set topic to "Machine Learning"; verify technical terms (e.g., *backpropagation*, *overfitting*, *loss function*) follow standard academic Persian conventions.

- [x] T017 [US2] Implement inline keyboards for topic selection in `app/bot/keyboards.py`
- [x] T018 [US2] Implement `/topic` command and callback query handlers in `app/bot/handlers.py`
- [x] T019 [US2] Integrate topic prompt biasing and custom glossary overrides into `app/core/engine.py`
- [x] T020 [P] [US2] Add test asserting domain-specific terminology translation in `tests/test_engine.py`

**Checkpoint**: Users can customize and switch course topics seamlessly.

---

## Phase 5: User Story 3 - Progress Feedback & Batch Resiliency (Priority: P3)

**Goal**: Provide live progress updates (percentage and cue milestones) during long lecture translations and recover gracefully from batch failures.

**Independent Test**: Submit a multi-batch subtitle file; verify Telegram status message updates smoothly without rate limits, and test automatic fallback on simulated batch error.

- [x] T021 [US3] Implement throttled progress bar message updater in `app/bot/handlers.py`
- [x] T022 [US3] Implement isolated batch retry with exponential backoff and fallback model transition in `app/core/engine.py`
- [x] T023 [P] [US3] Add unit tests for engine batch retry and error recovery in `tests/test_engine.py`

**Checkpoint**: Long lecture translation runs reliably with real-time feedback.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Cleanup, safety, documentation, and end-to-end validation

- [x] T024 [P] Create comprehensive `README.md` with architecture description and setup instructions
- [x] T025 Ensure safe temporary file lifecycle and cleanup in `app/bot/handlers.py`
- [x] T026 Execute quickstart validation scenarios according to `specs/001-academic-srt-translator/quickstart.md`

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: Completed.
- **Foundational (Phase 2)**: Completed.
- **User Story 1 (Phase 3 - MVP)**: Completed.
- **User Story 2 (Phase 4)**: Completed.
- **User Story 3 (Phase 5)**: Completed.
- **Polish (Phase 6)**: Completed.
