# Core API Contract: Subtitle Engine

## 1. Subtitle Parser (`app.core.srt_parser`)

```python
class SrtParser:
    @staticmethod
    def parse(content: str) -> list[SubtitleCue]:
        """
        Parses raw SRT string content into a list of SubtitleCue objects.
        Handles BOM, mixed CRLF/LF, irregular blank lines, and timestamp variants.
        Raises ValueError if content contains no valid subtitle cues.
        """
        ...

    @staticmethod
    def serialize(cues: list[SubtitleCue], use_translated: bool = True) -> str:
        """
        Serializes a list of SubtitleCue objects back to standard SRT format.
        If use_translated=True, writes cue.translated_text (falling back to cue.text if untranslated).
        Guarantees CRLF formatting standard and valid comma millisecond separators.
        """
        ...
```

---

## 2. Context Batcher (`app.core.batcher`)

```python
class ContextBatcher:
    def __init__(self, batch_size: int = 15, pre_context_size: int = 2, post_context_size: int = 2):
        ...

    def create_batches(self, cues: list[SubtitleCue], context: AcademicContext) -> list[TranslationBatch]:
        """
        Splits cues into contextual batches with pre_context and post_context windows.
        """
        ...
```

---

## 3. Translation Engine (`app.core.engine`)

```python
class TranslationEngine:
    async def translate_batch(
        self,
        batch: TranslationBatch,
        context: AcademicContext
    ) -> dict[str, str]:
        """
        Submits active cues to LLM with pre-context and post-context.
        Validates 100% cue key parity in returned JSON.
        Implements fallback chain across configured models on HTTP/API errors.
        Returns mapping: {"C1": "...", "C2": "...", ...}
        """
        ...

    async def translate_document(
        self,
        document: SubtitleDocument,
        context: AcademicContext,
        on_progress: Optional[Callable[[float, int, int], Awaitable[None]]] = None
    ) -> SubtitleDocument:
        """
        Coordinates full translation workflow across all batches.
        Calls on_progress(percentage, cues_done, total_cues) if provided.
        Returns document with all cues populated with translated_text.
        """
        ...
```
