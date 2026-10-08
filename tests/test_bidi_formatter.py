"""تست‌های جامع برای ماژول اصلاح چیدمان دوجهته (BiDi Formatter)."""

from app.core.bidi_formatter import fix_bidi_text, RLM, LRM


def test_bidi_parenthesized_english():
    text = "برخی از اصول استاتیک (Statics) مرور کنید، که"
    fixed = fix_bidi_text(text)
    assert f"{RLM}({LRM}Statics{LRM}){RLM}" in fixed
    assert fixed.startswith(RLM)


def test_bidi_line_starting_with_parenthesis():
    text = "(Parallel Axis Theorem) را بدانید. بنابراین، این بسیار مهم است."
    fixed = fix_bidi_text(text)
    assert fixed.startswith(RLM)
    assert f"{RLM}({LRM}Parallel Axis Theorem{LRM}){RLM}" in fixed


def test_bidi_line_starting_with_english_word():
    text = "X در مساحت است. همه متوجه شدید؟"
    fixed = fix_bidi_text(text)
    assert fixed.startswith(RLM)


def test_bidi_line_ending_with_parenthesis_and_dot():
    text = "این یک اصل است (Equilibrium)."
    fixed = fix_bidi_text(text)
    assert f"{RLM}({LRM}Equilibrium{LRM}){RLM}." in fixed


def test_bidi_pure_english_untouched():
    text = "Hello world 123"
    fixed = fix_bidi_text(text)
    assert fixed == text  # Should not be modified since no Persian chars
