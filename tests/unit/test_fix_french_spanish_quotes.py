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
# The styles that write guillemets
GUILLEMET_STYLES = [
    pytest.param(FRENCH, id="french"),
    pytest.param(SPANISH, id="spanish"),
]

# Each row: style, the space it sets inside guillemets (None: leaves it alone)
GUILLEMET_SPACE_CASES = [
    pytest.param(FRENCH, " ", id="french-space-is-the-no-break-space"),
    pytest.param(SPANISH, "", id="spanish-has-no-space"),
    pytest.param(GERMAN, None, id="german-leaves-guillemet-spacing-alone"),
    pytest.param(ENGLISH, None, id="english-leaves-guillemet-spacing-alone"),
]


class TestStyles:
    @pytest.mark.parametrize("style", GUILLEMET_STYLES)
    def test_guillemets_and_english_single_quotes(self, style):
        assert (style.open_double, style.close_double) == ("«", "»")
        assert (style.open_single, style.close_single) == ("‘", "’")
        assert style.convert_straight_single
        # the English-typographic stage runs for the top-level pairs (#16)
        assert style.convert_english_typographic

    @pytest.mark.parametrize("style, space", GUILLEMET_SPACE_CASES)
    def test_guillemet_space(self, style, space):
        assert style.guillemet_space == space


# ---------------------------------------------------------------------------
# space_guillemets
# ---------------------------------------------------------------------------
# Each row: style, text, expected result, the guillemets whose spacing changed
SPACING_CASES = [
    # French gets one no-break space
    pytest.param(FRENCH, f"{GO}texte{GC}", fr("texte"), 2, id="french-no-space"),
    pytest.param(FRENCH, f"{GO} texte {GC}", fr("texte"), 2, id="french-spaces"),
    pytest.param(
        FRENCH,
        f"{GO} texte {GC}",
        fr("texte"),
        0,
        id="french-no-break-spaces-stay",
    ),
    pytest.param(
        FRENCH,
        f"{GO} texte {GC}",
        fr("texte"),
        2,
        id="french-narrow-no-break-spaces",
    ),
    pytest.param(
        FRENCH, f"{GO}  texte\t{GC}", fr("texte"), 2, id="french-runs-of-whitespace"
    ),
    # Spanish loses the space
    pytest.param(
        SPANISH, f"{GO}texto{GC}", es("texto"), 0, id="spanish-no-space-stays"
    ),
    pytest.param(SPANISH, f"{GO} texto {GC}", es("texto"), 2, id="spanish-spaces"),
    pytest.param(
        SPANISH,
        f"{GO} texto {GC}",
        es("texto"),
        2,
        id="spanish-no-break-spaces",
    ),
    pytest.param(
        FRENCH,
        f"{GO}{NB}juste{NB}{GC} et {GO}faux {GC}",
        f"{fr('juste')} et {fr('faux')}",
        2,
        id="counts-changed-guillemets-only",
    ),
    pytest.param(
        FRENCH,
        fr("juste"),
        fr("juste"),
        0,
        id="correct-text-is-unchanged-and-not-counted",
    ),
    pytest.param(
        FRENCH,
        f"ligne {GO}\nsuite\n{GC} fin",
        f"ligne {GO}\nsuite\n{GC} fin",
        0,
        id="guillemet-at-a-line-break-keeps-its-spacing",
    ),
    # a guillemet at the block edge keeps its spacing
    pytest.param(FRENCH, GO, GO, 0, id="opening-guillemet-alone"),
    pytest.param(FRENCH, GC, GC, 0, id="closing-guillemet-alone"),
    pytest.param(
        FRENCH, f"x {GO}", f"x {GO}", 0, id="opening-guillemet-at-the-block-end"
    ),
    pytest.param(
        FRENCH,
        f"### {GC} Saltarse el refinamiento",
        f"### {GC} Saltarse el refinamiento",
        0,
        id="french-heading-marker-keeps-its-space",
    ),
    pytest.param(
        SPANISH,
        f"### {GC} Saltarse el refinamiento",
        f"### {GC} Saltarse el refinamiento",
        0,
        id="spanish-heading-marker-keeps-its-space",
    ),
    pytest.param(
        FRENCH,
        f"Suite {GC} et {GO}texte{GC}",
        f"Suite {GC} et {fr('texte')}",
        2,
        id="lone-closing-guillemet-keeps-its-space",
    ),
    pytest.param(
        FRENCH,
        f"{GO} Le dialogue continue, sans fin",
        f"{GO} Le dialogue continue, sans fin",
        0,
        id="unclosed-opening-guillemet-keeps-its-space",
    ),
    pytest.param(
        SPANISH,
        f"{GO}il dit {GO}non{GC} puis part{GC}",
        f"{GO}il dit {GO}non{GC} puis part{GC}",
        0,
        id="spanish-nested-guillemets-stay",
    ),
    pytest.param(
        FRENCH,
        f"{GO}il dit {GO}non{GC} puis part{GC}",
        fr(f"il dit {fr('non')} puis part"),
        4,
        id="french-nested-guillemets-are-spaced",
    ),
    pytest.param(
        FRENCH,
        f"`{GO}code{GC}` et {GO}texte{GC}",
        f"`{GO}code{GC}` et {fr('texte')}",
        2,
        id="inline-code-is-protected",
    ),
    pytest.param(
        GERMAN,
        f"{GO} x {GC}",
        f"{GO} x {GC}",
        0,
        id="style-without-guillemet-space-is-a-no-op",
    ),
    pytest.param(FRENCH, "", "", 0, id="empty-block"),
]


