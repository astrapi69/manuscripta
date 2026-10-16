import pytest

pytestmark = pytest.mark.unit

# tests/test_replace_emojis_text.py
from manuscripta.markdown.emojis import replace_emojis_in_text

# Each row: the mapping, text, the text replaced, the replacements counted
REPLACE_EMOJI_CASES = [
    pytest.param(
        {"🔥": "+++", "📈": "↑"},
        "growth 📈 and energy 🔥🔥",
        "growth ↑ and energy ++++++",
        3,
        id="basic",
    ),
    # If one key were a substring of another (rare with emojis), length-desc
    # prevents partial; the keys simulate a multi-codepoint “emoji”
    pytest.param(
        {"AB": "X", "A": "Y"}, "AB A AB", "X Y X", 3, id="handles-overlap-order"
    ),
    pytest.param({"🧠": "★"}, "", "", 0, id="no-change-on-empty"),
    # "B" sorts after "AB" by code point; only the length order keeps the
    # longer key from being eaten by the shorter one
    pytest.param(
        {"AB": "X", "B": "Y"},
        "AB",
        "X",
        1,
        id="the-longer-key-wins-whatever-the-code-point-order",
    ),
]


@pytest.mark.parametrize("mapping, text, expected, count", REPLACE_EMOJI_CASES)
def test_replace_emojis_in_text(mapping, text, expected, count):
    out, n = replace_emojis_in_text(text, mapping)
    assert out == expected
    assert n == count
