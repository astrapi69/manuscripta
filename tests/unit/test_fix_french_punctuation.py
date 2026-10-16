import pytest

pytestmark = pytest.mark.unit

"""Unit tests for the French space before ; : ! ? in fix-french-quotes."""

import sys

from manuscripta.markdown.german_quotes import (
    ENGLISH,
    FRENCH,
    FR_PUNCTUATION_SPACE,
    GERMAN,
    GUILLEMET_CLOSE,
    GUILLEMET_OPEN,
    SPANISH,
    main_french,
    make_stats,
    mask_protected_regions,
    print_stats,
    process_file,
    space_punctuation,
)

NB = FR_PUNCTUATION_SPACE
GO, GC = GUILLEMET_OPEN, GUILLEMET_CLOSE


def respace(text: str, style=FRENCH) -> tuple[str, dict]:
    """Run ``text`` through the punctuation spacing stage only."""
    stats = make_stats()
    result = space_punctuation(text, mask_protected_regions(text), stats, style)
    return result, stats


# Each row: style, the space it sets before ; : ! ? (None: leaves that spacing
# alone), what "Quoi? Oui : non" becomes
PUNCTUATION_SPACE_CASES = [
    pytest.param(
        FRENCH,
        " ",
        f"Quoi{NB}? Oui{NB}: non",
        id="french-uses-the-no-break-space",
    ),
    pytest.param(GERMAN, None, "Quoi? Oui : non", id="german-leaves-punctuation-alone"),
    pytest.param(
        ENGLISH, None, "Quoi? Oui : non", id="english-leaves-punctuation-alone"
    ),
    pytest.param(
        SPANISH, None, "Quoi? Oui : non", id="spanish-leaves-punctuation-alone"
    ),
]


class TestStyles:
    @pytest.mark.parametrize("style, space, expected", PUNCTUATION_SPACE_CASES)
    def test_punctuation_space(self, style, space, expected):
        assert style.punctuation_space == space
        assert respace("Quoi? Oui : non", style)[0] == expected


# The marks that take the French space
MARKS = [";", ":", "!", "?"]

# Each row: the whitespace typed before a mark, the runs counted as changed
SPACES_BEFORE_A_MARK = [
    pytest.param("", 1, id="no-space"),
    pytest.param(" ", 1, id="space"),
    pytest.param(" ", 0, id="no-break-space"),
    pytest.param(" ", 1, id="narrow-no-break-space"),
    pytest.param("  ", 1, id="two-spaces"),
    pytest.param("\t", 1, id="tab"),
]

# Each row: text, expected result, the runs of marks whose spacing changed
RESPACE_CASES = [
    pytest.param(
        "Vraiment?!", f"Vraiment{NB}?!", 1, id="a-run-of-marks-gets-one-space"
    ),
    pytest.param(
        "Que vous souhaitiez:",
        f"Que vous souhaitiez{NB}:",
        1,
        id="mark-at-the-end-of-the-block",
    ),
    # French punctuation in Markdown
    pytest.param(
        "**Conseil:** Tenez", f"**Conseil{NB}:** Tenez", 1, id="markdown-colon-in-bold"
    ),
    pytest.param(
        "**Débutants** : Lisez",
        f"**Débutants**{NB}: Lisez",
        1,
        id="markdown-colon-after-bold",
    ),
    pytest.param(
        "_Remarque :_ certains",
        f"_Remarque{NB}:_ certains",
        1,
        id="markdown-colon-in-italic",
    ),
    pytest.param(
        "[Vous y trouverez :](#a)",
        f"[Vous y trouverez{NB}:](#a)",
        1,
        id="markdown-colon-in-a-link-text",
    ),
    pytest.param(
        "[Ce livre ?](#a)",
        f"[Ce livre{NB}?](#a)",
        1,
        id="markdown-question-mark-in-a-link-text",
    ),
    pytest.param(
        "pour [problème] ? Oui",
        f"pour [problème]{NB}? Oui",
        1,
        id="markdown-question-mark-after-a-bracket",
    ),
    pytest.param(
        f"{GO}Quoi?{GC}",
        f"{GO}Quoi{NB}?{GC}",
        1,
        id="markdown-question-mark-in-guillemets",
    ),
    pytest.param(
        "(vraiment !)",
        f"(vraiment{NB}!)",
        1,
        id="markdown-exclamation-mark-in-parentheses",
    ),
    pytest.param(
        "Note 1 : texte", f"Note 1{NB}: texte", 1, id="markdown-colon-after-a-digit"
    ),
    pytest.param(
        "(ex. : un cas)", f"(ex.{NB}: un cas)", 1, id="markdown-colon-after-a-period"
    ),
    pytest.param(
        "`a ? b` et c?", f"`a ? b` et c{NB}?", 1, id="inline-code-is-protected"
    ),
    pytest.param(
        '<a title="Quoi ?">ici</a> et la?',
        f'<a title="Quoi ?">ici</a> et la{NB}?',
        1,
        id="html-attribute-is-protected",
    ),
    pytest.param(
        f"Oui{NB}! Non ! Peut-etre?",
        f"Oui{NB}! Non{NB}! Peut-etre{NB}?",
        2,
        id="counts-changed-runs-only",
    ),
]

