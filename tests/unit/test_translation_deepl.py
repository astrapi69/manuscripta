"""Unit tests for manuscripta.translation.deepl - the DeepL Free translator.

Every HTTP call is stubbed in the module namespace (``mod.requests.post``),
the per-block delay ``mod.sleep`` is recorded instead of slept, and the
cwd-relative constants (``project_root``, ``SKIPLIST_PATH``,
``SKIPPED_LOG_PATH``) are anchored on ``tmp_path`` by the ``sandbox``
fixture. The module reads ``DEEPL_AUTH_KEY`` from the environment on every
translation; the fixture sets it there. No test touches the network.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import requests

pytestmark = pytest.mark.unit

import manuscripta.translation.deepl as mod

KEY = "test-key"
PATH = "manuscript/ch.md"
PROG = "translate-book-deepl"


# --- HTTP doubles ----------------------------------------------------------


class Response:
    """What a stubbed ``requests.post`` returns. ``json_data`` may be an
    exception, which ``.json()`` then raises as it would on a malformed body."""

    def __init__(self, status_code=200, json_data=None, text=""):
        self.status_code = status_code
        self._json_data = json_data
        self.text = text

    def json(self):
        if isinstance(self._json_data, Exception):
            raise self._json_data
        return self._json_data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} for url")


def translation(*texts: str) -> Response:
    """A DeepL body carrying one translation per text."""
    return Response(
        json_data={
            "translations": [
                {"detected_source_language": "EN", "text": t} for t in texts
            ]
        }
    )


def echo(call: dict) -> Response:
    """A responder that 'translates' the posted text into ``<<text>>``."""
    return translation(f"<<{call['data']['text']}>>")


def sequence(*steps):
    """A responder answering each call with the next step - a Response, or a
    responder to delegate to; the last step repeats."""
    pending = list(steps)

    def respond(call: dict) -> Response:
        step = pending.pop(0) if len(pending) > 1 else pending[0]
        return step(call) if callable(step) else step

    return respond


class Recorder:
    """Stands in for ``requests.post``: records every call (url plus keyword
    arguments) and answers through ``respond``."""

    def __init__(self, respond):
        self.respond = respond
        self.calls: list[dict] = []

    def __call__(self, url, **kwargs):
        call = {"url": url, **kwargs}
        self.calls.append(call)
        return self.respond(call)

    @property
    def sent(self) -> list[str]:
        """The texts posted, in order."""
        return [c["data"]["text"] for c in self.calls]


def _refuse(*args, **kwargs):
    raise RuntimeError("no HTTP stub installed for this test")


def _read(path: Path):
    return path.read_text(encoding="utf-8") if path.exists() else None


def _write(root: Path, layout: dict[str, str]) -> None:
    for rel, content in layout.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(content, encoding="utf-8")


@pytest.fixture
def sleeps(monkeypatch):
    """Record the delays deepl would sleep instead of sleeping them."""
    slept: list = []
    monkeypatch.setattr(mod, "sleep", slept.append)
    return slept


@pytest.fixture
def sandbox(tmp_path, monkeypatch, sleeps):
    """Anchor the module on tmp_path (cwd, project root, skiplist, skip log),
    give it a key, and refuse HTTP until a test installs a recorder."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(mod, "project_root", str(tmp_path))
    monkeypatch.setattr(mod, "SKIPLIST_PATH", str(tmp_path / ".skiplist"))
    monkeypatch.setattr(mod, "SKIPPED_LOG_PATH", str(tmp_path / "logs" / "skipped.log"))
    monkeypatch.setenv("DEEPL_AUTH_KEY", KEY)
    monkeypatch.setattr(mod.requests, "post", _refuse)
    return tmp_path


@pytest.fixture
def post(sandbox, monkeypatch):
    """An echo-translating ``requests.post``; returns its recorder."""
    recorder = Recorder(echo)
    monkeypatch.setattr(mod.requests, "post", recorder)
    return recorder


# --- the key ---------------------------------------------------------------

# Each row: DEEPL_AUTH_KEY in the environment before each of a series of
# translations (None: unset, which raises instead of posting) and the
# auth_key the requests carry in order
KEY_CASES = [
    pytest.param(["from-env"], ["from-env"], id="read-from-environment"),
    pytest.param(["first", "second"], ["first", "second"], id="re-read-per-call"),
    pytest.param(["first", None], ["first"], id="absent-is-an-error-not-a-stale-key"),
]


