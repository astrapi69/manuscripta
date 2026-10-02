import pytest

pytestmark = pytest.mark.unit

"""Unit tests for the KDP-safe emoji replacement table."""

from manuscripta.data.emoji_map import EMOJI_MAP

CIRCLE = "◯"  # ◯, the replacement both globe emojis share
DIAMETER_SIGN = "⌀"  # ⌀, a technical symbol that must not appear in prose


def test_globe_with_meridians_maps_to_circle():
    assert EMOJI_MAP["🌐"] == CIRCLE


def test_both_globes_share_the_same_replacement():
    assert EMOJI_MAP["🌐"] == EMOJI_MAP["🌍"]


def test_diameter_sign_is_no_longer_a_replacement():
    assert DIAMETER_SIGN not in EMOJI_MAP.values()


def test_every_entry_is_a_non_empty_string_pair():
    for emoji, replacement in EMOJI_MAP.items():
        assert isinstance(emoji, str) and emoji
        assert isinstance(replacement, str) and replacement
