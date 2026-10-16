import pytest

pytestmark = pytest.mark.unit

"""Unit tests for fix-french-quotes and fix-spanish-quotes (guillemets)."""

import sys

from manuscripta.markdown.german_quotes import (
    DE_CLOSE_DOUBLE,
    DE_OPEN_DOUBLE,
    ENGLISH,
    EN_CLOSE_DOUBLE,
    EN_CLOSE_SINGLE,
    EN_OPEN_DOUBLE,
    EN_OPEN_SINGLE,
    FRENCH,
    FR_GUILLEMET_SPACE,
    GERMAN,
    GUILLEMET_CLOSE,
    GUILLEMET_OPEN,
    SPANISH,
    _converts_english_single,
    _nests_english_double,
    find_paired_guillemets,
    main_french,
    main_spanish,
    make_stats,
    mask_protected_regions,
    print_stats,
    process_block,
    process_file,
    replace_english_double_quotes,
    space_guillemets,
)

GO, GC = GUILLEMET_OPEN, GUILLEMET_CLOSE
NB = FR_GUILLEMET_SPACE
OS, CS = EN_OPEN_SINGLE, EN_CLOSE_SINGLE


def fr(text: str) -> str:
    """French quotation: guillemets with a no-break space inside."""
    return f"{GO}{NB}{text}{NB}{GC}"


def es(text: str) -> str:
    """Spanish quotation: guillemets without a space inside."""
    return f"{GO}{text}{GC}"


def convert(text: str, style) -> tuple[str, dict, list]:
    """Run ``text`` through process_file with ``style``."""
    stats = make_stats()
    warnings: list[str] = []
    return process_file(text, stats, warnings, style), stats, warnings


def respace(text: str, style) -> tuple[str, dict]:
    """Run ``text`` through the guillemet spacing stage only."""
    stats = make_stats()
    result = space_guillemets(text, mask_protected_regions(text), stats, style)
    return result, stats


# ---------------------------------------------------------------------------
# Styles
# ---------------------------------------------------------------------------
class TestStyles:
    @pytest.mark.parametrize("style", [FRENCH, SPANISH])
    def test_guillemets_and_english_single_quotes(self, style):
        assert (style.open_double, style.close_double) == ("«", "»")
        assert (style.open_single, style.close_single) == ("‘", "’")
        assert style.convert_straight_single
        # the English-typographic stage runs for the top-level pairs (#16)
        assert style.convert_english_typographic

    def test_french_space_is_the_no_break_space(self):
        assert FRENCH.guillemet_space == " "

    def test_spanish_has_no_space(self):
        assert SPANISH.guillemet_space == ""

    @pytest.mark.parametrize("style", [GERMAN, ENGLISH])
    def test_german_and_english_leave_guillemet_spacing_alone(self, style):
        assert style.guillemet_space is None


