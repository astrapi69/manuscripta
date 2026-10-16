import pytest

pytestmark = pytest.mark.unit

# tests/test_replace_md_bullet_points.py

from manuscripta.markdown.bullet_points import convert_bullets_in_text

# Each row: text and the text with its bullets converted
BULLET_CASES = [
    pytest.param(
        "- First item\n* Second item\nNormal line\n",
        "• First item  \n• Second item  \nNormal line\n",
        id="simple-dash-and-star-bullets",
    ),
    pytest.param(
        "- First item with continuation line\n"
        "  second line of the item\n"
        "Next normal line\n",
        "• First item with continuation line  \n"
        "  second line of the item  \n"
        "Next normal line\n",
        id="multiline-bullet-item",
    ),
    pytest.param(
        "- Point one\nNormal line\n  Not a follow-item, just indented\n",
        "• Point one  \nNormal line\n  Not a follow-item, just indented\n",
        id="list-state-resets-for-non-indented-line",
    ),
    pytest.param(
        "```python\n- this is not a bullet, but code\n```\n- actual bullet\n",
        "```python\n- this is not a bullet, but code\n```\n• actual bullet  \n",
        id="code-block-is-ignored",
    ),
    pytest.param(
        "Normal line\n"
        "  indented line without a list\n"
        "- List item\n"
        "  continuation line\n",
        "Normal line\n"
        "  indented line without a list\n"
        "• List item  \n"
        "  continuation line  \n",
        id="indented-follow-line-without-list-start-not-treated-as-bullet",
    ),
]


@pytest.mark.parametrize("text, expected", BULLET_CASES)
def test_convert_bullets_in_text(text, expected):
    assert convert_bullets_in_text(text) == expected
