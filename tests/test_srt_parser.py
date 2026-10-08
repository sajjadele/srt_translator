"""تست‌های جامع واحد برای پارسر و سریال‌ساز SRT."""

import pytest
from app.core.srt_parser import SrtParser, normalize_timestamp
from app.core.models import SubtitleCue, SubtitleDocument


SAMPLE_STANDARD_SRT = """1
00:00:01,000 --> 00:00:03,500
Welcome to Machine Learning lecture.

2
00:00:04,100 --> 00:00:07,800
Today we are discussing
gradient descent and cost functions.

3
00:00:08,200 --> 00:00:11,000
Let's start with the basics.
"""

SAMPLE_QUIRKY_SRT = """\ufeff1
00:00:01.000 --> 00:00:03.500  X1:000 Y1:000
Welcome to Machine Learning lecture.

00:00:04.100 --> 00:00:07.800
Today we are discussing gradient descent.
"""


def test_normalize_timestamp():
    assert normalize_timestamp("0:01:23.45") == "00:01:23,450"
    assert normalize_timestamp("00:00:05,123") == "00:00:05,123"
    assert normalize_timestamp("1:2:3.4") == "01:02:03,400"


def test_parse_standard_srt():
    doc = SrtParser.parse_text(SAMPLE_STANDARD_SRT, filename="test.srt")
    assert doc.total_cues == 3
    assert doc.cues[0].index == 1
    assert doc.cues[0].start_time == "00:00:01,000"
    assert doc.cues[0].end_time == "00:00:03,500"
    assert doc.cues[0].text == "Welcome to Machine Learning lecture."

    # Multiline check
    assert doc.cues[1].index == 2
    assert "gradient descent" in doc.cues[1].text
    assert "\n" in doc.cues[1].text


def test_parse_quirky_srt():
    # Handles BOM, dot millisecond separators, and missing cue numbers
    doc = SrtParser.parse_text(SAMPLE_QUIRKY_SRT, filename="quirky.srt")
    assert doc.total_cues == 2
    assert doc.cues[0].start_time == "00:00:01,000"
    assert doc.cues[0].end_time == "00:00:03,500"
    assert doc.cues[1].start_time == "00:00:04,100"


def test_serialization_roundtrip(tmp_path):
    doc = SrtParser.parse_text(SAMPLE_STANDARD_SRT)
    # Add translation to cue 1
    doc.cues[0].translated_text = "به جلسه یادگیری ماشین خوش آمدید."
    doc.cues[1].translated_text = "امروز درباره گرادیان نزولی بحث می‌کنیم."

    serialized = SrtParser.serialize(doc, use_translated=True)
    assert "به جلسه یادگیری ماشین خوش آمدید." in serialized
    assert "00:00:01,000 --> 00:00:03,500" in serialized

    # Save to file and re-parse
    out_file = tmp_path / "out_fa.srt"
    SrtParser.write_file(doc, out_file, use_translated=True)
    reloaded = SrtParser.parse_file(out_file)

    assert reloaded.total_cues == 3
    assert reloaded.cues[0].text == "به جلسه یادگیری ماشین خوش آمدید."
    assert reloaded.cues[2].text == "Let's start with the basics."  # Untranslated falls back cleanly


def test_parse_empty_content_raises_error():
    with pytest.raises(ValueError):
        SrtParser.parse_text("   \n\n   ")
