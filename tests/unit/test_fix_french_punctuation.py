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


class TestStyles:
    def test_french_uses_the_no_break_space(self):
        assert FRENCH.punctuation_space == " "

    @pytest.mark.parametrize("style", [GERMAN, ENGLISH, SPANISH])
    def test_other_styles_leave_punctuation_alone(self, style):
        assert style.punctuation_space is None
        assert respace("Quoi? Oui : non", style)[0] == "Quoi? Oui : non"


class TestSpacePunctuation:
    @pytest.mark.parametrize("mark", [";", ":", "!", "?"])
    @pytest.mark.parametrize("space", ["", " ", " ", " ", "  ", "\t"])
    def test_any_space_before_a_mark_becomes_the_no_break_space(self, mark, space):
        result, stats = respace(f"terme{space}{mark} suite")
        assert result == f"terme{NB}{mark} suite"
        assert stats["punctuation_space"] == (0 if space == NB else 1)

    def test_a_run_of_marks_gets_one_space(self):
        assert respace("Vraiment?!")[0] == f"Vraiment{NB}?!"

    def test_mark_at_the_end_of_the_block(self):
        assert respace("Que vous souhaitiez:")[0] == f"Que vous souhaitiez{NB}:"

    @pytest.mark.parametrize(
        "text, expected",
        [
            ("**Conseil:** Tenez", f"**Conseil{NB}:** Tenez"),
            ("**Débutants** : Lisez", f"**Débutants**{NB}: Lisez"),
            ("_Remarque :_ certains", f"_Remarque{NB}:_ certains"),
            ("[Vous y trouverez :](#a)", f"[Vous y trouverez{NB}:](#a)"),
            ("[Ce livre ?](#a)", f"[Ce livre{NB}?](#a)"),
            ("pour [problème] ? Oui", f"pour [problème]{NB}? Oui"),
            (f"{GO}Quoi?{GC}", f"{GO}Quoi{NB}?{GC}"),
            ("(vraiment !)", f"(vraiment{NB}!)"),
            ("Note 1 : texte", f"Note 1{NB}: texte"),
            ("(ex. : un cas)", f"(ex.{NB}: un cas)"),
        ],
    )
    def test_french_punctuation_in_markdown(self, text, expected):
        assert respace(text)[0] == expected

    @pytest.mark.parametrize(
        "text",
        [
            "https://chat.openai.com",
            "[lien](https://x.org/page?id=1)",
            "Rendez-vous a 10:30",
            "Un sourire :)",
            "[^1]: La note",
            "[id]: https://x.org",
            "| a :--- | ---: | :-: |",
            "Le (?) demeure",
            "![image](a.png)",
            "<!-- commentaire -->",
            "un&nbsp;blanc et &#8239; et &eacute;",
            "Quoi\n? non",
            "? en tete",
            "Yahoo!Mail",
        ],
    )
    def test_markup_and_non_punctuation_stay(self, text):
        result, stats = respace(text)
        assert result == text
        assert stats["punctuation_space"] == 0

    def test_inline_code_is_protected(self):
        assert respace("`a ? b` et c?")[0] == f"`a ? b` et c{NB}?"

    def test_html_attribute_is_protected(self):
        text = '<a title="Quoi ?">ici</a> et la?'
        assert respace(text)[0] == f'<a title="Quoi ?">ici</a> et la{NB}?'

    def test_counts_changed_runs_only(self):
        result, stats = respace(f"Oui{NB}! Non ! Peut-etre?")
        assert result == f"Oui{NB}! Non{NB}! Peut-etre{NB}?"
        assert stats["punctuation_space"] == 2


class TestProcessFrench:
    def test_quotes_and_punctuation_together(self):
        stats = make_stats()
        result = process_file('Il dit : "Vraiment?"', stats, [], FRENCH)
        assert result == f"Il dit{NB}: {GO}{NB}Vraiment{NB}?{NB}{GC}"
        assert stats["punctuation_space"] == 2
        assert stats["guillemet_space"] == 2

    def test_heading_and_table_rows(self):
        text = "## Pourquoi ?\n\n| Question | Avis |\n|---|---:|\n| Quoi? | Oui! |"
        result = process_file(text, make_stats(), [], FRENCH)
        assert result == (
            f"## Pourquoi{NB}?\n\n| Question | Avis |\n|---|---:|\n"
            f"| Quoi{NB}? | Oui{NB}! |"
        )

    def test_code_block_and_frontmatter_stay(self):
        text = "---\ntitle: Quoi?\n---\n```\nx = a ? b : c\n```"
        assert process_file(text, make_stats(), [], FRENCH) == text

    def test_already_correct_text_is_unchanged(self):
        text = f"Quoi{NB}? Oui{NB}; non{NB}: peut-etre{NB}!"
        stats = make_stats()
        assert process_file(text, stats, [], FRENCH) == text
        assert stats["lines_changed"] == 0


class TestReporting:
    def test_print_stats_shows_the_punctuation_row(self, capsys):
        stats = make_stats()
        stats["guillemet_space"] = 1
        stats["punctuation_space"] = 4
        print_stats(stats, FRENCH)
        out = capsys.readouterr().out
        assert "  Space before ; : ! ?:       4 correction(s)" in out
        assert "  Total replacements:         5" in out

    @pytest.mark.parametrize("style", [GERMAN, ENGLISH, SPANISH])
    def test_other_styles_have_no_punctuation_row(self, style, capsys):
        print_stats(make_stats(), style)
        assert "Space before" not in capsys.readouterr().out

    def test_main_french_writes_punctuation_only_changes(
        self, tmp_path, monkeypatch, capsys
    ):
        f = tmp_path / "a.md"
        f.write_text("Pourquoi ?", encoding="utf-8")
        monkeypatch.setattr(sys, "argv", ["fix-french-quotes", str(f)])
        main_french()
        assert f.read_text(encoding="utf-8") == f"Pourquoi{NB}?"
        assert "Space before ; : ! ?:       1 correction(s)" in capsys.readouterr().out