class TestSpaceGuillemets:
    @pytest.mark.parametrize("style, text, expected, changed", SPACING_CASES)
    def test_space_guillemets(self, style, text, expected, changed):
        result, stats = respace(text, style)
        assert result == expected
        assert stats["guillemet_space"] == changed


# ---------------------------------------------------------------------------
# process_file with the French and Spanish styles
# ---------------------------------------------------------------------------
# Each row: style, text, expected result, the stats that must change, the
# warnings
PROCESS_CASES = [
    pytest.param(
        FRENCH,
        '"Bonjour", dit-il. "C\'est l\'heure."',
        f"{fr('Bonjour')}, dit-il. {fr(f'C{CS}est l{CS}heure.')}",
        {"straight_double": 2, "straight_single": 2, "guillemet_space": 4},
        [],
        id="french-straight-quotes-and-apostrophes",
    ),
    pytest.param(
        FRENCH,
        'Il dit " oui ".',
        f"Il dit {fr('oui')}.",
        {"straight_double": 1, "guillemet_space": 2},
        [],
        id="spaces-typed-inside-straight-quotes-become-no-break-spaces",
    ),
    pytest.param(
        FRENCH,
        f'{GO} texte"',
        fr("texte"),
        {"straight_double": 1, "guillemet_space": 2},
        [],
        id="open-guillemet-takes-a-straight-closing-quote",
    ),
    pytest.param(
        FRENCH,
        'Il dit "oui\net non" ici.',
        f"Il dit {GO}{NB}oui\net non{NB}{GC} ici.",
        {"straight_double": 1, "guillemet_space": 2, "lines_changed": 2},
        [],
        id="quotation-split-by-a-hard-wrap",
    ),
    pytest.param(
        FRENCH,
        f'"Il a dit {EN_OPEN_DOUBLE}non{EN_CLOSE_DOUBLE}."',
        fr(f"Il a dit {EN_OPEN_DOUBLE}non{EN_CLOSE_DOUBLE}."),
        {"straight_double": 1, "english_double": 0},
        [],
        id="french-english-double-quotes-stay-as-second-level",
    ),
    pytest.param(
        FRENCH,
        f"{DE_OPEN_DOUBLE}Hallo{DE_CLOSE_DOUBLE}",
        f"{DE_OPEN_DOUBLE}Hallo{DE_CLOSE_DOUBLE}",
        {"lines_changed": 0},
        [],
        id="german-quotes-are-left-alone",
    ),
    pytest.param(
        FRENCH,
        f"{GO}'terme'{GC}",
        fr(f"{OS}terme{CS}"),
        {"straight_single": 2, "guillemet_space": 2},
        [],
        id="single-quote-after-a-guillemet-opens",
    ),
    pytest.param(
        FRENCH,
        '"Seul',
        '"Seul',
        {"straight_double": 0, "warnings": 1},
        [
            'Line 1: Asymmetric straight quotation mark (") '
            '- 1 unpaired occurrence(s)\n  Context: "Seul'
        ],
        id="odd-straight-double-quote-warns",
    ),
    pytest.param(
        FRENCH,
        '---\ntitle: "Titre"\n---\n<img alt="x"> "y"',
        f'---\ntitle: "Titre"\n---\n<img alt="x"> {fr("y")}',
        {"straight_double": 1, "guillemet_space": 2},
        [],
        id="html-attribute-and-frontmatter-are-untouched",
    ),
    pytest.param(
        FRENCH,
        f"{GO}a{GC} {GO}b{GC}\n\nsans",
        f"{fr('a')} {fr('b')}\n\nsans",
        {"lines_changed": 1, "guillemet_space": 4},
        [],
        id="lines-changed-counts-lines-not-guillemets",
    ),
    pytest.param(
        FRENCH,
        f"{fr('Oui')}, dit-il, l{CS}homme.",
        f"{fr('Oui')}, dit-il, l{CS}homme.",
        {"lines_changed": 0},
        [],
        id="already-french-text-is-unchanged",
    ),
    pytest.param(
        SPANISH,
        '"Hola", dijo, "¿qué tal?" con \'significado\'',
        f"{es('Hola')}, dijo, {es('¿qué tal?')} con {OS}significado{CS}",
        {"straight_double": 2, "straight_single": 2, "guillemet_space": 0},
        [],
        id="spanish-straight-quotes-and-single-quotes",
    ),
    pytest.param(
        SPANISH,
        f"{GO} ya {GC} y {GO} esto {GC}",
        f"{es('ya')} y {es('esto')}",
        {"guillemet_space": 4},
        [],
        id="french-spacing-is-removed",
    ),
    pytest.param(
        SPANISH,
        f'"Dijo {EN_OPEN_DOUBLE}no{EN_CLOSE_DOUBLE}."',
        es(f"Dijo {EN_OPEN_DOUBLE}no{EN_CLOSE_DOUBLE}."),
        {"straight_double": 1, "english_double": 0},
        [],
        id="spanish-english-double-quotes-stay-as-second-level",
    ),
]