# ---------------------------------------------------------------------------
# space_guillemets
# ---------------------------------------------------------------------------
class TestSpaceGuillemets:
    @pytest.mark.parametrize(
        "text",
        [
            f"{GO}texte{GC}",
            f"{GO} texte {GC}",
            f"{GO} texte {GC}",
            f"{GO} texte {GC}",
            f"{GO}  texte\t{GC}",
        ],
    )
    def test_french_gets_one_no_break_space(self, text):
        assert respace(text, FRENCH)[0] == fr("texte")

    @pytest.mark.parametrize(
        "text",
        [
            f"{GO}texto{GC}",
            f"{GO} texto {GC}",
            f"{GO} texto {GC}",
        ],
    )
    def test_spanish_loses_the_space(self, text):
        assert respace(text, SPANISH)[0] == es("texto")

    def test_counts_changed_guillemets_only(self):
        text = f"{GO}{NB}juste{NB}{GC} et {GO}faux {GC}"
        result, stats = respace(text, FRENCH)
        assert result == f"{fr('juste')} et {fr('faux')}"
        assert stats["guillemet_space"] == 2

    def test_correct_text_is_unchanged_and_not_counted(self):
        text = fr("juste")
        result, stats = respace(text, FRENCH)
        assert result == text
        assert stats["guillemet_space"] == 0

    def test_guillemet_at_a_line_break_keeps_its_spacing(self):
        text = f"ligne {GO}\nsuite\n{GC} fin"
        assert respace(text, FRENCH)[0] == text

    def test_guillemet_at_the_block_edge_keeps_its_spacing(self):
        assert respace(GO, FRENCH)[0] == GO
        assert respace(GC, FRENCH)[0] == GC
        assert respace(f"x {GO}", FRENCH)[0] == f"x {GO}"

    @pytest.mark.parametrize("style", [FRENCH, SPANISH])
    def test_heading_marker_keeps_its_space(self, style):
        text = f"### {GC} Saltarse el refinamiento"
        result, stats = respace(text, style)
        assert result == text
        assert stats["guillemet_space"] == 0

    def test_lone_closing_guillemet_keeps_its_space(self):
        text = f"Suite {GC} et {GO}texte{GC}"
        assert respace(text, FRENCH)[0] == f"Suite {GC} et {fr('texte')}"

    def test_unclosed_opening_guillemet_keeps_its_space(self):
        text = f"{GO} Le dialogue continue, sans fin"
        assert respace(text, FRENCH)[0] == text

    def test_nested_guillemets_are_spaced(self):
        text = f"{GO}il dit {GO}non{GC} puis part{GC}"
        assert respace(text, SPANISH)[0] == text
        assert respace(text, FRENCH)[0] == fr(f"il dit {fr('non')} puis part")

    def test_inline_code_is_protected(self):
        text = f"`{GO}code{GC}` et {GO}texte{GC}"
        assert respace(text, FRENCH)[0] == f"`{GO}code{GC}` et {fr('texte')}"

    def test_style_without_guillemet_space_is_a_no_op(self):
        text = f"{GO} x {GC}"
        result, stats = respace(text, GERMAN)
        assert result == text
        assert stats["guillemet_space"] == 0


# ---------------------------------------------------------------------------
# process_file with the French and Spanish styles
# ---------------------------------------------------------------------------
class TestProcessFrench:
    def test_straight_quotes_and_apostrophes(self):
        result, stats, warnings = convert(
            '"Bonjour", dit-il. "C\'est l\'heure."', FRENCH
        )
        assert result == f"{fr('Bonjour')}, dit-il. {fr(f'C{CS}est l{CS}heure.')}"
        assert stats["straight_double"] == 2
        assert stats["straight_single"] == 2
        assert stats["guillemet_space"] == 4
        assert warnings == []

    def test_spaces_typed_inside_straight_quotes_become_no_break_spaces(self):
        assert convert('Il dit " oui ".', FRENCH)[0] == f"Il dit {fr('oui')}."

    def test_open_guillemet_takes_a_straight_closing_quote(self):
        assert convert(f'{GO} texte"', FRENCH)[0] == fr("texte")

    def test_quotation_split_by_a_hard_wrap(self):
        result, _, warnings = convert('Il dit "oui\net non" ici.', FRENCH)
        assert result == f"Il dit {GO}{NB}oui\net non{NB}{GC} ici."
        assert warnings == []

    def test_english_double_quotes_stay_as_second_level(self):
        text = f'"Il a dit {EN_OPEN_DOUBLE}non{EN_CLOSE_DOUBLE}."'
        assert convert(text, FRENCH)[0] == fr(
            f"Il a dit {EN_OPEN_DOUBLE}non{EN_CLOSE_DOUBLE}."
        )

    def test_german_quotes_are_left_alone(self):
        text = f"{DE_OPEN_DOUBLE}Hallo{DE_CLOSE_DOUBLE}"
        assert convert(text, FRENCH)[0] == text

    def test_single_quote_after_a_guillemet_opens(self):
        result, _, warnings = convert(f"{GO}'terme'{GC}", FRENCH)
        assert result == fr(f"{OS}terme{CS}")
        assert warnings == []

    def test_odd_straight_double_quote_warns(self):
        result, stats, warnings = convert('"Seul', FRENCH)
        assert result == '"Seul'
        assert len(warnings) == 1
        assert stats["warnings"] == 1

    def test_html_attribute_and_frontmatter_are_untouched(self):
        text = '---\ntitle: "Titre"\n---\n<img alt="x"> "y"'
        result, _, _ = convert(text, FRENCH)
        assert result == f'---\ntitle: "Titre"\n---\n<img alt="x"> {fr("y")}'

    def test_lines_changed_counts_lines_not_guillemets(self):
        _, stats, _ = convert(f"{GO}a{GC} {GO}b{GC}\n\nsans", FRENCH)
        assert stats["lines_changed"] == 1
        assert stats["guillemet_space"] == 4

    def test_already_french_text_is_unchanged(self):
        text = f"{fr('Oui')}, dit-il, l{CS}homme."
        result, stats, warnings = convert(text, FRENCH)
        assert result == text
        assert stats["lines_changed"] == 0
        assert warnings == []