@pytest.mark.parametrize("env_keys, sent", KEY_CASES)
def test_key_is_read_from_the_environment_when_translating(
    env_keys, sent, sandbox, post, monkeypatch
):
    for env_key in env_keys:
        if env_key is None:
            monkeypatch.delenv("DEEPL_AUTH_KEY", raising=False)
            with pytest.raises(EnvironmentError):
                mod.translate_text("Hello", "EN", "DE")
        else:
            monkeypatch.setenv("DEEPL_AUTH_KEY", env_key)
            mod.translate_text("Hello", "EN", "DE")
    assert [c["data"]["auth_key"] for c in post.calls] == sent


# --- normalize_path / load_skiplist / log_skipped -------------------------

# Each row: a path (a str, or a callable of the project root making one) and
# its normalized form relative to the project root
NORMALIZE_CASES = [
    pytest.param("manuscript/ch.md", "manuscript/ch.md", id="relative-unchanged"),
    pytest.param("./manuscript//ch.md", "manuscript/ch.md", id="dot-and-double-slash"),
    pytest.param("manuscript/../ch.md", "ch.md", id="parent-segment-collapsed"),
    pytest.param(
        lambda root: str(root / "manuscript" / "ch.md"),
        "manuscript/ch.md",
        id="absolute-under-root",
    ),
    pytest.param(
        lambda root: str(root.parent / "ch.md"), "../ch.md", id="absolute-outside-root"
    ),
]


@pytest.mark.parametrize("path, expected", NORMALIZE_CASES)
def test_normalize_path(path, expected, sandbox):
    assert mod.normalize_path(path(sandbox) if callable(path) else path) == expected


# Each row: the skiplist file content (None: no file) and the entries loaded;
# ``{root}`` stands for the project root
SKIPLIST_CASES = [
    pytest.param(None, set(), id="no-file"),
    pytest.param("", set(), id="empty-file"),
    pytest.param(
        "manuscript/a.md\n\n   \nmanuscript/b.md  \n",
        {"manuscript/a.md", "manuscript/b.md"},
        id="blank-lines-and-padding-dropped",
    ),
    pytest.param(
        "./manuscript/a.md\n{root}/manuscript/b.md\n",
        {"manuscript/a.md", "manuscript/b.md"},
        id="entries-normalized",
    ),
    pytest.param(
        "manuscript/a.md\nmanuscript/a.md\n",
        {"manuscript/a.md"},
        id="duplicates-collapsed",
    ),
]


@pytest.mark.parametrize("content, expected", SKIPLIST_CASES)
def test_load_skiplist(content, expected, sandbox):
    if content is not None:
        (sandbox / ".skiplist").write_text(
            content.format(root=sandbox), encoding="utf-8"
        )
    assert mod.load_skiplist(str(sandbox / ".skiplist")) == expected


def test_log_skipped_appends_one_line_per_event(sandbox):
    mod.log_skipped("skiplist", "manuscript/a.md")
    mod.log_skipped("empty", "manuscript/b.md")
    assert (
        _read(sandbox / "logs" / "skipped.log")
        == "skiplist: manuscript/a.md\nempty: manuscript/b.md\n"
    )


# --- translate_text --------------------------------------------------------

# Each row: the source and target codes as given and the ``source_lang`` /
# ``target_lang`` the request carries
TRANSLATE_REQUEST_CASES = [
    pytest.param("EN", "DE", "EN", "DE", id="upper-kept"),
    pytest.param("en", "de", "EN", "DE", id="lower-uppercased"),
    pytest.param("Fr", "es", "FR", "ES", id="mixed-uppercased"),
]


@pytest.mark.parametrize("source, target, src, tgt", TRANSLATE_REQUEST_CASES)
def test_translate_text_request(source, target, src, tgt, sandbox, monkeypatch):
    post = Recorder(sequence(translation("Hallo Welt", "ignored second")))
    monkeypatch.setattr(mod.requests, "post", post)
    assert mod.translate_text("Hello world", source, target) == "Hallo Welt"
    assert post.calls == [
        {
            "url": "https://api-free.deepl.com/v2/translate",
            "data": {
                "auth_key": KEY,
                "text": "Hello world",
                "source_lang": src,
                "target_lang": tgt,
            },
        }
    ]