# Each row: text the stage leaves alone, where the marks are no French
# punctuation or none is there
UNCHANGED_CASES = [
    pytest.param("https://chat.openai.com", id="url-scheme"),
    pytest.param("[lien](https://x.org/page?id=1)", id="query-string-in-a-link"),
    pytest.param("Rendez-vous a 10:30", id="time-of-day"),
    pytest.param("Un sourire :)", id="smiley"),
    pytest.param("[^1]: La note", id="footnote-definition"),
    pytest.param("[id]: https://x.org", id="link-reference-definition"),
    pytest.param("| a :--- | ---: | :-: |", id="table-delimiter-row"),
    pytest.param("Le (?) demeure", id="mark-after-an-opening-bracket"),
    pytest.param("![image](a.png)", id="image"),
    pytest.param("<!-- commentaire -->", id="html-comment"),
    pytest.param("un&nbsp;blanc et &#8239; et &eacute;", id="html-entities"),
    pytest.param("Quoi\n? non", id="mark-at-a-line-start"),
    pytest.param("? en tete", id="mark-at-the-block-start"),
    pytest.param("Yahoo!Mail", id="mark-followed-by-a-letter"),
    pytest.param("", id="empty-block"),
]


class TestSpacePunctuation:
    @pytest.mark.parametrize("mark", MARKS)
    @pytest.mark.parametrize("space, changed", SPACES_BEFORE_A_MARK)
    def test_any_space_before_a_mark_becomes_the_no_break_space(
        self, mark, space, changed
    ):
        result, stats = respace(f"terme{space}{mark} suite")
        assert result == f"terme{NB}{mark} suite"
        assert stats["punctuation_space"] == changed

    @pytest.mark.parametrize("text, expected, changed", RESPACE_CASES)
    def test_french_punctuation_gets_the_no_break_space(self, text, expected, changed):
        result, stats = respace(text)
        assert result == expected
        assert stats["punctuation_space"] == changed

    @pytest.mark.parametrize("text", UNCHANGED_CASES)
    def test_markup_and_non_punctuation_stay(self, text):
        result, stats = respace(text)
        assert result == text
        assert stats["punctuation_space"] == 0


# Each row: text, expected result, the stats that must change. Every row also
# asserts no warning.
PROCESS_CASES = [
    pytest.param(
        'Il dit : "Vraiment?"',
        f"Il dit{NB}: {GO}{NB}Vraiment{NB}?{NB}{GC}",
        {"punctuation_space": 2, "guillemet_space": 2},
        id="quotes-and-punctuation-together",
    ),
    pytest.param(
        "## Pourquoi ?\n\n| Question | Avis |\n|---|---:|\n| Quoi? | Oui! |",
        f"## Pourquoi{NB}?\n\n| Question | Avis |\n|---|---:|\n"
        f"| Quoi{NB}? | Oui{NB}! |",
        {"punctuation_space": 3, "lines_changed": 2},
        id="heading-and-table-rows",
    ),
    pytest.param(
        "---\ntitle: Quoi?\n---\n```\nx = a ? b : c\n```",
        "---\ntitle: Quoi?\n---\n```\nx = a ? b : c\n```",
        {"punctuation_space": 0, "lines_changed": 0},
        id="code-block-and-frontmatter-stay",
    ),
    pytest.param(
        f"Quoi{NB}? Oui{NB}; non{NB}: peut-etre{NB}!",
        f"Quoi{NB}? Oui{NB}; non{NB}: peut-etre{NB}!",
        {"punctuation_space": 0, "lines_changed": 0},
        id="already-correct-text-is-unchanged",
    ),
]


class TestProcessFrench:
    @pytest.mark.parametrize("text, expected, expected_stats", PROCESS_CASES)
    def test_process_file(self, text, expected, expected_stats):
        stats = make_stats()
        warnings: list[str] = []
        result = process_file(text, stats, warnings, FRENCH)
        assert result == expected
        assert {key: stats[key] for key in expected_stats} == expected_stats
        assert warnings == []


# Each row: style, the summary lines it prints, the ones it leaves out. Every
# row reports 1 guillemet and 4 punctuation corrections.
SUMMARY_ROW_CASES = [
    pytest.param(
        FRENCH,
        [
            "  Space before ; : ! ?:       4 correction(s)",
            "  Total replacements:         5",
        ],
        [],
        id="french-shows-the-punctuation-row",
    ),
    pytest.param(GERMAN, [], ["Space before"], id="german-has-no-punctuation-row"),
    pytest.param(ENGLISH, [], ["Space before"], id="english-has-no-punctuation-row"),
    pytest.param(SPANISH, [], ["Space before"], id="spanish-has-no-punctuation-row"),
]


class TestReporting:
    @pytest.mark.parametrize("style, present, absent", SUMMARY_ROW_CASES)
    def test_summary_rows(self, style, present, absent, capsys):
        stats = make_stats()
        stats["guillemet_space"] = 1
        stats["punctuation_space"] = 4
        print_stats(stats, style)
        out = capsys.readouterr().out
        for line in present:
            assert line in out
        for text in absent:
            assert text not in out

    def test_main_french_writes_punctuation_only_changes(
        self, tmp_path, monkeypatch, capsys
    ):
        f = tmp_path / "a.md"
        f.write_text("Pourquoi ?", encoding="utf-8")
        monkeypatch.setattr(sys, "argv", ["fix-french-quotes", str(f)])
        main_french()
        assert f.read_text(encoding="utf-8") == f"Pourquoi{NB}?"
        assert "Space before ; : ! ?:       1 correction(s)" in capsys.readouterr().out