class TestFindPairedGuillemets:
    def test_pairs_and_lone_guillemets(self):
        text = f"{GC} a {GO}b{GC} {GO}c"
        assert find_paired_guillemets(text, []) == {4, 6}

    def test_protected_guillemets_do_not_pair(self):
        text = f"`{GO}` b{GC}"
        assert find_paired_guillemets(text, mask_protected_regions(text)) == set()


class TestProcessSpanish:
    def test_straight_quotes_and_single_quotes(self):
        result, stats, warnings = convert(
            '"Hola", dijo, "¿qué tal?" con \'significado\'', SPANISH
        )
        assert result == (
            f"{es('Hola')}, dijo, {es('¿qué tal?')} con {OS}significado{CS}"
        )
        assert stats["straight_double"] == 2
        assert stats["straight_single"] == 2
        assert stats["guillemet_space"] == 0
        assert warnings == []

    def test_french_spacing_is_removed(self):
        result, stats, _ = convert(f"{GO} ya {GC} y {GO} esto {GC}", SPANISH)
        assert result == f"{es('ya')} y {es('esto')}"
        assert stats["guillemet_space"] == 4

    def test_english_double_quotes_stay_as_second_level(self):
        text = f'"Dijo {EN_OPEN_DOUBLE}no{EN_CLOSE_DOUBLE}."'
        assert convert(text, SPANISH)[0] == es(
            f"Dijo {EN_OPEN_DOUBLE}no{EN_CLOSE_DOUBLE}."
        )

    def test_process_block_defaults_to_german(self):
        assert process_block('"Hola"', 1, make_stats(), []) == (
            f"{DE_OPEN_DOUBLE}Hola{DE_CLOSE_DOUBLE}"
        )


# ---------------------------------------------------------------------------
# Reporting and CLI
# ---------------------------------------------------------------------------
class TestReporting:
    def test_print_stats_shows_the_guillemet_row(self, capsys):
        stats = make_stats()
        stats["straight_double"] = 1
        stats["straight_single"] = 2
        stats["guillemet_space"] = 3
        print_stats(stats, FRENCH)
        out = capsys.readouterr().out
        assert '  Straight " -> French:       1 pair(s)' in out
        assert "  Straight ' -> French:       2 mark(s)" in out
        assert "  Guillemet spacing:          3 correction(s)" in out
        assert "  English typographic double: 0 correction(s)" in out
        # ‘…’ is already the target of French, so that stage has no row
        assert "English typographic single" not in out
        assert "  Total replacements:         6" in out

    def test_english_has_no_guillemet_row(self, capsys):
        print_stats(make_stats(), ENGLISH)
        assert "Guillemet" not in capsys.readouterr().out