# Each row: the auth key, the DeepL response, the exception raised, a fragment
# of its message and whether a request was sent at all
TRANSLATE_ERROR_CASES = [
    pytest.param(
        None,
        translation("x"),
        EnvironmentError,
        "Please set the DEEPL_AUTH_KEY environment variable.",
        False,
        id="missing-key",
    ),
    pytest.param(
        "", translation("x"), EnvironmentError, "DEEPL_AUTH_KEY", False, id="blank-key"
    ),
    pytest.param(
        KEY,
        Response(403, text="Forbidden"),
        requests.HTTPError,
        "403",
        True,
        id="http-error",
    ),
    pytest.param(
        KEY,
        Response(456, text="Quota exceeded"),
        requests.HTTPError,
        "456",
        True,
        id="quota-exceeded-is-an-http-error",
    ),
    pytest.param(
        KEY,
        Response(json_data={"translations": []}),
        IndexError,
        "",
        True,
        id="no-translations",
    ),
    pytest.param(
        KEY,
        Response(json_data={"message": "Wrong endpoint"}),
        KeyError,
        "translations",
        True,
        id="no-translations-key",
    ),
    pytest.param(
        KEY,
        Response(json_data=ValueError("Expecting value")),
        ValueError,
        "Expecting value",
        True,
        id="malformed-json",
    ),
]


@pytest.mark.parametrize(
    "key, response, exception, fragment, posted", TRANSLATE_ERROR_CASES
)
def test_translate_text_errors(
    key, response, exception, fragment, posted, sandbox, monkeypatch
):
    if key is None:
        monkeypatch.delenv("DEEPL_AUTH_KEY")
    else:
        monkeypatch.setenv("DEEPL_AUTH_KEY", key)
    post = Recorder(sequence(response))
    monkeypatch.setattr(mod.requests, "post", post)
    with pytest.raises(exception) as exc:
        mod.translate_text("Hello", "EN", "DE")
    assert fragment in str(exc.value)
    assert len(post.calls) == (1 if posted else 0)


# --- translate_markdown_file -----------------------------------------------

MD = "# Title\n\nFirst paragraph.\n\n\n\nLast paragraph.\n"
# Blocks are stripped before they are sent; the file's final newline and the
# empty block between the double blank line survive the translation.
TRANSLATED_MD = "<<# Title>>\n\n<<First paragraph.>>\n\n\n\n<<Last paragraph.>>\n"

# Each row: the file content (None: no file), the skiplist, dry_run, the
# requests.post script, the file content afterwards (None: still no file), the
# texts posted in order, the number of per-block delays slept,
# translated_files afterwards, the skipped.log content (None: no log) and the
# lines stdout must carry
FILE_CASES = [
    pytest.param(
        MD,
        set(),
        False,
        (echo,),
        TRANSLATED_MD,
        ["# Title", "First paragraph.", "Last paragraph."],
        3,
        {PATH},
        None,
        [
            f"🌍 Translating: {PATH} [en → de]",
            f"✅ Overwritten: {PATH}",
            f"📌 Added to translated_files: {PATH}",
        ],
        id="translates-each-block-in-place",
    ),
    pytest.param(
        MD,
        set(),
        True,
        (echo,),
        MD,
        [],
        0,
        {PATH},
        None,
        [f"🧪 Dry-run complete: {PATH} not written."],
        id="dry-run-posts-writes-and-sleeps-nothing",
    ),
    pytest.param(
        MD,
        {PATH},
        False,
        (echo,),
        MD,
        [],
        0,
        set(),
        f"skiplist: {PATH}\n",
        [f"⏭️ Skipped via .skiplist: {PATH}"],
        id="listed-in-skiplist",
    ),
    pytest.param(
        None,
        set(),
        False,
        (echo,),
        None,
        [],
        0,
        set(),
        f"not_found: {PATH}\n",
        [f"🌍 Translating: {PATH} [en → de]", f"❌ File not found: {PATH}"],
        id="missing-file-announced-then-logged",
    ),
    pytest.param(
        "  \n\n",
        set(),
        False,
        (echo,),
        "  \n\n",
        [],
        0,
        {PATH},
        f"empty: {PATH}\n",
        [f"⏭️ Skipped empty file: {PATH}"],
        id="empty-file-remembered",
    ),
    pytest.param(
        "One.\n\nTwo.",
        set(),
        False,
        (Response(429, text="Too Many Requests"), echo),
        "One.\n\n<<Two.>>",
        ["One.", "Two."],
        1,
        {PATH},
        None,
        ["⚠️ Failed to translate block:\nOne....\nError: 429 for url"],
        id="failed-block-keeps-original",
    ),
    pytest.param(
        "One.\n\nTwo.",
        set(),
        False,
        (Response(json_data={"message": "Wrong endpoint"}), echo),
        "One.\n\n<<Two.>>",
        ["One.", "Two."],
        1,
        {PATH},
        None,
        ["⚠️ Failed to translate block:\nOne....\nError: 'translations'"],
        id="malformed-body-keeps-original",
    ),
]