class TestProcess:
    @pytest.mark.parametrize(
        "style, text, expected, expected_stats, expected_warnings", PROCESS_CASES
    )
    def test_process_file(
        self, style, text, expected, expected_stats, expected_warnings
    ):
        result, stats, warnings = convert(text, style)
        assert result == expected
        assert {key: stats[key] for key in expected_stats} == expected_stats
        assert warnings == expected_warnings

    def test_process_block_defaults_to_german(self):
        assert process_block('"Hola"', 1, make_stats(), []) == (
            f"{DE_OPEN_DOUBLE}Hola{DE_CLOSE_DOUBLE}"
        )


# Each row: text, the positions of the guillemets that pair up
PAIRED_GUILLEMET_CASES = [
    pytest.param(f"{GC} a {GO}b{GC} {GO}c", {4, 6}, id="pairs-and-lone-guillemets"),
    pytest.param(f"{GO}a {GO}b{GC} c{GC}", {0, 3, 5, 8}, id="nested-pairs"),
    pytest.param(f"`{GO}` b{GC}", set(), id="protected-guillemets-do-not-pair"),
    pytest.param("", set(), id="empty-block"),
]


class TestFindPairedGuillemets:
    @pytest.mark.parametrize("text, expected", PAIRED_GUILLEMET_CASES)
    def test_find_paired_guillemets(self, text, expected):
        assert find_paired_guillemets(text, mask_protected_regions(text)) == expected


# ---------------------------------------------------------------------------
# Reporting and CLI
# ---------------------------------------------------------------------------
# Each row: style, the summary lines it prints, the ones it leaves out. Every
# row reports 1 straight pair, 2 straight single marks and 3 guillemet
# corrections.
GUILLEMET_ROW_CASES = [
    # ‘…’ is already the target of French, so that stage has no row
    pytest.param(
        FRENCH,
        [
            '  Straight " -> French:       1 pair(s)',
            "  Straight ' -> French:       2 mark(s)",
            "  Guillemet spacing:          3 correction(s)",
            "  English typographic double: 0 correction(s)",
            "  Total replacements:         6",
        ],
        ["English typographic single"],
        id="french-shows-the-guillemet-row",
    ),
    pytest.param(
        SPANISH,
        [
            '  Straight " -> Spanish:      1 pair(s)',
            "  Straight ' -> Spanish:      2 mark(s)",
            "  Guillemet spacing:          3 correction(s)",
            "  Total replacements:         6",
        ],
        ["English typographic single"],
        id="spanish-shows-the-guillemet-row",
    ),
    pytest.param(GERMAN, [], ["Guillemet"], id="german-has-no-guillemet-row"),
    pytest.param(ENGLISH, [], ["Guillemet"], id="english-has-no-guillemet-row"),
]


