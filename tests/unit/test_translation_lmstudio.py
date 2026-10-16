"""Unit tests for manuscripta.translation.lmstudio - the LM Studio translator.

Every HTTP call is stubbed in the module namespace (``mod.requests.post``,
``mod.requests.get``), the throttle ``mod.sleep`` is recorded instead of
slept, and the cwd-relative constants (``PROJECT_ROOT``, ``SKIPLIST_PATH``,
``SKIPPED_LOG_PATH``) are anchored on ``tmp_path`` by the ``sandbox``
fixture. No test touches the network.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
import requests

pytestmark = pytest.mark.unit

import manuscripta.translation.lmstudio as mod

API_URL = "http://lmstudio.test/v1/chat/completions"
MODELS_URL = "http://lmstudio.test/v1/models"
MODEL = "llama-3.1-8b-instruct"
PATH = "manuscript/ch.md"
PROG = "translate-book-lmstudio"


# --- HTTP doubles ----------------------------------------------------------


class Response:
    """What a stubbed ``requests`` call returns. ``json_data`` may be an
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


def chat(content: str) -> Response:
    """A chat-completion body whose first choice says ``content``."""
    return Response(json_data={"choices": [{"message": {"content": content}}]})


def models(*ids: str) -> Response:
    """A ``/v1/models`` body listing ``ids`` in order."""
    return Response(json_data={"data": [{"id": i} for i in ids]})


def echo(call: dict) -> Response:
    """A responder that 'translates' the posted user text into ``<<text>>``."""
    return chat(f"<<{call['json']['messages'][1]['content']}>>")


def sequence(*steps):
    """A responder answering each call with the next step - a Response, or a
    responder to delegate to; the last step repeats."""
    pending = list(steps)

    def respond(call: dict) -> Response:
        step = pending.pop(0) if len(pending) > 1 else pending[0]
        return step(call) if callable(step) else step

    return respond


class Recorder:
    """Stands in for ``requests.post`` / ``requests.get``: records every call
    (url plus keyword arguments) and answers through ``respond``."""

    def __init__(self, respond):
        self.respond = respond
        self.calls: list[dict] = []

    def __call__(self, url, **kwargs):
        call = {"url": url, **kwargs}
        self.calls.append(call)
        return self.respond(call)

    @property
    def sent(self) -> list[str]:
        """The user texts posted, in order."""
        return [c["json"]["messages"][1]["content"] for c in self.calls]


def _refuse(*args, **kwargs):
    raise RuntimeError("no HTTP stub installed for this test")


def _read(path: Path):
    return path.read_text(encoding="utf-8") if path.exists() else None


def _write(root: Path, layout: dict[str, str]) -> None:
    for rel, content in layout.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(content, encoding="utf-8")


def _langs(call: dict) -> tuple[str, str]:
    """The (source, target) the system prompt of a chat request names."""
    found = re.search(
        r"Translate the text from (\S+) to (\S+)\.",
        call["json"]["messages"][0]["content"],
    )
    assert found is not None
    return found.group(1), found.group(2)