@pytest.mark.parametrize(
    "content, skiplist, dry_run, steps, after, sent, delays, translated, log, "
    "out_lines",
    FILE_CASES,
)
def test_translate_markdown_file(
    content,
    skiplist,
    dry_run,
    steps,
    after,
    sent,
    delays,
    translated,
    log,
    out_lines,
    sandbox,
    sleeps,
    monkeypatch,
    capsys,
):
    file = sandbox / PATH
    if content is not None:
        _write(sandbox, {PATH: content})
    post = Recorder(sequence(*steps))
    monkeypatch.setattr(mod.requests, "post", post)
    translated_files: set = set()
    mod.translate_markdown_file(
        str(file), "en", "de", skiplist, translated_files, dry_run
    )
    assert _read(file) == after
    assert post.sent == sent
    assert sleeps == [mod.TRANSLATION_DELAY] * delays
    assert translated_files == translated
    assert _read(sandbox / "logs" / "skipped.log") == log
    out = capsys.readouterr().out
    for line in out_lines:
        assert line in out


# --- translate_markdown_files ----------------------------------------------

# Each row: the files under the base directory (None: the directory does not
# exist) and the normalized paths translated
WALK_CASES = [
    pytest.param(
        {"a.md": "A.", "sub/deep/b.md": "B.", "notes.txt": "N.", "c.markdown": "C."},
        {"book/a.md", "book/sub/deep/b.md"},
        id="recursive-md-only",
    ),
    pytest.param({}, set(), id="empty-directory"),
    pytest.param(None, set(), id="missing-directory"),
]


@pytest.mark.parametrize("layout, translated", WALK_CASES)
def test_translate_markdown_files(layout, translated, sandbox, post):
    base = sandbox / "book"
    if layout is not None:
        base.mkdir()
        _write(base, layout)
    translated_files: set = set()
    mod.translate_markdown_files(str(base), "en", "de", set(), translated_files, False)
    assert translated_files == translated
    expected = {
        rel: f"<<{text}>>" if rel.endswith(".md") else text
        for rel, text in (layout or {}).items()
    }
    assert {rel: _read(base / rel) for rel in expected} == expected
    assert set(post.sent) == {
        text for rel, text in (layout or {}).items() if rel.endswith(".md")
    }


# --- main ------------------------------------------------------------------

# Each row: the command line after the program name and the usage error
# printed to stderr; the exit status is 2 and nothing is written
MAIN_USAGE_CASES = [
    pytest.param(
        [],
        "the following arguments are required: --target-lang",
        id="target-lang-required",
    ),
    pytest.param(
        ["--target-lang", "DE"],
        "You must specify either --file or --base-dir.",
        id="file-or-base-dir-required",
    ),
]