class TestReporting:
    @pytest.mark.parametrize("style, present, absent", GUILLEMET_ROW_CASES)
    def test_guillemet_rows(self, style, present, absent, capsys):
        stats = make_stats()
        stats["straight_double"] = 1
        stats["straight_single"] = 2
        stats["guillemet_space"] = 3
        print_stats(stats, style)
        out = capsys.readouterr().out
        for line in present:
            assert line in out
        for text in absent:
            assert text not in out


# Each row: entry point, file text, the file text afterwards, a summary line.
# Every row also gets a backup, as the file is outside a Git repository.
MAIN_FILE_CASES = [
    pytest.param(
        main_french,
        '"C\'est" et « déjà »',
        f"{fr(f'C{CS}est')} et {fr('déjà')}",
        "Guillemet spacing:          4 correction(s)",
        id="french-file-mode",
    ),
    pytest.param(
        main_spanish,
        '"Hola" y « ya »',
        f"{es('Hola')} y {es('ya')}",
        'Straight " -> Spanish:      1 pair(s)',
        id="spanish-file-mode",
    ),
    pytest.param(
        main_french,
        "« déjà »",
        fr("déjà"),
        "Guillemet spacing:          2 correction(s)",
        id="file-with-only-spacing-fixes-is-written",
    ),
]

# Each row: entry point, its program name, the language its help names
HELP_CASES = [
    pytest.param(main_french, "fix-french-quotes", "French", id="french"),
    pytest.param(main_spanish, "fix-spanish-quotes", "Spanish", id="spanish"),
]


class TestMain:
    @pytest.mark.parametrize(
        "entry_point, text, expected, summary_line", MAIN_FILE_CASES
    )
    def test_file_mode(
        self, entry_point, text, expected, summary_line, tmp_path, monkeypatch, capsys
    ):
        f = tmp_path / "a.md"
        f.write_text(text, encoding="utf-8")
        monkeypatch.setattr(sys, "argv", ["fix-quotes", str(f)])
        entry_point()
        assert f.read_text(encoding="utf-8") == expected
        assert (tmp_path / "a.md.bak").exists()
        captured = capsys.readouterr()
        assert summary_line in captured.out
        assert captured.err == ""

    @pytest.mark.parametrize("entry, prog, name", HELP_CASES)
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