class TestMain:
    def test_french_file_mode(self, tmp_path, monkeypatch, capsys):
        f = tmp_path / "a.md"
        f.write_text('"C\'est" et « déjà »', encoding="utf-8")
        monkeypatch.setattr(sys, "argv", ["fix-french-quotes", str(f)])
        main_french()
        assert f.read_text(encoding="utf-8") == (f"{fr(f'C{CS}est')} et {fr('déjà')}")
        captured = capsys.readouterr()
        assert "Guillemet spacing:          4 correction(s)" in captured.out
        assert captured.err == ""

    def test_spanish_file_mode(self, tmp_path, monkeypatch, capsys):
        f = tmp_path / "a.md"
        f.write_text('"Hola" y « ya »', encoding="utf-8")
        monkeypatch.setattr(sys, "argv", ["fix-spanish-quotes", str(f)])
        main_spanish()
        assert f.read_text(encoding="utf-8") == f"{es('Hola')} y {es('ya')}"
        assert 'Straight " -> Spanish:      1 pair(s)' in capsys.readouterr().out

    def test_file_with_only_spacing_fixes_is_written(self, tmp_path, monkeypatch):
        f = tmp_path / "a.md"
        f.write_text("« déjà »", encoding="utf-8")
        monkeypatch.setattr(sys, "argv", ["fix-french-quotes", str(f)])
        main_french()
        assert f.read_text(encoding="utf-8") == fr("déjà")
        assert (tmp_path / "a.md.bak").exists()

    @pytest.mark.parametrize(
        "entry, prog, name",
        [
            (main_french, "fix-french-quotes", "French"),
            (main_spanish, "fix-spanish-quotes", "Spanish"),
        ],
    )
    def test_help_names_the_language(self, entry, prog, name, monkeypatch, capsys):
        monkeypatch.setenv("COLUMNS", "200")
        monkeypatch.setattr(sys, "argv", [prog, "--help"])
        with pytest.raises(SystemExit):
            entry()
        assert f"to {name} typographic style" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# English “…” pairs: top-level ones become guillemets, nested ones stay (#16)
# ---------------------------------------------------------------------------
def en(text: str) -> str:
    """An English typographic quotation."""
    return f"{EN_OPEN_DOUBLE}{text}{EN_CLOSE_DOUBLE}"