@pytest.mark.parametrize("argv, err", MAIN_USAGE_CASES)
def test_main_usage_errors(argv, err, sandbox, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", [PROG, *argv])
    with pytest.raises(SystemExit) as exc:
        mod.main()
    assert exc.value.code == 2
    assert err in capsys.readouterr().err
    assert _read(sandbox / ".skiplist") is None


CH = {"manuscript/ch.md": "Hello.\n\nWorld."}
CH_DE = {"manuscript/ch.md": "<<Hello.>>\n\n<<World.>>"}
TREE = {"book/a.md": "A.", "book/sub/b.md": "B.", "book/n.txt": "N."}
TREE_DE = {"book/a.md": "<<A.>>", "book/sub/b.md": "<<B.>>", "book/n.txt": "N."}

# Each row: the command line after the program name, the files before
# (relative to the project root), the existing skiplist (None: none), the
# files after, the skiplist after (None: none), the (source, target) every
# request carries (None: no request) and the lines stdout must carry
MAIN_CASES = [
    pytest.param(
        ["--target-lang", "DE", "--file", "manuscript/ch.md"],
        CH,
        None,
        CH_DE,
        "manuscript/ch.md\n",
        ("EN", "DE"),
        [
            "📊 Total files marked as translated: 1",
            "📄 Writing to .skiplist: manuscript/ch.md",
            "📝 Skiplist updated with 1 new entries (total 1).",
        ],
        id="single-file",
    ),
    pytest.param(
        ["--source-lang", "de", "--target-lang", "en", "--base-dir", "book"],
        TREE,
        None,
        TREE_DE,
        "book/a.md\nbook/sub/b.md\n",
        ("DE", "EN"),
        [
            "📊 Total files marked as translated: 2",
            "📝 Skiplist updated with 2 new entries (total 2).",
        ],
        id="base-dir-recursive",
    ),
    pytest.param(
        ["--target-lang", "FR", "--base-dir", "book", "--dry-run"],
        TREE,
        None,
        TREE,
        None,
        None,
        ["🧪 Dry-run complete: book/a.md not written."],
        id="dry-run",
    ),
    pytest.param(
        ["--target-lang", "DE", "--file", "manuscript/ch.md"],
        CH,
        "manuscript/ch.md\n",
        CH,
        "manuscript/ch.md\n",
        None,
        ["⏭️ Skipped via .skiplist: manuscript/ch.md"],
        id="skiplisted-file-untouched",
    ),
    pytest.param(
        ["--target-lang", "DE", "--file", "manuscript/ch.md"],
        CH,
        "manuscript/old.md\n",
        CH_DE,
        "manuscript/ch.md\nmanuscript/old.md\n",
        ("EN", "DE"),
        ["📝 Skiplist updated with 1 new entries (total 2)."],
        id="skiplist-merged",
    ),
    pytest.param(
        ["--target-lang", "DE", "--file", "manuscript/none.md"],
        CH,
        None,
        CH,
        None,
        None,
        ["❌ File not found: manuscript/none.md"],
        id="missing-file-no-skiplist",
    ),
    pytest.param(
        ["--target-lang", "DE", "--file", "manuscript/ch.md", "--base-dir", "book"],
        {**CH, **TREE},
        None,
        {**CH_DE, **TREE},
        "manuscript/ch.md\n",
        ("EN", "DE"),
        [],
        id="file-wins-over-base-dir",
    ),
]


@pytest.mark.parametrize(
    "argv, before, existing, after, skiplist, langs, out_lines", MAIN_CASES
)
def test_main(
    argv,
    before,
    existing,
    after,
    skiplist,
    langs,
    out_lines,
    sandbox,
    post,
    monkeypatch,
    capsys,
):
    _write(sandbox, before)
    if existing is not None:
        (sandbox / ".skiplist").write_text(existing, encoding="utf-8")
    monkeypatch.setattr(sys, "argv", [PROG, *argv])
    mod.main()
    assert {rel: _read(sandbox / rel) for rel in after} == after
    assert _read(sandbox / ".skiplist") == skiplist
    requests_made = {
        (c["data"]["source_lang"], c["data"]["target_lang"]) for c in post.calls
    }
    assert requests_made == ({langs} if langs else set())
    out = capsys.readouterr().out
    for line in out_lines:
        assert line in out


def test_main_persists_what_was_translated_before_ctrl_c(sandbox, monkeypatch, capsys):
    def interrupted(base_dir, source, target, skiplist, translated_files, dry_run):
        translated_files.add("manuscript/done.md")
        raise KeyboardInterrupt

    monkeypatch.setattr(mod, "translate_markdown_files", interrupted)
    monkeypatch.setattr(sys, "argv", [PROG, "--target-lang", "DE", "--base-dir", "m"])
    mod.main()
    assert _read(sandbox / ".skiplist") == "manuscript/done.md\n"
    out = capsys.readouterr().out
    assert "🛑 Translation interrupted by user (Ctrl+C)" in out
    assert "📊 Total files marked as translated: 1" in out


def test_main_does_not_rewrite_a_skiplist_another_run_completed(
    sandbox, post, monkeypatch, capsys
):
    """The skiplist is re-read at the end: a file another run listed meanwhile
    is no new entry, and the file is left as that run wrote it."""
    _write(sandbox, CH)
    loads = iter([set(), {"manuscript/ch.md"}])
    monkeypatch.setattr(mod, "load_skiplist", lambda path=None: next(loads))
    monkeypatch.setattr(sys, "argv", [PROG, "--target-lang", "DE", "--file", PATH])
    mod.main()
    assert _read(sandbox / ".skiplist") is None
    assert "ℹ️ No new entries to add to skiplist." in capsys.readouterr().out