# Each row: style, text, expected result, the stats that must change. Every
# row also asserts no warning. Add a row to pin a new case.
ENGLISH_PAIR_CASES = [
    pytest.param(
        SPANISH,
        f"aquello que percibimos como {en('realidad')} es real en absoluto.",
        f"aquello que percibimos como {es('realidad')} es real en absoluto.",
        {"english_double": 1},
        id="spanish-top-level-pair",
    ),
    pytest.param(
        FRENCH,
        f"ce que nous appelons {en('réalité')}.",
        f"ce que nous appelons {fr('réalité')}.",
        {"english_double": 1, "guillemet_space": 2},
        id="french-top-level-pair-gets-spaces",
    ),
    pytest.param(
        SPANISH,
        f"¿existe acaso algún {en('sentido verdadero')} o {en('fin')}?",
        f"¿existe acaso algún {es('sentido verdadero')} o {es('fin')}?",
        {"english_double": 1},
        id="several-pairs-in-one-block",
    ),
    pytest.param(
        SPANISH,
        f"{GO}Dijo {en('no')} y se fue{GC}",
        f"{GO}Dijo {en('no')} y se fue{GC}",
        {"english_double": 0},
        id="spanish-pair-inside-guillemets-stays",
    ),
    pytest.param(
        FRENCH,
        f"{GO}Dijo {en('no')} y se fue{GC}",
        fr(f"Dijo {en('no')} y se fue"),
        {"english_double": 0, "guillemet_space": 2},
        id="french-pair-inside-guillemets-stays",
    ),
    # The straight pair becomes guillemets first; the pair inside is nested
    pytest.param(
        SPANISH,
        f'"Dijo {en("no")}."',
        es(f"Dijo {en('no')}."),
        {"english_double": 0, "straight_double": 1},
        id="pair-inside-a-straight-pair-stays",
    ),
    pytest.param(
        SPANISH,
        f"{en('sí')} y {GO}dijo {en('no')}{GC}",
        f"{es('sí')} y {GO}dijo {en('no')}{GC}",
        {"english_double": 1},
        id="top-level-and-nested-pairs-in-one-block",
    ),
    pytest.param(
        SPANISH,
        f"{es('uno')} y {en('dos')}",
        f"{es('uno')} y {es('dos')}",
        {"english_double": 1},
        id="pair-after-a-closed-guillemet-pair-converts",
    ),
    pytest.param(
        SPANISH,
        en(f"a {es('b')} c"),
        es(f"a {es('b')} c"),
        {"english_double": 1},
        id="pair-wrapping-guillemets-converts",
    ),
    pytest.param(
        SPANISH,
        f"hola{EN_CLOSE_DOUBLE} y adiós",
        f"hola{GC} y adiós",
        {"english_double": 1},
        id="lone-closing-quote-becomes-a-closing-guillemet",
    ),
    pytest.param(
        SPANISH,
        f"{GO}hola{EN_CLOSE_DOUBLE} y adiós{GC}",
        f"{GO}hola{EN_CLOSE_DOUBLE} y adiós{GC}",
        {"english_double": 0},
        id="lone-closing-quote-inside-guillemets-stays",
    ),
    pytest.param(
        SPANISH,
        f"{EN_OPEN_DOUBLE}hola y adiós",
        f"{EN_OPEN_DOUBLE}hola y adiós",
        {"english_double": 0},
        id="lone-opening-quote-stays",
    ),
    pytest.param(
        SPANISH,
        f"usa `{en('x')}` aquí",
        f"usa `{en('x')}` aquí",
        {"english_double": 0},
        id="pair-in-inline-code-stays",
    ),
    pytest.param(
        SPANISH,
        f'<span title="{en("x")}">y</span>',
        f'<span title="{en("x")}">y</span>',
        {"english_double": 0},
        id="pair-in-an-html-attribute-stays",
    ),
    pytest.param(
        SPANISH,
        f'"uno" y {en("dos")}',
        f"{es('uno')} y {es('dos')}",
        {"english_double": 1, "straight_double": 1},
        id="straight-and-english-pairs-in-one-block",
    ),
    pytest.param(
        SPANISH,
        f"{GO}abierto y {en('dos')}",
        f"{GO}abierto y {en('dos')}",
        {"english_double": 0},
        id="unclosed-guillemet-hides-the-rest-of-the-block",
    ),
    pytest.param(
        SPANISH,
        f"{OS}significado{CS}",
        f"{OS}significado{CS}",
        {"english_single": 0},
        id="english-single-quotes-are-already-the-target",
    ),
    # “ is both the German closer and the English opener, so an open German
    # pair cannot be tracked: every English pair converts
    pytest.param(
        GERMAN,
        f"{DE_OPEN_DOUBLE}Er sagte {en('nein')}{DE_CLOSE_DOUBLE}",
        f"{DE_OPEN_DOUBLE}Er sagte {DE_OPEN_DOUBLE}nein{DE_CLOSE_DOUBLE}"
        f"{DE_CLOSE_DOUBLE}",
        {"english_double": 1},
        id="german-cannot-nest-and-converts-every-pair",
    ),
    pytest.param(
        ENGLISH,
        f"{en('fine')} and {es('inner')}",
        f"{en('fine')} and {es('inner')}",
        {"english_double": 0},
        id="english-leaves-its-own-quotes-alone",
    ),
]

