import pytest

pytestmark = pytest.mark.unit

"""Unit tests for the KDP-safe emoji replacement table."""

from manuscripta.data.emoji_map import EMOJI_MAP

CIRCLE = "◯"  # ◯, the replacement both globes share
DIAMETER_SIGN = "⌀"  # ⌀, a technical symbol that must not appear in prose

# Each row: an emoji and its replacement
REPLACEMENTS = [
    pytest.param("🌐", CIRCLE, id="globe-with-meridians-maps-to-circle"),
    pytest.param("🌍", CIRCLE, id="both-globes-share-the-same-replacement"),
]


@pytest.mark.parametrize("emoji, replacement", REPLACEMENTS)
def test_replacement(emoji, replacement):
    assert EMOJI_MAP[emoji] == replacement


def test_diameter_sign_is_no_longer_a_replacement():
    assert DIAMETER_SIGN not in EMOJI_MAP.values()


def test_every_entry_is_a_non_empty_string_pair():
    for emoji, replacement in EMOJI_MAP.items():
        assert isinstance(emoji, str) and emoji
        assert isinstance(replacement, str) and replacement
