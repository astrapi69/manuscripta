"""Unit tests for manuscripta.translation.shortcuts and shortcuts_lms - the
console-script wrappers around the DeepL and LM Studio translators.

Each wrapper rewrites ``sys.argv`` and calls the underlying ``main`` with no
arguments, so the argv it hands over is ``sys.argv`` as that main sees it.
Both mains are replaced by recorders; nothing is translated.
"""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

import manuscripta.translation.shortcuts as deepl_sc
import manuscripta.translation.shortcuts_lms as lms_sc

# The attribute each module calls as the underlying translator main
MAIN_OF = {
    deepl_sc: "export_translate_book_deepl_main",
    lms_sc: "export_translate_book_lmstudio_main",
}
MODULES = [pytest.param(deepl_sc, id="deepl"), pytest.param(lms_sc, id="lmstudio")]
PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"


def argv_for(source: str, target: str, base_dir: str) -> list[str]:
    """The argv both shortcut modules hand to their translator main. The LM
    Studio shortcuts name the DeepL program too; argparse ignores argv[0]."""
    return [
        "translate-book-deepl",
        "--base-dir",
        base_dir,
        "--source-lang",
        source,
        "--target-lang",
        target,
    ]


@pytest.fixture
def mains(monkeypatch):
    """Replace both translator mains; each records sys.argv as it was called
    with. sys.argv is restored after the test, as the wrappers reassign it."""
    monkeypatch.setattr(sys, "argv", ["pytest"])
    calls: dict = {module: [] for module in MAIN_OF}
    for module, name in MAIN_OF.items():
        monkeypatch.setattr(
            module, name, lambda module=module: calls[module].append(list(sys.argv))
        )
    return calls


# --- the fixed wrappers and translate_manuscript ---------------------------

# Each row: the module, the wrapper, its arguments and the argv the translator
# main receives
WRAPPER_CASES = [
    pytest.param(
        deepl_sc,
        deepl_sc.translate_manuscript_to_german,
        (),
        argv_for("EN", "DE", "manuscript"),
        id="deepl-en-de",
    ),
    pytest.param(
        deepl_sc,
        deepl_sc.translate_manuscript_from_german_to_english,
        (),
        argv_for("DE", "EN", "manuscript"),
        id="deepl-de-en",
    ),
    pytest.param(
        deepl_sc,
        deepl_sc.translate_manuscript_from_english_to_spanish,
        (),
        argv_for("EN", "ES", "manuscript"),
        id="deepl-en-es",
    ),
    pytest.param(
        deepl_sc,
        deepl_sc.translate_manuscript_from_german_to_spanish,
        (),
        argv_for("DE", "ES", "manuscript"),
        id="deepl-de-es",
    ),
    pytest.param(
        deepl_sc,
        deepl_sc.translate_manuscript,
        ("FR", "IT", "docs/book"),
        argv_for("FR", "IT", "docs/book"),
        id="deepl-custom-folder",
    ),
    pytest.param(
        lms_sc,
        lms_sc.translate_manuscript_from_english_to_german,
        (),
        argv_for("EN", "DE", "manuscript"),
        id="lmstudio-en-de",
    ),
    pytest.param(
        lms_sc,
        lms_sc.translate_manuscript_from_german_to_english,
        (),
        argv_for("DE", "EN", "manuscript"),
        id="lmstudio-de-en",
    ),
    pytest.param(
        lms_sc,
        lms_sc.translate_manuscript_from_english_to_spanish,
        (),
        argv_for("EN", "ES", "manuscript"),
        id="lmstudio-en-es",
    ),
    pytest.param(
        lms_sc,
        lms_sc.translate_manuscript_from_english_to_french,
        (),
        argv_for("EN", "FR", "manuscript"),
        id="lmstudio-en-fr",
    ),
    pytest.param(
        lms_sc,
        lms_sc.translate_manuscript,
        ("FR", "IT", "docs/book"),
        argv_for("FR", "IT", "docs/book"),
        id="lmstudio-custom-folder",
    ),
]