# Each row: the style the stage gets (None: its German default), text,
# expected result, english_double count. Spacing is a later stage.
STAGE_CASES = [
    pytest.param(
        SPANISH,
        f"{en('a')} {GO}{en('b')}{GC}",
        f"{es('a')} {GO}{en('b')}{GC}",
        1,
        id="spanish-top-level-converts-nested-stays",
    ),
    pytest.param(FRENCH, en("a"), f"{GO}a{GC}", 1, id="french-without-spaces"),
    pytest.param(
        None, en("a"), f"{DE_OPEN_DOUBLE}a{DE_CLOSE_DOUBLE}", 1, id="defaults-to-german"
    ),
    pytest.param(
        SPANISH, f"{GO}{en('b')}{GC}", f"{GO}{en('b')}{GC}", 0, id="only-nested"
    ),
]

# Each row: style, the summary lines it prints, the ones it leaves out
SUMMARY_ROW_CASES = [
    pytest.param(
        SPANISH,
        ["  English typographic double: 2 correction(s)"],
        ["English typographic single"],
        id="spanish-double-row-only",
    ),
    pytest.param(
        FRENCH,
        ["  English typographic double: 2 correction(s)"],
        ["English typographic single"],
        id="french-double-row-only",
    ),
    pytest.param(
        GERMAN,
        [
            "  English typographic double: 2 correction(s)",
            "  English typographic single: 0 correction(s)",
        ],
        [],
        id="german-both-rows",
    ),
    pytest.param(ENGLISH, [], ["English typographic"], id="english-neither-row"),
]

# Each row: entry point, file text, expected text, a summary line
FILE_MODE_CASES = [
    pytest.param(
        main_spanish,
        f"… aquello que percibimos como {en('realidad')} es real en absoluto.\n",
        f"… aquello que percibimos como {es('realidad')} es real en absoluto.\n",
        "English typographic double: 1 correction(s)",
        id="spanish",
    ),
    pytest.param(
        main_french,
        f"ce que nous appelons {en('réalité')}.\n",
        f"ce que nous appelons {fr('réalité')}.\n",
        "English typographic double: 1 correction(s)",
        id="french",
    ),
]


class TestEnglishDoubleQuotesInGuillemetStyles:
    # Each row: style, whether an English pair inside its own double quotes
    # is a nested quotation that stays, whether the English single-quote
    # stage can change anything for it
    @pytest.mark.parametrize(
        "style, nests, converts_single",
        [
            pytest.param(GERMAN, False, True, id="german"),
            pytest.param(ENGLISH, False, False, id="english"),
            pytest.param(FRENCH, True, False, id="french"),
            pytest.param(SPANISH, True, False, id="spanish"),
        ],
    )
    def test_style_traits(self, style, nests, converts_single):
        assert _nests_english_double(style) is nests
        assert _converts_english_single(style) is converts_single

    @pytest.mark.parametrize(
        "style, text, expected, expected_stats", ENGLISH_PAIR_CASES
    )
    def test_english_pairs(self, style, text, expected, expected_stats):
        result, stats, warnings = convert(text, style)
        assert result == expected
        assert {key: stats[key] for key in expected_stats} == expected_stats
        assert warnings == []

    @pytest.mark.parametrize("style, text, expected, count", STAGE_CASES)
    def test_stage_alone(self, style, text, expected, count):
        stats = make_stats()
        styles = () if style is None else (style,)
        result = replace_english_double_quotes(
            text, mask_protected_regions(text), stats, *styles
        )
        assert result == expected
        assert stats["english_double"] == count

    @pytest.mark.parametrize("style, present, absent", SUMMARY_ROW_CASES)
    def test_summary_rows(self, style, present, absent, capsys):
        stats = make_stats()
        stats["english_double"] = 2
        print_stats(stats, style)
        out = capsys.readouterr().out
        for line in present:
            assert line in out
        for text in absent:
            assert text not in out

    @pytest.mark.parametrize(
        "entry_point, text, expected, summary_line", FILE_MODE_CASES
    )
    def test_file_mode_converts_english_pairs(
        self, entry_point, text, expected, summary_line, tmp_path, monkeypatch, capsys
    ):
        f = tmp_path / "foreword.md"
        f.write_text(text, encoding="utf-8")
        monkeypatch.setattr(sys, "argv", ["fix-quotes", str(f)])
        entry_point()
        assert f.read_text(encoding="utf-8") == expected
        captured = capsys.readouterr()
        assert summary_line in captured.out
        assert captured.err == ""