class TestEnglishDoubleQuotesInGuillemetStyles:
    @pytest.mark.parametrize(
        "style, expected",
        [(GERMAN, False), (ENGLISH, False), (FRENCH, True), (SPANISH, True)],
    )
    def test_nests_english_double(self, style, expected):
        assert _nests_english_double(style) is expected

    @pytest.mark.parametrize(
        "style, expected",
        [(GERMAN, True), (ENGLISH, False), (FRENCH, False), (SPANISH, False)],
    )
    def test_converts_english_single(self, style, expected):
        assert _converts_english_single(style) is expected

    def test_spanish_converts_a_top_level_pair(self):
        text = f"aquello que percibimos como {en('realidad')} es real en absoluto."
        result, stats, warnings = convert(text, SPANISH)
        assert (
            result
            == f"aquello que percibimos como {es('realidad')} es real en absoluto."
        )
        assert stats["english_double"] == 1
        assert warnings == []

    def test_french_converts_a_top_level_pair_and_spaces_it(self):
        text = f"ce que nous appelons {en('réalité')}."
        result, stats, _ = convert(text, FRENCH)
        assert result == f"ce que nous appelons {fr('réalité')}."
        assert stats["english_double"] == 1
        assert stats["guillemet_space"] == 2

    def test_several_pairs_in_one_block(self):
        text = f"¿existe acaso algún {en('sentido verdadero')} o {en('fin')}?"
        assert convert(text, SPANISH)[0] == (
            f"¿existe acaso algún {es('sentido verdadero')} o {es('fin')}?"
        )

    @pytest.mark.parametrize("style", [FRENCH, SPANISH])
    def test_a_pair_inside_guillemets_stays_as_second_level(self, style):
        text = f"{GO}Dijo {en('no')} y se fue{GC}"
        result, stats, _ = convert(text, style)
        assert en("no") in result
        assert stats["english_double"] == 0

    def test_a_pair_inside_a_straight_pair_stays_as_second_level(self):
        # The straight pair becomes guillemets first; the pair inside is nested
        result, stats, _ = convert(f'"Dijo {en("no")}."', SPANISH)
        assert result == es(f"Dijo {en('no')}.")
        assert stats["english_double"] == 0

    def test_top_level_and_nested_pairs_in_one_block(self):
        text = f"{en('sí')} y {GO}dijo {en('no')}{GC}"
        assert convert(text, SPANISH)[0] == f"{es('sí')} y {GO}dijo {en('no')}{GC}"

    def test_a_pair_after_a_closed_guillemet_pair_converts(self):
        text = f"{es('uno')} y {en('dos')}"
        assert convert(text, SPANISH)[0] == f"{es('uno')} y {es('dos')}"

    def test_a_pair_wrapping_guillemets_converts(self):
        text = en(f"a {es('b')} c")
        assert convert(text, SPANISH)[0] == es(f"a {es('b')} c")

    def test_a_lone_closing_quote_becomes_a_closing_guillemet(self):
        assert convert(f"hola{EN_CLOSE_DOUBLE} y adiós", SPANISH)[0] == (
            f"hola{GC} y adiós"
        )

    def test_a_lone_closing_quote_inside_guillemets_stays(self):
        text = f"{GO}hola{EN_CLOSE_DOUBLE} y adiós{GC}"
        assert convert(text, SPANISH)[0] == text

    def test_a_lone_opening_quote_stays(self):
        text = f"{EN_OPEN_DOUBLE}hola y adiós"
        assert convert(text, SPANISH)[0] == text

    def test_a_pair_in_inline_code_stays(self):
        text = f"usa `{en('x')}` aquí"
        assert convert(text, SPANISH)[0] == text

    def test_a_pair_in_an_html_attribute_stays(self):
        text = f'<span title="{en("x")}">y</span>'
        assert convert(text, SPANISH)[0] == text

    def test_straight_and_english_pairs_in_one_block(self):
        assert convert(f'"uno" y {en("dos")}', SPANISH)[0] == (
            f"{es('uno')} y {es('dos')}"
        )

    def test_an_unclosed_guillemet_hides_the_rest_of_the_block(self):
        text = f"{GO}abierto y {en('dos')}"
        assert convert(text, SPANISH)[0] == text

    def test_english_single_quotes_are_already_the_target(self):
        text = f"{OS}significado{CS}"
        result, stats, _ = convert(text, SPANISH)
        assert result == text
        assert stats["english_single"] == 0

    def test_stage_alone_with_the_spanish_style(self):
        stats = make_stats()
        text = f"{en('a')} {GO}{en('b')}{GC}"
        result = replace_english_double_quotes(
            text, mask_protected_regions(text), stats, SPANISH
        )
        assert result == f"{es('a')} {GO}{en('b')}{GC}"
        assert stats["english_double"] == 1

    def test_stage_defaults_to_german(self):
        stats = make_stats()
        text = en("a")
        result = replace_english_double_quotes(
            text, mask_protected_regions(text), stats
        )
        assert result == f"{DE_OPEN_DOUBLE}a{DE_CLOSE_DOUBLE}"

    def test_german_cannot_nest_and_converts_every_pair(self):
        # “ is both the German closer and the English opener, so an open
        # German pair cannot be tracked: every English pair converts
        text = f"{DE_OPEN_DOUBLE}Er sagte {en('nein')}{DE_CLOSE_DOUBLE}"
        result, stats, _ = convert(text, GERMAN)
        assert result == (
            f"{DE_OPEN_DOUBLE}Er sagte {DE_OPEN_DOUBLE}nein{DE_CLOSE_DOUBLE}"
            f"{DE_CLOSE_DOUBLE}"
        )
        assert stats["english_double"] == 1

    def test_english_leaves_its_own_quotes_alone(self):
        text = f"{en('fine')} and {es('inner')}"
        result, stats, _ = convert(text, ENGLISH)
        assert result == text
        assert stats["english_double"] == 0

    def test_spanish_summary_shows_the_double_row_only(self, capsys):
        stats = make_stats()
        stats["english_double"] = 2
        print_stats(stats, SPANISH)
        out = capsys.readouterr().out
        assert "  English typographic double: 2 correction(s)" in out
        assert "English typographic single" not in out
        assert "  Total replacements:         2" in out

    def test_spanish_file_mode_converts_english_pairs(
        self, tmp_path, monkeypatch, capsys
    ):
        f = tmp_path / "foreword.md"
        f.write_text(
            f"… aquello que percibimos como {en('realidad')} es real en absoluto.\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(sys, "argv", ["fix-spanish-quotes", str(f)])
        main_spanish()
        assert f.read_text(encoding="utf-8") == (
            f"… aquello que percibimos como {es('realidad')} es real en absoluto.\n"
        )
        captured = capsys.readouterr()
        assert "English typographic double: 1 correction(s)" in captured.out
        assert captured.err == ""