def system_prompt(source: str, target: str) -> str:
    """The instruction lmstudio sends as the system message."""
    return (
        "You are a professional translation engine.\n"
        f"Translate the text from {source} to {target}.\n"
        "Output ONLY the translated text.\n"
        "Do NOT explain your reasoning.\n"
        "Do NOT add comments.\n"
        "Do NOT include tags like <think> or </think>.\n"
        "Do NOT repeat the original text.\n"
        "Preserve Markdown formatting exactly "
        "(headings, lists, emphasis, links, code blocks).\n"
    )


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """Anchor the module on tmp_path (cwd, project root, skiplist, skip log)
    and refuse HTTP until a test installs a recorder."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(mod, "PROJECT_ROOT", str(tmp_path))
    monkeypatch.setattr(mod, "SKIPLIST_PATH", str(tmp_path / ".skiplist"))
    monkeypatch.setattr(mod, "SKIPPED_LOG_PATH", str(tmp_path / "logs" / "skipped.log"))
    monkeypatch.setattr(mod.requests, "post", _refuse)
    monkeypatch.setattr(mod.requests, "get", _refuse)
    return tmp_path


@pytest.fixture
def post(sandbox, monkeypatch):
    """An echo-translating ``requests.post``; returns its recorder."""
    recorder = Recorder(echo)
    monkeypatch.setattr(mod.requests, "post", recorder)
    return recorder


@pytest.fixture
def get(sandbox, monkeypatch):
    """A ``requests.get`` listing one model, ``auto-model``; returns its recorder."""
    recorder = Recorder(sequence(models("auto-model")))
    monkeypatch.setattr(mod.requests, "get", recorder)
    return recorder


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


# --- strip_reasoning -------------------------------------------------------

# Each row: what the model answered and the translation kept from it
REASONING_CASES = [
    pytest.param("", "", id="empty"),
    pytest.param("Hallo Welt", "Hallo Welt", id="plain-text-unchanged"),
    pytest.param("  Hallo Welt \n", "Hallo Welt", id="padding-stripped"),
    pytest.param("<think>hmm</think>\nHallo Welt", "Hallo Welt", id="think-block"),
    pytest.param("<THINK>hmm</THINK>Hallo Welt", "Hallo Welt", id="think-any-case"),
    pytest.param(
        "<think>line one\nline two</think>  Hallo Welt",
        "Hallo Welt",
        id="think-spans-lines",
    ),
    pytest.param("<think>only reasoning</think>", "", id="think-only"),
    # Only the reasoning block and a leading label are stripped: a preamble
    # section stays, and so does every paragraph of a multi-paragraph answer.
    pytest.param(
        "Here is the translation:\n\nHallo Welt",
        "Here is the translation:\n\nHallo Welt",
        id="preamble-section-kept",
    ),
    pytest.param(
        "Erster Absatz.\n\nZweiter Absatz.",
        "Erster Absatz.\n\nZweiter Absatz.",
        id="multi-paragraph-kept-whole",
    ),
    pytest.param(
        "<think>hmm</think>\nErster Absatz.\n\nZweiter Absatz.",
        "Erster Absatz.\n\nZweiter Absatz.",
        id="think-then-multi-paragraph-kept-whole",
    ),
    pytest.param("Translation: Hallo Welt", "Hallo Welt", id="label-translation"),
    pytest.param("ÜBERSETZUNG : Hallo Welt", "Hallo Welt", id="label-uebersetzung"),
    pytest.param("Final:Hallo Welt", "Hallo Welt", id="label-final"),
    pytest.param("answer: Hallo Welt", "Hallo Welt", id="label-answer"),
    pytest.param("Summary: Hallo Welt", "Summary: Hallo Welt", id="unknown-label-kept"),
    # A label is stripped only where the answer starts; a preamble before it
    # keeps the label in place.
    pytest.param(
        "<think>x</think>Note:\n\nTranslation: Hallo Welt",
        "Note:\n\nTranslation: Hallo Welt",
        id="think-then-sections-label-not-leading",
    ),
]


@pytest.mark.parametrize("answer, kept", REASONING_CASES)
def test_strip_reasoning(answer, kept):
    assert mod.strip_reasoning(answer) == kept


# --- get_default_model_id --------------------------------------------------

# Each row: the /v1/models response and the model id returned, or the
# exception raised
MODEL_ID_CASES = [
    pytest.param(models("first", "second"), "first", id="first-listed-model"),
    pytest.param(Response(json_data={"data": []}), RuntimeError, id="empty-list"),
    pytest.param(
        Response(json_data={"data": [{"name": "x"}]}),
        RuntimeError,
        id="entry-without-id",
    ),
    pytest.param(Response(json_data={}), RuntimeError, id="no-data-key"),
    pytest.param(Response(json_data={"data": None}), RuntimeError, id="data-null"),
    pytest.param(
        Response(status_code=503, text="down"), requests.HTTPError, id="http-error"
    ),
    pytest.param(
        Response(json_data=ValueError("Expecting value")),
        ValueError,
        id="malformed-json",
    ),
]


@pytest.mark.parametrize("response, expected", MODEL_ID_CASES)
def test_get_default_model_id(response, expected, sandbox, monkeypatch):
    get = Recorder(sequence(response))
    monkeypatch.setattr(mod.requests, "get", get)
    if isinstance(expected, str):
        assert mod.get_default_model_id(MODELS_URL) == expected
    else:
        with pytest.raises(expected) as exc:
            mod.get_default_model_id(MODELS_URL)
        if expected is RuntimeError:
            assert f"Could not determine model id from {MODELS_URL}" in str(exc.value)
    assert get.calls == [{"url": MODELS_URL, "timeout": 10}]


# --- translate_text --------------------------------------------------------

# Each row: the keyword arguments beyond text, languages and urls, the model
# ids /v1/models lists (None: it must not be fetched), and the model id,
# temperature and timeout the chat request must carry
TRANSLATE_REQUEST_CASES = [
    pytest.param(
        {"model": MODEL}, None, MODEL, 0.2, 120, id="explicit-model-skips-model-list"
    ),
    pytest.param(
        {}, ["first", "second"], "first", 0.2, 120, id="first-listed-model-by-default"
    ),
    pytest.param(
        {"model": MODEL, "temperature": 0.7, "timeout_s": 5},
        None,
        MODEL,
        0.7,
        5,
        id="temperature-and-timeout-forwarded",
    ),
]


@pytest.mark.parametrize(
    "kwargs, listed, model, temperature, timeout", TRANSLATE_REQUEST_CASES
)
def test_translate_text_request(
    kwargs, listed, model, temperature, timeout, sandbox, monkeypatch
):
    post = Recorder(sequence(chat("Hallo Welt")))
    get = Recorder(sequence(models(*(listed or []))))
    monkeypatch.setattr(mod.requests, "post", post)
    monkeypatch.setattr(mod.requests, "get", get)
    translated = mod.translate_text(
        "Hello world", "en", "de", API_URL, MODELS_URL, **kwargs
    )
    assert translated == "Hallo Welt"
    assert [c["url"] for c in get.calls] == ([MODELS_URL] if listed else [])
    assert post.calls == [
        {
            "url": API_URL,
            "json": {
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt("EN", "DE")},
                    {"role": "user", "content": "Hello world"},
                ],
                "temperature": temperature,
            },
            "timeout": timeout,
        }
    ]


# Each row: the chat response, the exception translate_text raises and a
# fragment of its message
TRANSLATE_ERROR_CASES = [
    pytest.param(
        Response(404, text="no route"),
        RuntimeError,
        f"404 Not Found. Check api_url={API_URL}. Body: no route",
        id="404-names-the-url",
    ),
    pytest.param(
        Response(400, text="bad payload"),
        RuntimeError,
        "400 Bad Request. Body: bad payload",
        id="400-quotes-the-body",
    ),
    pytest.param(
        Response(500, text="boom"), requests.HTTPError, "500", id="other-http-error"
    ),
    pytest.param(
        Response(json_data={"choices": []}),
        RuntimeError,
        "Unexpected response from LM Studio: {'choices': []}",
        id="no-choices",
    ),
    pytest.param(
        Response(json_data={"error": "overloaded"}),
        RuntimeError,
        "Unexpected response from LM Studio: {'error': 'overloaded'}",
        id="error-body",
    ),
    pytest.param(
        Response(json_data=ValueError("Expecting value")),
        ValueError,
        "Expecting value",
        id="malformed-json",
    ),
]


@pytest.mark.parametrize("response, exception, fragment", TRANSLATE_ERROR_CASES)
def test_translate_text_errors(response, exception, fragment, sandbox, monkeypatch):
    monkeypatch.setattr(mod.requests, "post", Recorder(sequence(response)))
    with pytest.raises(exception) as exc:
        mod.translate_text("Hello", "en", "de", API_URL, MODELS_URL, model=MODEL)
    assert fragment in str(exc.value)


def test_translate_text_strips_the_models_reasoning(sandbox, monkeypatch):
    answer = "<think>Short and plain.</think>\nTranslation: Hallo Welt"
    monkeypatch.setattr(mod.requests, "post", Recorder(sequence(chat(answer))))
    assert (
        mod.translate_text("Hello world", "en", "de", API_URL, MODELS_URL, model=MODEL)
        == "Hallo Welt"
    )


# --- translate_markdown_file -----------------------------------------------

MD = "# Title\n\nFirst paragraph.\n\n<tr><td>cell</td></tr>\n\n\n\nLast paragraph.\n"
# Blocks are stripped before they are sent; the file's final newline and the
# empty block between the double blank line survive the translation.
TRANSLATED_MD = (
    "<<# Title>>\n\n<<First paragraph.>>\n\n<tr><td>cell</td></tr>\n\n\n\n"
    "<<Last paragraph.>>\n"
)
TRANSLATED_MD_WITH_TR = (
    "<<# Title>>\n\n<<First paragraph.>>\n\n<<<tr><td>cell</td></tr>>>\n\n\n\n"
    "<<Last paragraph.>>\n"
)

# Each row: the file content (None: no file), the skiplist, the keyword
# arguments, the requests.post script, the file content afterwards (None:
# still no file), the user texts posted in order, translated_files afterwards,
# the skipped.log content (None: no log) and the lines stdout must carry
FILE_CASES = [
    pytest.param(
        MD,
        set(),
        {},
        (echo,),
        TRANSLATED_MD,
        ["# Title", "First paragraph.", "Last paragraph."],
        {PATH},
        None,
        [f"🌍 Translating: {PATH} [en → de]", f"✅ Overwritten: {PATH}"],
        id="translates-each-block-in-place",
    ),
    pytest.param(
        MD,
        set(),
        {"skip_html_tr_rows": False},
        (echo,),
        TRANSLATED_MD_WITH_TR,
        ["# Title", "First paragraph.", "<tr><td>cell</td></tr>", "Last paragraph."],
        {PATH},
        None,
        [],
        id="html-tr-rows-translated-on-request",
    ),
    pytest.param(
        MD,
        set(),
        {"dry_run": True},
        (echo,),
        MD,
        [],
        {PATH},
        None,
        [f"🧪 Dry-run complete: {PATH} not written."],
        id="dry-run-posts-and-writes-nothing",
    ),
    pytest.param(
        MD,
        {PATH},
        {},
        (echo,),
        MD,
        [],
        set(),
        f"skiplist: {PATH}\n",
        [f"⏭️  Skipped via .skiplist: {PATH}"],
        id="listed-in-skiplist",
    ),
    pytest.param(
        None,
        set(),
        {},
        (echo,),
        None,
        [],
        set(),
        f"not_found: {PATH}\n",
        [f"❌ File not found: {PATH}"],
        id="missing-file",
    ),
    pytest.param(
        "  \n\n",
        set(),
        {},
        (echo,),
        "  \n\n",
        [],
        {PATH},
        f"empty: {PATH}\n",
        [f"⏭️  Skipped empty file: {PATH}"],
        id="empty-file-remembered",
    ),
    pytest.param(
        "One.\n\nTwo.",
        set(),
        {},
        (Response(500, text="boom"), echo),
        "One.\n\n<<Two.>>",
        ["One.", "Two."],
        {PATH},
        None,
        [
            "⚠️  Failed to translate block (keeping original). "
            "Error: 500 for url\nBlock preview: 'One.'"
        ],
        id="failed-block-keeps-original",
    ),
    pytest.param(
        "One.\n\nTwo.",
        set(),
        {},
        (Response(json_data={"choices": []}), echo),
        "One.\n\n<<Two.>>",
        ["One.", "Two."],
        {PATH},
        None,
        ["Error: Unexpected response from LM Studio"],
        id="unexpected-body-keeps-original",
    ),
]


@pytest.mark.parametrize(
    "content, skiplist, kwargs, steps, after, sent, translated, log, out_lines",
    FILE_CASES,
)
def test_translate_markdown_file(
    content,
    skiplist,
    kwargs,
    steps,
    after,
    sent,
    translated,
    log,
    out_lines,
    sandbox,
    monkeypatch,
    capsys,
):
    file = sandbox / PATH
    if content is not None:
        _write(sandbox, {PATH: content})
    post = Recorder(sequence(*steps))
    monkeypatch.setattr(mod.requests, "post", post)
    translated_files: set[str] = set()
    mod.translate_markdown_file(
        str(file),
        "en",
        "de",
        API_URL,
        MODELS_URL,
        skiplist,
        translated_files,
        **{"dry_run": False, "model": MODEL, **kwargs},
    )
    assert _read(file) == after
    assert post.sent == sent
    assert translated_files == translated
    assert _read(sandbox / "logs" / "skipped.log") == log
    out = capsys.readouterr().out
    for line in out_lines:
        assert line in out


# Each row: TRANSLATION_DELAY, the requests.post script and the delays slept
# for a two-block file
THROTTLE_CASES = [
    pytest.param(0, (echo,), [], id="no-delay-by-default"),
    pytest.param(2, (echo,), [2, 2], id="sleeps-after-every-block"),
    pytest.param(2, (Response(500), echo), [2], id="no-sleep-after-a-failed-block"),
]


@pytest.mark.parametrize("delay, steps, sleeps", THROTTLE_CASES)
def test_translate_markdown_file_throttle(delay, steps, sleeps, sandbox, monkeypatch):
    _write(sandbox, {PATH: "One.\n\nTwo."})
    monkeypatch.setattr(mod.requests, "post", Recorder(sequence(*steps)))
    monkeypatch.setattr(mod, "TRANSLATION_DELAY", delay)
    slept: list = []
    monkeypatch.setattr(mod, "sleep", slept.append)
    mod.translate_markdown_file(
        str(sandbox / PATH),
        "en",
        "de",
        API_URL,
        MODELS_URL,
        set(),
        set(),
        dry_run=False,
        model=MODEL,
    )
    assert slept == sleeps


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
    translated_files: set[str] = set()
    mod.translate_markdown_files(
        str(base),
        "en",
        "de",
        API_URL,
        MODELS_URL,
        set(),
        translated_files,
        dry_run=False,
        model=MODEL,
    )
    assert translated_files == translated
    expected = {
        rel: f"<<{text}>>" if rel.endswith(".md") else text
        for rel, text in (layout or {}).items()
    }
    assert {rel: _read(base / rel) for rel in expected} == expected
    assert set(post.sent) == {
        text for rel, text in (layout or {}).items() if rel.endswith(".md")
    }


# --- persist_skiplist ------------------------------------------------------

# Each row: the existing skiplist (None: none), translated_files, dry_run, the
# skiplist afterwards (None: none) and the line printed (None: nothing)
PERSIST_CASES = [
    pytest.param(
        None,
        {"manuscript/b.md", "manuscript/a.md"},
        False,
        "manuscript/a.md\nmanuscript/b.md\n",
        "📝 Skiplist updated with 2 new entries (total 2).",
        id="created-sorted",
    ),
    pytest.param(
        "manuscript/a.md\n",
        {"manuscript/b.md"},
        False,
        "manuscript/a.md\nmanuscript/b.md\n",
        "📝 Skiplist updated with 1 new entries (total 2).",
        id="merged-with-existing",
    ),
    pytest.param(
        "manuscript/a.md\n",
        {"./manuscript/a.md"},
        False,
        "manuscript/a.md\n",
        "ℹ️  No new entries to add to skiplist.",
        id="already-listed-after-normalizing",
    ),
    pytest.param(
        "manuscript/a.md\n",
        set(),
        False,
        "manuscript/a.md\n",
        "ℹ️  No files to add to skiplist.",
        id="nothing-translated",
    ),
    pytest.param(
        "manuscript/a.md\n",
        {"manuscript/b.md"},
        True,
        "manuscript/a.md\n",
        None,
        id="dry-run-leaves-existing",
    ),
    pytest.param(
        None, {"manuscript/b.md"}, True, None, None, id="dry-run-creates-none"
    ),
]


@pytest.mark.parametrize("existing, translated, dry_run, after, line", PERSIST_CASES)
def test_persist_skiplist(existing, translated, dry_run, after, line, sandbox, capsys):
    if existing is not None:
        (sandbox / ".skiplist").write_text(existing, encoding="utf-8")
    mod.persist_skiplist(translated, dry_run)
    assert _read(sandbox / ".skiplist") == after
    assert capsys.readouterr().out == ("" if line is None else line + "\n")


def test_persist_skiplist_creates_the_parent_directory(sandbox, monkeypatch):
    monkeypatch.setattr(mod, "SKIPLIST_PATH", str(sandbox / "state" / ".skiplist"))
    mod.persist_skiplist({"manuscript/a.md"}, dry_run=False)
    assert _read(sandbox / "state" / ".skiplist") == "manuscript/a.md\n"


# --- build_arg_parser ------------------------------------------------------

ENV = ("LM_STUDIO_API_URL", "LM_STUDIO_MODELS_URL", "LM_STUDIO_MODEL")

# Each row: the command line, the LM_STUDIO_* environment and the options the
# parser must yield
PARSER_CASES = [
    pytest.param(
        ["--target-lang", "de"],
        {},
        {
            "source_lang": "en",
            "target_lang": "de",
            "base_dir": "manuscript",
            "file": None,
            "api_url": mod.DEFAULT_API_URL,
            "models_url": mod.DEFAULT_MODELS_URL,
            "model": None,
            "no_skip_html_tr": False,
            "dry_run": False,
        },
        id="defaults",
    ),
    pytest.param(
        [
            "--source-lang",
            "de",
            "--target-lang",
            "en",
            "--base-dir",
            "book",
            "--file",
            "book/a.md",
            "--api-url",
            API_URL,
            "--models-url",
            MODELS_URL,
            "--model",
            MODEL,
            "--no-skip-html-tr",
            "--dry-run",
        ],
        {},
        {
            "source_lang": "de",
            "target_lang": "en",
            "base_dir": "book",
            "file": "book/a.md",
            "api_url": API_URL,
            "models_url": MODELS_URL,
            "model": MODEL,
            "no_skip_html_tr": True,
            "dry_run": True,
        },
        id="every-option",
    ),
    pytest.param(
        ["--target-lang", "de"],
        {
            "LM_STUDIO_API_URL": API_URL,
            "LM_STUDIO_MODELS_URL": MODELS_URL,
            "LM_STUDIO_MODEL": MODEL,
        },
        {"api_url": API_URL, "models_url": MODELS_URL, "model": MODEL},
        id="environment-overrides-defaults",
    ),
    pytest.param(
        ["--target-lang", "de", "--model", "cli-model"],
        {"LM_STUDIO_MODEL": "env-model"},
        {"model": "cli-model"},
        id="option-beats-environment",
    ),
]


@pytest.mark.parametrize("argv, env, expected", PARSER_CASES)
def test_build_arg_parser(argv, env, expected, monkeypatch):
    for name in ENV:
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    options = vars(mod.build_arg_parser().parse_args(argv))
    assert {name: options[name] for name in expected} == expected


def test_main_requires_the_target_language(sandbox, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", [PROG])
    with pytest.raises(SystemExit) as exc:
        mod.main()
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "the following arguments are required: --target-lang" in err
    assert _read(sandbox / ".skiplist") is None


# --- main ------------------------------------------------------------------

CH = {"manuscript/ch.md": "Hello.\n\nWorld."}
CH_DE = {"manuscript/ch.md": "<<Hello.>>\n\n<<World.>>"}
TREE = {"manuscript/a.md": "A.", "manuscript/sub/b.md": "B.", "manuscript/n.txt": "N."}
TREE_DE = {
    "manuscript/a.md": "<<A.>>",
    "manuscript/sub/b.md": "<<B.>>",
    "manuscript/n.txt": "N.",
}
TR = {"manuscript/t.md": "<tr><td>x</td></tr>\n\nText."}

# Each row: the command line after the program name, the files before
# (relative to the project root), the existing skiplist (None: none), the
# files after, the skiplist after (None: none), the (model, source, target)
# every chat request carries (None: no request) and the lines stdout must
# carry. With no --model the model list answers "auto-model".
MAIN_CASES = [
    pytest.param(
        ["--target-lang", "de", "--model", MODEL, "--file", "manuscript/ch.md"],
        CH,
        None,
        CH_DE,
        "manuscript/ch.md\n",
        (MODEL, "EN", "DE"),
        [
            "📊 Files processed/marked: 1",
            "📝 Skiplist updated with 1 new entries (total 1).",
        ],
        id="single-file",
    ),
    pytest.param(
        ["--source-lang", "de", "--target-lang", "en"],
        TREE,
        None,
        TREE_DE,
        "manuscript/a.md\nmanuscript/sub/b.md\n",
        ("auto-model", "DE", "EN"),
        ["📊 Files processed/marked: 2"],
        id="default-base-dir-and-auto-model",
    ),
    pytest.param(
        ["--target-lang", "fr", "--model", MODEL, "--dry-run"],
        TREE,
        None,
        TREE,
        None,
        None,
        ["🧪 Dry-run complete: manuscript/a.md not written."],
        id="dry-run",
    ),
    pytest.param(
        ["--target-lang", "de", "--model", MODEL, "--file", "manuscript/t.md"],
        TR,
        None,
        {"manuscript/t.md": "<tr><td>x</td></tr>\n\n<<Text.>>"},
        "manuscript/t.md\n",
        (MODEL, "EN", "DE"),
        [],
        id="html-tr-rows-kept-by-default",
    ),
    pytest.param(
        [
            "--target-lang",
            "de",
            "--model",
            MODEL,
            "--file",
            "manuscript/t.md",
            "--no-skip-html-tr",
        ],
        TR,
        None,
        {"manuscript/t.md": "<<<tr><td>x</td></tr>>>\n\n<<Text.>>"},
        "manuscript/t.md\n",
        (MODEL, "EN", "DE"),
        [],
        id="html-tr-rows-translated-on-request",
    ),
    pytest.param(
        ["--target-lang", "de", "--model", MODEL, "--file", "manuscript/ch.md"],
        CH,
        "manuscript/ch.md\n",
        CH,
        "manuscript/ch.md\n",
        None,
        ["⏭️  Skipped via .skiplist: manuscript/ch.md"],
        id="skiplisted-file-untouched",
    ),
    pytest.param(
        ["--target-lang", "de", "--model", MODEL, "--file", "manuscript/ch.md"],
        CH,
        "manuscript/old.md\n",
        CH_DE,
        "manuscript/ch.md\nmanuscript/old.md\n",
        (MODEL, "EN", "DE"),
        ["📝 Skiplist updated with 1 new entries (total 2)."],
        id="skiplist-merged",
    ),
    pytest.param(
        ["--target-lang", "de", "--model", MODEL, "--file", "manuscript/none.md"],
        CH,
        None,
        CH,
        None,
        None,
        ["❌ File not found: manuscript/none.md"],
        id="missing-file-no-skiplist",
    ),
]


@pytest.mark.parametrize(
    "argv, before, existing, after, skiplist, chat_request, out_lines", MAIN_CASES
)
def test_main(
    argv,
    before,
    existing,
    after,
    skiplist,
    chat_request,
    out_lines,
    sandbox,
    post,
    get,
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
    requests_made = {(c["json"]["model"], *_langs(c)) for c in post.calls}
    assert requests_made == ({chat_request} if chat_request else set())
    out = capsys.readouterr().out
    for line in out_lines:
        assert line in out


def test_main_persists_what_was_translated_before_ctrl_c(sandbox, monkeypatch, capsys):
    def interrupted(**kwargs):
        kwargs["translated_files"].add("manuscript/done.md")
        raise KeyboardInterrupt

    monkeypatch.setattr(mod, "translate_markdown_files", interrupted)
    monkeypatch.setattr(sys, "argv", [PROG, "--target-lang", "de"])
    mod.main()
    assert _read(sandbox / ".skiplist") == "manuscript/done.md\n"
    out = capsys.readouterr().out
    assert "🛑 Translation interrupted by user (Ctrl+C)." in out
    assert "📊 Files processed/marked: 1" in out