@pytest.mark.parametrize("module, wrapper, args, argv", WRAPPER_CASES)
def test_wrappers_hand_their_argv_to_the_translator_main(
    module, wrapper, args, argv, mains
):
    wrapper(*args)
    assert mains.pop(module) == [argv]
    # The other translator is not called.
    assert list(mains.values()) == [[]]


# Each row: a console script of the wheel ([project.scripts]) and the wrapper it runs
SCRIPT_CASES = [
    pytest.param("translate", deepl_sc.translate, id="translate"),
    pytest.param(
        "translate-en-de", deepl_sc.translate_manuscript_to_german, id="en-de"
    ),
    pytest.param(
        "translate-de-en",
        deepl_sc.translate_manuscript_from_german_to_english,
        id="de-en",
    ),
    pytest.param(
        "translate-en-es",
        deepl_sc.translate_manuscript_from_english_to_spanish,
        id="en-es",
    ),
    pytest.param(
        "translate-de-es",
        deepl_sc.translate_manuscript_from_german_to_spanish,
        id="de-es",
    ),
    pytest.param(
        "translate-book-en-de",
        lms_sc.translate_manuscript_from_english_to_german,
        id="book-en-de",
    ),
    pytest.param(
        "translate-book-de-en",
        lms_sc.translate_manuscript_from_german_to_english,
        id="book-de-en",
    ),
    pytest.param(
        "translate-book-en-es",
        lms_sc.translate_manuscript_from_english_to_spanish,
        id="book-en-es",
    ),
    pytest.param(
        "translate-book-en-fr",
        lms_sc.translate_manuscript_from_english_to_french,
        id="book-en-fr",
    ),
]


@pytest.mark.parametrize("script, wrapper", SCRIPT_CASES)
def test_console_scripts_point_at_the_wrappers(script, wrapper):
    scripts = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]["scripts"]
    assert scripts[script] == f"{wrapper.__module__}:{wrapper.__name__}"


# --- the translate CLI -----------------------------------------------------

# Each row: the command line after the program name, the exit status (None:
# returns normally), the argv the translator main receives (None: not
# called), the lines stdout must carry and the stderr fragment (None: nothing)
CLI_CASES = [
    pytest.param(
        ["--from", "EN", "--to", "DE"],
        None,
        argv_for("EN", "DE", "manuscript"),
        ["🌍 Translating from English → German", "📂 Folder: manuscript"],
        None,
        id="default-folder",
    ),
    pytest.param(
        ["--from", "DE", "--to", "ES", "--dir", "book/src"],
        None,
        argv_for("DE", "ES", "book/src"),
        ["🌍 Translating from German → Spanish", "📂 Folder: book/src"],
        None,
        id="custom-folder",
    ),
    pytest.param(
        ["--from", "FR", "--to", "FR"],
        1,
        None,
        ["❌ Source and target languages must differ: both are 'FR'"],
        None,
        id="same-language-exits-1",
    ),
    pytest.param(
        ["--from", "EN", "--to", "XX"],
        2,
        None,
        [],
        "argument --to: invalid choice: 'XX'",
        id="unsupported-target",
    ),
    pytest.param(
        ["--from", "en", "--to", "DE"],
        2,
        None,
        [],
        "argument --from: invalid choice: 'en'",
        id="codes-are-upper-case",
    ),
    pytest.param(
        ["--from", "EN"],
        2,
        None,
        [],
        "the following arguments are required: --to",
        id="target-required",
    ),
    pytest.param(
        ["--help"], 0, None, ["usage:", "--from", "--to", "--dir"], None, id="help"
    ),
]


@pytest.mark.parametrize("module", MODULES)
@pytest.mark.parametrize("argv, exit_code, forwarded, out_lines, err", CLI_CASES)
def test_translate_cli(
    module, argv, exit_code, forwarded, out_lines, err, mains, monkeypatch, capsys
):
    monkeypatch.setattr(sys, "argv", ["translate", *argv])
    if exit_code is None:
        module.translate()
    else:
        with pytest.raises(SystemExit) as exc:
            module.translate()
        assert exc.value.code == exit_code
    assert mains.pop(module) == ([forwarded] if forwarded else [])
    assert list(mains.values()) == [[]]
    captured = capsys.readouterr()
    for line in out_lines:
        assert line in captured.out
    if err:
        assert err in captured.err
