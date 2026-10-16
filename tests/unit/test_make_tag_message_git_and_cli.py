#!/usr/bin/env python3
# tests/unit/test_make_tag_message_git_and_cli.py
"""Tests for the git, log-processing and command-line parts of
manuscripta.project.tag_message: the prompt template, GitOperations,
LogProcessor, write_file, validate_tag, the preflight checks, the parser,
--since-tag resolution, the interactive fill-in and main.

No real git runs: subprocess.run is replaced in the module's namespace by a
recorder that answers every git subcommand from a table. The ask_* helpers
have their own tests in test_make_tag_message_test_ask_helpers.py; here
they are replaced by scripted answers."""
from __future__ import annotations

import io
import json
import runpy
import subprocess
import sys
from datetime import datetime
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.unit

import manuscripta.project.tag_message as mtm
from manuscripta.project.tag_message import GitOperations, LogProcessor

PROG = "make-tag-message"
TAG = "v1.6.1-de"
BRANCH = "develop-de"
PRETTY = mtm.DEFAULT_PRETTY_FORMAT
STUB = f"# Tag message for {TAG}\n# Paste AI-generated content here\n"
AUTHOR = "Ada Lovelace <ada@example.org>"
DATE = "Mon Oct 13 10:00:00 2026 +0200"


# ---------------------------------------------------------------------------
# Git log samples
# ---------------------------------------------------------------------------


def subject_block(sha: str, subject: str, body: str = "") -> str:
    """One commit as DEFAULT_PRETTY_FORMAT prints it (explicit Subject: line)."""
    return (
        f"commit {sha}\nAuthor: {AUTHOR}\nDate: {DATE}\n"
        f"Subject: {subject}\n\n{body}\n"
    )


def plain_block(sha: str, subject: str) -> str:
    """One commit as git's default log format prints it (indented subject)."""
    return f"commit {sha}\nAuthor: {AUTHOR}\nDate:   {DATE}\n\n    {subject}\n"


SHA_A, SHA_B, SHA_C = "a" * 40, "b" * 40, "c" * 40
FEAT = subject_block(SHA_A, "feat: add content chapter", "Body of the feature.")
CHORE = subject_block(SHA_B, "chore: bump version")
FIX = subject_block(SHA_C, "fix: image alt attributes")
SAMPLE_LOG = FEAT + CHORE + FIX


def lines_of(*blocks: str) -> str:
    """The text filter_log returns when exactly these blocks are kept."""
    return "\n".join(line for block in blocks for line in block.splitlines())


# What main writes as history from SAMPLE_LOG with the default excludes:
# GitOperations.run strips git's output, so the last block loses its blank
# tail.
FILTERED_HISTORY = lines_of(FEAT, FIX).rstrip("\n")


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

# What a repository without the tag answers; rows override single entries.
CLEAN_GIT = {
    "rev-parse": (128, ""),
    "ls-remote": (0, ""),
    "rev-list": (0, "3\n"),
    "log": (0, SAMPLE_LOG),
    "describe": (128, ""),
    "tag": (0, ""),
    "push": (0, ""),
}


class FakeGit:
    """Stands in for subprocess.run: answers each git subcommand from a table
    of (returncode, stdout) and records every command and its keyword
    arguments."""

    def __init__(self, answers=None):
        self.answers = {**CLEAN_GIT, **(answers or {})}
        self.calls: list = []
        self.kwargs: list = []

    def __call__(self, cmd, **kwargs):
        self.calls.append(list(cmd))
        self.kwargs.append(kwargs)
        returncode, stdout = self.answers.get(cmd[1], (0, ""))
        stderr = f"fatal: {cmd[1]} failed" if returncode else ""
        return subprocess.CompletedProcess(cmd, returncode, stdout, stderr)

    def commands(self, subcommand: str) -> list:
        return [cmd for cmd in self.calls if cmd[1] == subcommand]


class Script:
    """Scripted answers for the ask_* helpers, keyed by a fragment of the
    prompt; records every prompt with its keyword arguments. An unscripted
    prompt fails the test instead of hanging on input()."""

    def __init__(self, answers=None):
        self.answers = dict(answers or {})
        self.asked: list = []

    def __call__(self, prompt, *args, **kwargs):
        self.asked.append((prompt, kwargs))
        for fragment, answer in self.answers.items():
            if fragment in prompt:
                return answer
        raise AssertionError(f"unscripted prompt: {prompt!r}")

    def default_of(self, fragment: str):
        return next(kw["default"] for p, kw in self.asked if fragment in p)

    def prompts(self) -> list:
        return [p for p, _ in self.asked]


@pytest.fixture(autouse=True)
def no_questionary(monkeypatch):
    monkeypatch.setattr(mtm, "questionary", None)


@pytest.fixture
def git(monkeypatch):
    fake = FakeGit()
    monkeypatch.setattr(mtm.subprocess, "run", fake)
    return fake


def ask(monkeypatch, answers=None) -> Script:
    script = Script(answers)
    for name in ("ask_text", "ask_confirm", "ask_choice", "ask_int"):
        monkeypatch.setattr(mtm, name, script)
    return script


def parse(*tail: str):
    return mtm.build_parser().parse_args(list(tail))


class Cli:
    """main() driven through sys.argv with the output dir in tmp_path, stdin
    not a terminal and git faked."""

    def __init__(self, monkeypatch, tmp_path, git):
        self.monkeypatch = monkeypatch
        self.out = tmp_path
        self.git = git
        monkeypatch.setattr(sys, "stdin", io.StringIO())

    def argv(self, *tail, tag=TAG, branch=BRANCH) -> list:
        argv = [PROG, "--output-dir", str(self.out)]
        if branch:
            argv += ["--branch", branch]
        if tag:
            argv += ["--tag", tag]
        return argv + [t.format(out=self.out) for t in tail]

    def run(self, *tail, tag=TAG, branch=BRANCH) -> None:
        self.monkeypatch.setattr(sys, "argv", self.argv(*tail, tag=tag, branch=branch))
        mtm.main()

    def history(self, name=f"{BRANCH}-history.txt"):
        return (self.out / name).read_text(encoding="utf-8")

    def prompt(self, tag=TAG):
        return (self.out / f"PROMPT_{tag}.md").read_text(encoding="utf-8")

    def stub_path(self):
        return self.out / f"TAGMSG_{TAG}.txt"


@pytest.fixture
def cli(monkeypatch, tmp_path, git):
    return Cli(monkeypatch, tmp_path, git)


# ===========================================================================
# get_template_prompt
# ===========================================================================

# Each row: the template name, fragments only that template's prompt carries
# (the built-in title templates keep {version_label} as a literal placeholder;
# only a --template-file renders the label)
TEMPLATE_PROMPTS = [
    pytest.param(
        "de",
        [
            "Title line: `Version {version_label} — <short theme>`",
            "   - **Content & Style**\n   - **Imagery & Accessibility**",
            "Readers of the German edition",
        ],
        id="de",
    ),
    pytest.param(
        "en",
        [
            "Title line: `Version {version_label} — <brief summary>`",
            "   - **Features & Content**\n   - **User Experience**",
            "End users and technical stakeholders",
            "main value proposition",
        ],
        id="en",
    ),
    pytest.param(
        "fr",
        ["Version {version_label} — <short theme>", "Readers of the German edition"],
        id="unknown-falls-back-to-de",
    ),
]


@pytest.mark.parametrize("name, fragments", TEMPLATE_PROMPTS)
def test_template_prompt_carries_template_branch_tag_and_log(name, fragments):
    prompt = mtm.get_template_prompt(name, BRANCH, TAG, "1.6.1-de", "commit abc")
    for fragment in fragments:
        assert fragment in prompt
    assert f"from branch **{BRANCH}**" in prompt
    assert f"release tag named **{TAG}**" in prompt
    assert prompt.endswith("```\ncommit abc\n```\n")


# ===========================================================================
# GitOperations
# ===========================================================================


def test_run_returns_stripped_stdout_and_captures_text(git):
    git.answers["status"] = (0, "  clean \n")
    assert GitOperations.run(["git", "status"], cwd="/repo") == "clean"
    assert git.calls == [["git", "status"]]
    assert git.kwargs == [
        {
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "cwd": "/repo",
            "text": True,
            "encoding": "utf-8",
        }
    ]


def test_run_raises_with_the_command_and_stderr_on_failure(git):
    git.answers["status"] = (1, "ignored")
    with pytest.raises(RuntimeError) as exc:
        GitOperations.run(["git", "status", "--short"])
    assert str(exc.value) == "Command failed: git status --short\nfatal: status failed"


# Each row: the keyword arguments of get_log and the git command it builds
LOG_COMMANDS = [
    pytest.param({}, ["git", "log", PRETTY, BRANCH], id="branch-only"),
    pytest.param(
        {"rev_range": "v1..v2"}, ["git", "log", PRETTY, "v1..v2"], id="range-wins"
    ),
    pytest.param(
        {"include_patches": True, "patches_mode": "brief"},
        ["git", "log", PRETTY, "-p", "-U1", BRANCH],
        id="brief-patches",
    ),
    pytest.param(
        {"include_patches": True, "patches_mode": "full"},
        ["git", "log", PRETTY, "-p", BRANCH],
        id="full-patches",
    ),
    pytest.param(
        {"include_patches": True},
        ["git", "log", PRETTY, BRANCH],
        id="patches-without-mode-add-nothing",
    ),
    pytest.param(
        {"include_patches": False, "patches_mode": "full"},
        ["git", "log", PRETTY, BRANCH],
        id="mode-without-patches-adds-nothing",
    ),
    pytest.param(
        {"max_commits": 5}, ["git", "log", PRETTY, "-n5", BRANCH], id="max-commits"
    ),
    pytest.param(
        {"max_commits": 0}, ["git", "log", PRETTY, BRANCH], id="zero-max-is-unlimited"
    ),
    pytest.param(
        {"extra_args": ["--since", "2025-08-01"]},
        ["git", "log", PRETTY, BRANCH, "--since", "2025-08-01"],
        id="extra-args-last",
    ),
    pytest.param(
        {
            "rev_range": "v1..v2",
            "include_patches": True,
            "patches_mode": "brief",
            "max_commits": 7,
            "extra_args": ["--since", "2025-08-01"],
        },
        ["git", "log", PRETTY, "-p", "-U1", "-n7", "v1..v2", "--since", "2025-08-01"],
        id="everything-in-order",
    ),
]


@pytest.mark.parametrize("kwargs, expected", LOG_COMMANDS)
def test_get_log_builds_the_command(kwargs, expected, git):
    call = {
        "branch": BRANCH,
        "rev_range": None,
        "pretty": PRETTY,
        "include_patches": False,
        "extra_args": [],
        **kwargs,
    }
    assert GitOperations.get_log(**call) == SAMPLE_LOG.strip()
    assert git.calls == [expected]


# Each row: the pattern, git describe's answer, the command asked, the tag
LAST_TAG_LOOKUPS = [
    pytest.param(
        None,
        (0, "v1.6.0-de\n"),
        ["git", "describe", "--tags", "--abbrev=0", BRANCH],
        "v1.6.0-de",
        id="without-pattern",
    ),
    pytest.param(
        "v*-de",
        (0, "v1.6.0-de\n"),
        ["git", "describe", "--tags", "--abbrev=0", "--match", "v*-de", BRANCH],
        "v1.6.0-de",
        id="with-pattern",
    ),
    pytest.param(
        "v*-de",
        (128, ""),
        ["git", "describe", "--tags", "--abbrev=0", "--match", "v*-de", BRANCH],
        None,
        id="no-tag-is-none",
    ),
]


@pytest.mark.parametrize("pattern, answer, command, expected", LAST_TAG_LOOKUPS)
def test_get_last_tag(pattern, answer, command, expected, git):
    git.answers["describe"] = answer
    assert GitOperations.get_last_tag(BRANCH, pattern) == expected
    assert git.calls == [command]


# Each row: the lookup, its arguments, git's answer, the command asked, the
# result
TAG_LOOKUPS = [
    pytest.param(
        GitOperations.tag_exists_local,
        (TAG,),
        (0, "abc123\n"),
        ["git", "rev-parse", f"refs/tags/{TAG}"],
        True,
        id="local-exists",
    ),
    pytest.param(
        GitOperations.tag_exists_local,
        (TAG,),
        (128, ""),
        ["git", "rev-parse", f"refs/tags/{TAG}"],
        False,
        id="local-missing",
    ),
    pytest.param(
        GitOperations.tag_exists_remote,
        (TAG,),
        (0, f"abc123\trefs/tags/{TAG}\n"),
        ["git", "ls-remote", "--tags", "origin", f"refs/tags/{TAG}", TAG],
        True,
        id="remote-exists",
    ),
    pytest.param(
        GitOperations.tag_exists_remote,
        (TAG,),
        (0, "\n"),
        ["git", "ls-remote", "--tags", "origin", f"refs/tags/{TAG}", TAG],
        False,
        id="remote-blank-output-is-missing",
    ),
    pytest.param(
        GitOperations.tag_exists_remote,
        (TAG,),
        (128, ""),
        ["git", "ls-remote", "--tags", "origin", f"refs/tags/{TAG}", TAG],
        False,
        id="remote-failure-is-missing",
    ),
    pytest.param(
        GitOperations.tag_exists_remote,
        (TAG, "upstream"),
        (0, f"abc123\trefs/tags/{TAG}\n"),
        ["git", "ls-remote", "--tags", "upstream", f"refs/tags/{TAG}", TAG],
        True,
        id="remote-named",
    ),
    pytest.param(
        GitOperations.count_commits,
        ("v1..v2",),
        (0, "42\n"),
        ["git", "rev-list", "--count", "v1..v2"],
        42,
        id="count",
    ),
    pytest.param(
        GitOperations.count_commits,
        ("v1..v2",),
        (0, "many"),
        ["git", "rev-list", "--count", "v1..v2"],
        0,
        id="count-not-a-number-is-zero",
    ),
    pytest.param(
        GitOperations.count_commits,
        ("v1..v2",),
        (128, ""),
        ["git", "rev-list", "--count", "v1..v2"],
        0,
        id="count-failure-is-zero",
    ),
]


@pytest.mark.parametrize("lookup, args, answer, command, expected", TAG_LOOKUPS)
def test_tag_lookups(lookup, args, answer, command, expected, git):
    git.answers[command[1]] = answer
    result = lookup(*args)
    assert result == expected and type(result) is type(expected)
    assert git.calls == [command]


# ===========================================================================
# LogProcessor.filter_log
# ===========================================================================


def test_filter_log_without_patterns_returns_the_raw_text():
    raw = "commit x\nSubject: chore: y\n"
    assert LogProcessor.filter_log(raw, []) is raw


# Each row: the commit blocks of the raw log, the subject patterns, the
# blocks kept (in order)
FILTER_DECISIONS = [
    pytest.param([FEAT, CHORE, FIX], ["chore"], [FEAT, FIX], id="drops-middle"),
    pytest.param([CHORE, FEAT], ["chore"], [FEAT], id="drops-first"),
    pytest.param([FEAT, CHORE], ["chore"], [FEAT], id="drops-last"),
    pytest.param([CHORE], ["chore"], [], id="drops-only"),
    pytest.param([FEAT, CHORE, FIX], ["wip"], [FEAT, CHORE, FIX], id="keeps-all"),
    pytest.param([FEAT, CHORE, FIX], ["CHORE", "Fix"], [FEAT], id="case-insensitive"),
    pytest.param([CHORE], ["bump"], [], id="matches-a-substring"),
    pytest.param(
        [subject_block(SHA_A, "feat: x", "chore follow-up")],
        ["chore"],
        [subject_block(SHA_A, "feat: x", "chore follow-up")],
        id="body-does-not-count",
    ),
    pytest.param(
        [plain_block(SHA_A, "feat: x"), plain_block(SHA_B, "Merge branch 'x'")],
        ["merge"],
        [plain_block(SHA_A, "feat: x")],
        id="plain-format-subject",
    ),
    pytest.param(
        [f"commit {SHA_A}\n\nchore: no headers\n"],
        ["chore"],
        [f"commit {SHA_A}\n\nchore: no headers\n"],
        id="headerless-block-is-kept",
    ),
]


@pytest.mark.parametrize("blocks, patterns, kept", FILTER_DECISIONS)
def test_filter_log(blocks, patterns, kept):
    assert LogProcessor.filter_log("".join(blocks), patterns) == lines_of(*kept)


# ===========================================================================
# LogProcessor.categorize_commits
# ===========================================================================

# Each row: a commit subject and the category it lands in
CATEGORY_KEYWORDS = [
    pytest.param("Update content wording", "content_style", id="content"),
    pytest.param("Tweak CSS spacing", "content_style", id="css-lowercased"),
    pytest.param("Add image captions", "imagery_accessibility", id="image"),
    pytest.param("Improve a11y of the nav", "imagery_accessibility", id="a11y"),
    pytest.param("Adjust layout grid", "structure_typography", id="layout"),
    pytest.param("Switch font family", "structure_typography", id="font"),
    pytest.param("Fix build pipeline", "metadata_build", id="build"),
    pytest.param("Deploy to staging", "metadata_build", id="deploy"),
    pytest.param("Rework parser", "other", id="other"),
    pytest.param("Style the image", "content_style", id="first-category-wins"),
]


@pytest.mark.parametrize("subject, category", CATEGORY_KEYWORDS)
def test_categorize_commits_by_subject(subject, category):
    categories = LogProcessor.categorize_commits(subject_block(SHA_A, subject))
    assert [c["hash"] for c in categories[category]] == [SHA_A]
    assert sum(len(c) for c in categories.values()) == 1


def all_commits(categories) -> list:
    return [commit for commits in categories.values() for commit in commits]


# Each row: the log text and the commits parsed out of it
PARSED_COMMITS = [
    pytest.param(
        subject_block(SHA_A, "feat: add content", "A body line."),
        [
            {
                "hash": SHA_A,
                "subject": "feat: add content",
                "author": AUTHOR,
                "date": DATE,
            }
        ],
        id="subject-line-wins-over-body",
    ),
    pytest.param(
        plain_block(SHA_A, "feat: add content"),
        [
            {
                "hash": SHA_A,
                "subject": "feat: add content",
                "author": AUTHOR,
                "date": "  " + DATE,
            }
        ],
        id="plain-format-first-line-is-the-subject",
    ),
    pytest.param(
        subject_block(SHA_A, "fix: image") + subject_block(SHA_B, "Rework parser"),
        [
            {"hash": SHA_A, "subject": "fix: image", "author": AUTHOR, "date": DATE},
            {"hash": SHA_B, "subject": "Rework parser", "author": AUTHOR, "date": DATE},
        ],
        id="two-commits",
    ),
    pytest.param("", [], id="empty-log"),
]


@pytest.mark.parametrize("log, commits", PARSED_COMMITS)
def test_categorize_commits_parses_the_fields(log, commits):
    categories = LogProcessor.categorize_commits(log)
    assert sorted(categories) == [
        "content_style",
        "imagery_accessibility",
        "metadata_build",
        "other",
        "structure_typography",
    ]
    assert all_commits(categories) == commits


# ===========================================================================
# write_file, validate_tag
# ===========================================================================


def test_write_file_creates_the_parents_and_writes_utf8(tmp_path):
    target = tmp_path / "dist" / "releases" / "TAGMSG.txt"
    mtm.write_file(target, "Größe — ok\n")
    assert target.read_bytes() == "Größe — ok\n".encode("utf-8")


# Each row: the tag and the message validate_tag exits with (None: accepted)
TAG_VALIDATIONS = [
    pytest.param("v1.6.1-de", None, id="accepted"),
    pytest.param("release/2026", None, id="slash-accepted"),
    pytest.param("", "Tag is required (e.g., v1.6.1-de).", id="empty"),
    pytest.param(
        "v1 .6", "Tag must not contain spaces, newlines, or tabs.", id="space"
    ),
    pytest.param(
        "v1\n6", "Tag must not contain spaces, newlines, or tabs.", id="newline"
    ),
    pytest.param("v1\t6", "Tag must not contain spaces, newlines, or tabs.", id="tab"),
]


@pytest.mark.parametrize("tag, message", TAG_VALIDATIONS)
def test_validate_tag(tag, message):
    if message is None:
        assert mtm.validate_tag(tag) is None
    else:
        with pytest.raises(SystemExit) as exc:
            mtm.validate_tag(tag)
        assert exc.value.code == message


# ===========================================================================
# preflight_checks
# ===========================================================================


def message_path(args):
    return args.message_file or f"{args.output_dir}/TAGMSG_{args.tag}.txt"


# Each row: git answers to override, the extra arguments, the content of the
# message file (None: no file), the issues reported ({out}: the output dir)
PREFLIGHT_FINDINGS = [
    pytest.param({}, [], None, [], id="clean"),
    pytest.param(
        {"rev-parse": (0, "abc123")},
        [],
        None,
        [f"⚠️  Tag '{TAG}' already exists locally"],
        id="tag-exists-locally",
    ),
    pytest.param(
        {"ls-remote": (0, f"abc123\trefs/tags/{TAG}")},
        [],
        None,
        [
            f"⚠️  Tag '{TAG}' already exists on remote",
            f"    💡 To fix: git tag -d {TAG} && git push --delete origin {TAG}",
        ],
        id="tag-exists-on-remote-with-remedy",
    ),
    pytest.param(
        {"rev-parse": (0, "abc123"), "ls-remote": (0, f"abc123\trefs/tags/{TAG}")},
        [],
        None,
        [
            f"⚠️  Tag '{TAG}' already exists locally",
            f"⚠️  Tag '{TAG}' already exists on remote",
            f"    💡 To fix: git tag -d {TAG} && git push --delete origin {TAG}",
        ],
        id="tag-exists-everywhere",
    ),
    pytest.param(
        {},
        ["--create-tag"],
        None,
        [f"❌ Message file not found: {{out}}/TAGMSG_{TAG}.txt"],
        id="create-tag-default-file-missing",
    ),
    pytest.param(
        {},
        ["--create-tag"],
        "",
        [f"❌ Message file is empty: {{out}}/TAGMSG_{TAG}.txt"],
        id="create-tag-default-file-empty",
    ),
    pytest.param({}, ["--create-tag"], "Release notes", [], id="create-tag-file-ok"),
    pytest.param(
        {},
        ["--create-tag", "--message-file", "{out}/notes/msg.txt"],
        None,
        ["❌ Message file not found: {out}/notes/msg.txt"],
        id="create-tag-named-file-missing",
    ),
    pytest.param(
        {},
        ["--message-file", "{out}/notes/msg.txt"],
        None,
        [],
        id="file-only-checked-when-creating",
    ),
    pytest.param(
        {"rev-list": (0, "0")},
        ["--range", "v1..v2"],
        None,
        ["❌ No commits found in range: v1..v2"],
        id="range-without-commits",
    ),
    pytest.param(
        {"rev-list": (128, "")},
        ["--range", "v1..v2"],
        None,
        ["❌ No commits found in range: v1..v2"],
        id="range-count-fails",
    ),
    pytest.param(
        {"rev-list": (0, "1001")},
        ["--range", "v1..v2"],
        None,
        ["⚠️  Large commit range: 1001 commits (consider --max-commits)"],
        id="range-too-large",
    ),
    pytest.param(
        {"rev-list": (0, "1000")}, ["--range", "v1..v2"], None, [], id="range-at-limit"
    ),
    pytest.param({"rev-list": (0, "0")}, [], None, [], id="no-range-no-count"),
]


@pytest.mark.parametrize("answers, tail, content, issues", PREFLIGHT_FINDINGS)
def test_preflight_checks(answers, tail, content, issues, git, tmp_path):
    git.answers.update(answers)
    args = parse(
        "--tag",
        TAG,
        "--output-dir",
        str(tmp_path),
        *[t.format(out=tmp_path) for t in tail],
    )
    if content is not None:
        mtm.write_file(mtm.Path(message_path(args)), content)
    assert mtm.preflight_checks(args) == [i.format(out=tmp_path) for i in issues]


def test_preflight_asks_git_for_local_then_remote_then_range(git, tmp_path):
    args = parse("--tag", TAG, "--output-dir", str(tmp_path), "--range", "v1..v2")
    mtm.preflight_checks(args)
    assert git.calls == [
        ["git", "rev-parse", f"refs/tags/{TAG}"],
        ["git", "ls-remote", "--tags", "origin", f"refs/tags/{TAG}", TAG],
        ["git", "rev-list", "--count", "v1..v2"],
    ]


# ===========================================================================
# build_parser
# ===========================================================================

# Each row: the arguments, the attribute and the value parsed
PARSER_VALUES = [
    pytest.param([], "branch", None, id="branch-unset"),
    pytest.param([], "tag", None, id="tag-unset"),
    pytest.param([], "pretty", PRETTY, id="pretty-default"),
    pytest.param([], "patches", "none", id="patches-default"),
    pytest.param([], "exclude", ["chore", "merge", "wip"], id="exclude-default"),
    pytest.param(["--exclude"], "exclude", [], id="exclude-emptied"),
    pytest.param(
        ["--exclude", "fix", "docs"], "exclude", ["fix", "docs"], id="exclude-set"
    ),
    pytest.param([], "output_dir", "dist/releases", id="output-dir-default"),
    pytest.param([], "template", "de", id="template-default"),
    pytest.param(["--template", "en"], "template", "en", id="template-en"),
    pytest.param([], "max_commits", None, id="max-commits-default"),
    pytest.param(["--max-commits", "5"], "max_commits", 5, id="max-commits-int"),
    pytest.param(["--range", "v1..v2"], "rev_range", "v1..v2", id="range-dest"),
    pytest.param(["--since-tag", "auto"], "since_tag", "auto", id="since-tag"),
    pytest.param(["--since", "2025-08-01"], "since", "2025-08-01", id="since"),
    pytest.param(["--patches", "brief"], "patches", "brief", id="patches-brief"),
    pytest.param(
        ["--template-file", "t.md"], "template_file", "t.md", id="template-file"
    ),
    pytest.param(
        ["--message-file", "m.txt"], "message_file", "m.txt", id="message-file"
    ),
    *[
        pytest.param([], attr, False, id=f"{attr}-off")
        for attr in (
            "interactive",
            "dry_run",
            "emit_json",
            "create_tag",
            "push",
            "auto_stub",
            "force_stub",
        )
    ],
    *[
        pytest.param([f"--{attr.replace('_', '-')}"], attr, True, id=f"{attr}-on")
        for attr in (
            "interactive",
            "dry_run",
            "emit_json",
            "create_tag",
            "push",
            "auto_stub",
            "force_stub",
        )
    ],
]


@pytest.mark.parametrize("tail, attr, value", PARSER_VALUES)
def test_parser_values(tail, attr, value):
    assert getattr(parse(*tail), attr) == value


# Each row: the arguments and the text of the usage error
PARSER_REJECTS = [
    pytest.param(["--patches", "all"], "invalid choice: 'all'", id="patches-choice"),
    pytest.param(["--template", "fr"], "invalid choice: 'fr'", id="template-choice"),
    pytest.param(
        ["--max-commits", "many"], "invalid int value: 'many'", id="max-commits-int"
    ),
    pytest.param(["--bogus"], "unrecognized arguments: --bogus", id="unknown-option"),
]


@pytest.mark.parametrize("tail, text", PARSER_REJECTS)
def test_parser_rejects(tail, text, capsys):
    with pytest.raises(SystemExit) as exc:
        parse(*tail)
    assert exc.value.code == 2
    assert text in capsys.readouterr().err


# ===========================================================================
# resolve_since_tag
# ===========================================================================

# Each row: the arguments, git answers to override, the commands asked, the
# range resolved, the line printed
SINCE_TAG_RESOLUTIONS = [
    pytest.param(
        ["--tag", TAG, "--since-tag", "v1.6.0-de"],
        {},
        [],
        None,
        "",
        id="explicit-tag-is-left-alone",
    ),
    pytest.param(
        ["--tag", TAG, "--since-tag", "auto"],
        {"tag": (0, "v1.6.0-de\nv1.5.0-de\n")},
        [["git", "tag", "--list", "v*-de", "--sort=-creatordate"]],
        f"v1.6.0-de..{BRANCH}",
        f"🔍 Auto-detected range: v1.6.0-de..{BRANCH}\n",
        id="newest-listed-tag",
    ),
    pytest.param(
        ["--tag", TAG, "--branch", "main", "--since-tag", "auto"],
        {"tag": (0, "v1.6.0-de\n")},
        [["git", "tag", "--list", "v*-de", "--sort=-creatordate"]],
        "v1.6.0-de..main",
        "🔍 Auto-detected range: v1.6.0-de..main\n",
        id="range-ends-at-the-branch",
    ),
    pytest.param(
        ["--tag", TAG, "--since-tag", "auto"],
        {"tag": (0, ""), "describe": (0, "v1.5.9-de\n")},
        [
            ["git", "tag", "--list", "v*-de", "--sort=-creatordate"],
            ["git", "describe", "--tags", "--abbrev=0", "--match", "v*-de", BRANCH],
        ],
        f"v1.5.9-de..{BRANCH}",
        f"🔍 Auto-detected range: v1.5.9-de..{BRANCH}\n",
        id="empty-list-falls-back-to-describe",
    ),
    pytest.param(
        ["--tag", TAG, "--since-tag", "auto"],
        {"tag": (128, ""), "describe": (0, "v1.5.9-de\n")},
        [
            ["git", "tag", "--list", "v*-de", "--sort=-creatordate"],
            ["git", "describe", "--tags", "--abbrev=0", "--match", "v*-de", BRANCH],
        ],
        f"v1.5.9-de..{BRANCH}",
        f"🔍 Auto-detected range: v1.5.9-de..{BRANCH}\n",
        id="failed-list-falls-back-to-describe",
    ),
    pytest.param(
        ["--tag", "v1.6.1", "--since-tag", "auto"],
        {"describe": (0, "v1.6.0\n")},
        [["git", "describe", "--tags", "--abbrev=0", BRANCH]],
        f"v1.6.0..{BRANCH}",
        f"🔍 Auto-detected range: v1.6.0..{BRANCH}\n",
        id="tag-without-suffix-has-no-pattern",
    ),
    pytest.param(
        ["--since-tag", "auto"],
        {"describe": (0, "v1.6.0\n")},
        [["git", "describe", "--tags", "--abbrev=0", BRANCH]],
        f"v1.6.0..{BRANCH}",
        f"🔍 Auto-detected range: v1.6.0..{BRANCH}\n",
        id="no-tag-has-no-pattern",
    ),
    pytest.param(
        ["--tag", TAG, "--since-tag", "auto"],
        {"tag": (0, "")},
        [
            ["git", "tag", "--list", "v*-de", "--sort=-creatordate"],
            ["git", "describe", "--tags", "--abbrev=0", "--match", "v*-de", BRANCH],
        ],
        None,
        "⚠️  No previous tag found, using full branch history\n",
        id="nothing-found-keeps-full-history",
    ),
]


@pytest.mark.parametrize(
    "tail, answers, commands, rev_range, printed", SINCE_TAG_RESOLUTIONS
)
def test_resolve_since_tag(tail, answers, commands, rev_range, printed, git, capsys):
    git.answers.update(answers)
    args = parse(*tail)
    mtm.resolve_since_tag(args)
    assert args.rev_range == rev_range
    assert git.calls == commands
    assert capsys.readouterr().out == printed


# ===========================================================================
# fill_from_interactive
# ===========================================================================

# The answers that take every prompt's shortest path
BASE_ANSWERS = {
    "Branch:": BRANCH,
    "Tag (e.g., v1.6.1-de):": TAG,
    "Template:": "de",
    "Commit range:": "Full branch history",
    "Configure advanced options?": False,
    "Create annotated tag?": False,
    "Create empty message stub file?": True,
}

BASE_FILL = {
    "branch": BRANCH,
    "tag": TAG,
    "template": "de",
    "since_tag": None,
    "rev_range": None,
    "since": None,
    "patches": "none",
    "max_commits": None,
    "emit_json": False,
    "create_tag": False,
    "message_file": None,
    "push": False,
    "auto_stub": True,
}

# Each row: answers that override BASE_ANSWERS, the arguments given before
# the prompts, the attributes that differ from BASE_FILL afterwards
INTERACTIVE_FILLS = [
    pytest.param({}, [], {}, id="shortest-path"),
    pytest.param(
        {"Branch:": "main", "Tag (e.g., v1.6.1-de):": "v2.0.0-en", "Template:": "en"},
        [],
        {"branch": "main", "tag": "v2.0.0-en", "template": "en"},
        id="core-answers-are-taken",
    ),
    pytest.param(
        {"Commit range:": "Since last tag (auto)"},
        [],
        {"since_tag": "auto"},
        id="since-last-tag",
    ),
    pytest.param(
        {"Commit range:": "Custom range", "Rev range": "v1.6.0-de..develop-de"},
        [],
        {"rev_range": "v1.6.0-de..develop-de"},
        id="custom-range",
    ),
    pytest.param(
        {"Commit range:": "Since date", "Since date": "2025-08-01"},
        [],
        {"since": "2025-08-01"},
        id="since-date",
    ),
    pytest.param(
        {
            "Configure advanced options?": True,
            "Include patches for precision?": True,
            "Patch detail:": "full",
            "Limit number of commits?": True,
            "Max commits:": 50,
            "Emit JSON summary?": True,
        },
        [],
        {"patches": "full", "max_commits": 50, "emit_json": True},
        id="advanced-all-on",
    ),
    pytest.param(
        {
            "Configure advanced options?": True,
            "Include patches for precision?": False,
            "Limit number of commits?": False,
            "Emit JSON summary?": False,
        },
        ["--patches", "brief", "--max-commits", "9"],
        {"patches": "brief", "max_commits": 9},
        id="advanced-declined-keeps-given-values",
    ),
    pytest.param(
        {
            "Create annotated tag?": True,
            "Tag message file path:": "notes/msg.txt",
            "Push tag to origin after creation?": True,
        },
        [],
        {"create_tag": True, "message_file": "notes/msg.txt", "push": True},
        id="create-and-push",
    ),
    pytest.param(
        {
            "Create annotated tag?": True,
            "Tag message file path:": "notes/msg.txt",
            "Push tag to origin after creation?": False,
        },
        [],
        {"create_tag": True, "message_file": "notes/msg.txt"},
        id="create-without-push",
    ),
    pytest.param(
        {"Create annotated tag?": True, "Push tag to origin after creation?": False},
        ["--message-file", "given.txt"],
        {"create_tag": True, "message_file": "given.txt"},
        id="create-keeps-a-given-message-file",
    ),
    pytest.param(
        {"Create annotated tag?": False},
        ["--push"],
        {"push": True},
        id="declining-creation-leaves-push-alone",
    ),
    pytest.param(
        {"Create empty message stub file?": False},
        [],
        {"auto_stub": False},
        id="no-stub",
    ),
]


@pytest.mark.parametrize("answers, tail, changed", INTERACTIVE_FILLS)
def test_fill_from_interactive(answers, tail, changed, monkeypatch):
    ask(monkeypatch, {**BASE_ANSWERS, **answers})
    args = parse(*tail)
    result = mtm.fill_from_interactive(args)
    assert result is args
    expected = {**BASE_FILL, **changed}
    assert {k: getattr(args, k) for k in expected} == expected


# Each row: answers that override BASE_ANSWERS, the arguments given before
# the prompts, a prompt and the default it offers
INTERACTIVE_DEFAULTS = [
    pytest.param({}, [], "Branch:", BRANCH, id="branch-falls-back-to-develop-de"),
    pytest.param({}, ["--branch", "main"], "Branch:", "main", id="branch-given"),
    pytest.param({}, [], "Tag (e.g., v1.6.1-de):", "", id="tag-unset"),
    pytest.param({}, ["--tag", "v2"], "Tag (e.g., v1.6.1-de):", "v2", id="tag-given"),
    pytest.param({}, [], "Template:", "de", id="template-default"),
    pytest.param({}, ["--template", "en"], "Template:", "en", id="template-given"),
    pytest.param({}, [], "Commit range:", "Full branch history", id="range"),
    pytest.param({}, [], "Create annotated tag?", False, id="create-off"),
    pytest.param({}, ["--create-tag"], "Create annotated tag?", True, id="create-on"),
    pytest.param(
        {
            "Create annotated tag?": True,
            "Tag message file path:": "m",
            "Push tag": False,
        },
        ["--output-dir", "out"],
        "Tag message file path:",
        f"out/TAGMSG_{TAG}.txt",
        id="message-file-under-output-dir",
    ),
    pytest.param(
        {
            "Create annotated tag?": True,
            "Tag message file path:": "m",
            "Push tag": True,
        },
        ["--push"],
        "Push tag to origin after creation?",
        True,
        id="push-given",
    ),
    pytest.param(
        {
            "Configure advanced options?": True,
            "Include patches": False,
            "Limit number": False,
            "Emit JSON summary?": True,
        },
        ["--emit-json"],
        "Emit JSON summary?",
        True,
        id="emit-json-given",
    ),
    pytest.param(
        {
            "Configure advanced options?": True,
            "Include patches": True,
            "Patch detail:": "brief",
            "Limit number": True,
            "Max commits:": 100,
            "Emit JSON summary?": False,
        },
        [],
        "Max commits:",
        100,
        id="max-commits-default-100",
    ),
    pytest.param({}, [], "Create empty message stub file?", True, id="stub-on"),
]


@pytest.mark.parametrize("answers, tail, prompt, default", INTERACTIVE_DEFAULTS)
def test_fill_from_interactive_offers_the_given_value_as_default(
    answers, tail, prompt, default, monkeypatch
):
    script = ask(monkeypatch, {**BASE_ANSWERS, **answers})
    mtm.fill_from_interactive(parse(*tail))
    assert script.default_of(prompt) == default


def test_fill_from_interactive_validates_the_tag_answer(monkeypatch):
    script = ask(monkeypatch, BASE_ANSWERS)
    mtm.fill_from_interactive(parse())
    tag_prompt = next(kw for p, kw in script.asked if p.startswith("Tag ("))
    assert tag_prompt["validate"] is mtm.validate_tag


def test_fill_from_interactive_offers_the_template_names(monkeypatch):
    script = ask(monkeypatch, BASE_ANSWERS)
    mtm.fill_from_interactive(parse())
    assert script.prompts() == [
        "Branch:",
        "Tag (e.g., v1.6.1-de):",
        "Template:",
        "Commit range:",
        "Configure advanced options?",
        "Create annotated tag?",
        "Create empty message stub file?",
    ]


def test_fill_from_interactive_skips_the_template_choice_with_one_template(
    monkeypatch,
):
    monkeypatch.setattr(mtm, "TEMPLATES", {"de": mtm.TEMPLATES["de"]})
    script = ask(monkeypatch, BASE_ANSWERS)
    args = mtm.fill_from_interactive(parse())
    assert "Template:" not in script.prompts()
    assert args.template == "de"


# ===========================================================================
# main: when it prompts
# ===========================================================================

# Each row: the arguments, whether stdin is a terminal, whether main prompts
PROMPT_TRIGGERS = [
    pytest.param(
        ["--interactive", "--branch", BRANCH, "--tag", TAG], False, True, id="flag"
    ),
    pytest.param(["--branch", BRANCH], True, True, id="tty-without-tag"),
    pytest.param(["--tag", TAG], True, True, id="tty-without-branch"),
    pytest.param(["--branch", BRANCH, "--tag", TAG], True, False, id="tty-complete"),
    pytest.param(["--tag", TAG], False, False, id="no-tty-defaults-branch"),
]


@pytest.mark.parametrize("tail, tty, prompts", PROMPT_TRIGGERS)
def test_main_prompts_only_when_needed(tail, tty, prompts, cli, capsys):
    filled = []

    def fill(args):
        filled.append(args)
        args.branch, args.tag = "asked-branch", "asked-tag"
        return args

    cli.monkeypatch.setattr(mtm, "fill_from_interactive", fill)
    cli.monkeypatch.setattr(sys, "stdin", SimpleNamespace(isatty=lambda: tty))
    cli.run("--dry-run", *tail, tag=None, branch=None)
    out = capsys.readouterr().out
    assert (len(filled) == 1) is prompts
    if prompts:
        assert f"Prompt file  : {cli.out}/PROMPT_asked-tag.md" in out
        assert f"History file : {cli.out}/asked-branch-history.txt" in out
    else:
        assert f"Prompt file  : {cli.out}/PROMPT_{TAG}.md" in out
        assert f"History file : {cli.out}/{BRANCH}-history.txt" in out


def test_main_without_a_tag_is_a_usage_error_when_not_prompting(cli, capsys):
    with pytest.raises(SystemExit) as exc:
        cli.run(tag=None)
    assert exc.value.code == 2
    assert "--tag is required in non-interactive mode" in capsys.readouterr().err
    assert cli.git.calls == []


def test_main_rejects_a_tag_with_spaces_before_touching_git(cli):
    with pytest.raises(SystemExit) as exc:
        cli.run(tag="v1 6")
    assert exc.value.code == "Tag must not contain spaces, newlines, or tabs."
    assert cli.git.calls == []


# ===========================================================================
# main: dry run
# ===========================================================================

# Each row: the arguments, lines the dry run announces, lines it does not
# ({out}: the output dir)
DRY_RUN_LINES = [
    pytest.param(
        [],
        [
            "🏃 DRY RUN - showing what would be executed:",
            f"  📝 History file : {{out}}/{BRANCH}-history.txt",
            f"  🤖 Prompt file  : {{out}}/PROMPT_{TAG}.md",
        ],
        ["JSON file", "Stub file", "Create tag", "Push tag"],
        id="plain",
    ),
    pytest.param(
        ["--range", "v1..v2"],
        [f"  📝 History file : {{out}}/{BRANCH}-history_v1__v2.txt"],
        [],
        id="range-in-history-name",
    ),
    pytest.param(
        ["--emit-json"],
        [f"  📊 JSON file    : {{out}}/COMMITS_{TAG}.json"],
        ["Stub file"],
        id="json",
    ),
    pytest.param(
        ["--auto-stub"],
        [f"  📄 Stub file    : {{out}}/TAGMSG_{TAG}.txt"],
        ["JSON file"],
        id="stub",
    ),
    pytest.param(
        ["--create-tag"],
        [
            f"  🏷️  Create tag   : {TAG} from {{out}}/TAGMSG_{TAG}.txt",
            f"❌ Message file not found: {{out}}/TAGMSG_{TAG}.txt",
            "❌ Critical issues found. Please fix before proceeding.",
        ],
        ["Push tag"],
        id="create-tag-survives-critical-issues",
    ),
    pytest.param(
        ["--create-tag", "--push", "--message-file", "notes/msg.txt"],
        [
            f"  🏷️  Create tag   : {TAG} from notes/msg.txt",
            f"  📤 Push tag     : {TAG} to origin",
        ],
        [],
        id="create-and-push",
    ),
    pytest.param(["--push"], [], ["Push tag"], id="push-without-create"),
]


@pytest.mark.parametrize("tail, present, absent", DRY_RUN_LINES)
def test_main_dry_run_announces_without_writing(tail, present, absent, cli, capsys):
    cli.run("--dry-run", *tail)
    out = capsys.readouterr().out
    for line in present:
        assert line.format(out=cli.out) in out
    for text in absent:
        assert text not in out
    assert list(cli.out.iterdir()) == []
    assert cli.git.commands("log") == []
    assert cli.git.commands("tag") == []


# ===========================================================================
# main: preflight outcomes
# ===========================================================================

# Each row: git answers to override, the arguments, scripted confirmations,
# the exit code (None: runs through), lines printed
PREFLIGHT_OUTCOMES = [
    pytest.param(
        {"rev-list": (0, "0")},
        ["--range", "v1..v2"],
        {},
        1,
        [
            "🔍 Preflight check results:",
            "  ❌ No commits found in range: v1..v2",
            "❌ Critical issues found. Please fix before proceeding.",
        ],
        id="critical-exits-1",
    ),
    pytest.param(
        {"rev-list": (0, "0")},
        ["--range", "v1..v2", "--dry-run"],
        {},
        None,
        ["❌ Critical issues found", "🏃 DRY RUN"],
        id="critical-only-reported-in-dry-run",
    ),
    pytest.param(
        {"rev-parse": (0, "abc123")},
        [],
        {},
        None,
        [f"  ⚠️  Tag '{TAG}' already exists locally", "✅ Generated files:"],
        id="warning-continues-without-interactive",
    ),
    pytest.param(
        {"ls-remote": (0, f"abc123\trefs/tags/{TAG}")},
        ["--interactive"],
        {"Proceed despite warnings?": False},
        "Aborted by user.",
        [
            f"  ⚠️  Tag '{TAG}' already exists on remote",
            f"      💡 To fix: git tag -d {TAG} && git push --delete origin {TAG}",
        ],
        id="warning-declined-interactively",
    ),
    pytest.param(
        {"rev-parse": (0, "abc123")},
        ["--interactive"],
        {"Proceed despite warnings?": True},
        None,
        ["✅ Generated files:"],
        id="warning-accepted-interactively",
    ),
    pytest.param(
        {"rev-parse": (0, "abc123")},
        ["--interactive", "--dry-run"],
        {},
        None,
        ["already exists locally", "🏃 DRY RUN"],
        id="warning-not-asked-in-dry-run",
    ),
]


@pytest.mark.parametrize("answers, tail, confirms, code, printed", PREFLIGHT_OUTCOMES)
def test_main_preflight_outcomes(answers, tail, confirms, code, printed, cli, capsys):
    cli.git.answers.update(answers)
    cli.monkeypatch.setattr(mtm, "fill_from_interactive", lambda args: args)
    ask(cli.monkeypatch, confirms)
    if code is None:
        cli.run(*tail)
    else:
        with pytest.raises(SystemExit) as exc:
            cli.run(*tail)
        assert exc.value.code == code
    out = capsys.readouterr().out
    for line in printed:
        assert line in out
    assert (cli.git.commands("log") != []) is (code is None and "--dry-run" not in tail)


# ===========================================================================
# main: the files it generates
# ===========================================================================

# Each row: the arguments and the git log command main runs
LOG_COMMANDS_FROM_CLI = [
    pytest.param([], ["git", "log", PRETTY, BRANCH], id="plain"),
    pytest.param(["--range", "v1..v2"], ["git", "log", PRETTY, "v1..v2"], id="range"),
    pytest.param(
        ["--since", "2025-08-01"],
        ["git", "log", PRETTY, BRANCH, "--since", "2025-08-01"],
        id="since",
    ),
    pytest.param(
        ["--patches", "brief"], ["git", "log", PRETTY, "-p", "-U1", BRANCH], id="brief"
    ),
    pytest.param(
        ["--patches", "full"], ["git", "log", PRETTY, "-p", BRANCH], id="full"
    ),
    pytest.param(["--patches", "none"], ["git", "log", PRETTY, BRANCH], id="none"),
    pytest.param(
        ["--max-commits", "5"], ["git", "log", PRETTY, "-n5", BRANCH], id="max"
    ),
    pytest.param(
        ["--pretty=--oneline"], ["git", "log", "--oneline", BRANCH], id="pretty"
    ),
]


@pytest.mark.parametrize("tail, command", LOG_COMMANDS_FROM_CLI)
def test_main_fetches_the_log_as_asked(tail, command, cli):
    cli.run(*tail)
    assert cli.git.commands("log") == [command]


def test_main_echoes_the_resolved_parameters(cli, capsys):
    cli.run("--range", "v1..v2", "--max-commits", "5", "--since", "2025-08-01")
    out = capsys.readouterr().out
    assert f"🔍 Fetching git log from {BRANCH}...\n" in out
    assert "    Range: v1..v2\n" in out
    assert f"    Pretty: {PRETTY}\n" in out
    assert "    Patches: none\n" in out
    assert "    Max commits: 5\n" in out
    assert "    Since: 2025-08-01\n" in out
    assert "🧹 Filtering commits (excluding: chore, merge, wip)...\n" in out


def test_main_resolves_since_tag_auto_before_fetching_the_log(cli):
    cli.git.answers["tag"] = (0, "v1.6.0-de\n")
    cli.run("--since-tag", "auto")
    assert cli.git.commands("log") == [["git", "log", PRETTY, f"v1.6.0-de..{BRANCH}"]]
    assert (cli.out / f"{BRANCH}-history_v1.6.0-de__{BRANCH}.txt").exists()


# Each row: the arguments and the name of the history file
HISTORY_NAMES = [
    pytest.param([], f"{BRANCH}-history.txt", id="branch-only"),
    pytest.param(
        ["--range", "v1.6.0-de..develop-de"],
        f"{BRANCH}-history_v1.6.0-de__develop-de.txt",
        id="range-with-double-underscore",
    ),
    pytest.param(
        ["--range", "feature/x..origin/main"],
        f"{BRANCH}-history_feature_x__origin_main.txt",
        id="slashes-become-underscores",
    ),
    pytest.param(
        ["--range", "a b..c^2"],
        f"{BRANCH}-history_a_b__c_2.txt",
        id="odd-characters-collapse",
    ),
]


@pytest.mark.parametrize("tail, name", HISTORY_NAMES)
def test_main_names_the_history_after_branch_and_range(tail, name, cli, capsys):
    cli.run(*tail)
    assert cli.history(name) == FILTERED_HISTORY
    assert f"  📝 History: {cli.out / name}\n" in capsys.readouterr().out


def test_main_runs_history_with_a_custom_branch(cli):
    cli.run(branch="main")
    assert cli.git.commands("log") == [["git", "log", PRETTY, "main"]]
    assert cli.history("main-history.txt") == FILTERED_HISTORY


# Each row: the arguments, the commits kept in the history, the commits
# dropped
EXCLUDE_DECISIONS = [
    pytest.param([], [SHA_A, SHA_C], [SHA_B], id="default-drops-chore"),
    pytest.param(["--exclude"], [SHA_A, SHA_B, SHA_C], [], id="empty-keeps-all"),
    pytest.param(
        ["--exclude", "fix", "feat"], [SHA_B], [SHA_A, SHA_C], id="own-patterns"
    ),
]


@pytest.mark.parametrize("tail, kept, dropped", EXCLUDE_DECISIONS)
def test_main_filters_the_history_by_exclude(tail, kept, dropped, cli):
    cli.run(*tail)
    history = cli.history()
    assert [sha for sha in (SHA_A, SHA_B, SHA_C) if f"commit {sha}" in history] == kept
    assert all(f"commit {sha}" not in history for sha in dropped)
    assert all(f"commit {sha}" not in cli.prompt() for sha in dropped)


# Each row: the arguments and fragments of the prompt written
PROMPT_CONTENTS = [
    pytest.param(
        [],
        [
            "**Role:** You are a release notes editor.",
            f"from branch **{BRANCH}**",
            f"release tag named **{TAG}**",
            "Title line: `Version {version_label} — <short theme>`",
            "**Content & Style**",
            f"```\ncommit {SHA_A}\n",
            f"commit {SHA_C}\n",
        ],
        id="de-default",
    ),
    pytest.param(
        ["--template", "en"],
        ["Version {version_label} — <brief summary>", "**Features & Content**"],
        id="en",
    ),
    pytest.param(
        ["--max-commits", "5"],
        ["_Note: Output limited to 5 most recent commits for brevity._\n\n**Role:**"],
        id="max-commits-note-first",
    ),
]


@pytest.mark.parametrize("tail, fragments", PROMPT_CONTENTS)
def test_main_writes_the_prompt(tail, fragments, cli, capsys):
    cli.run(*tail)
    prompt = cli.prompt()
    for fragment in fragments:
        assert fragment in prompt
    assert f"commit {SHA_B}" not in prompt
    out = capsys.readouterr().out
    assert f"  🤖 AI Prompt: {cli.out}/PROMPT_{TAG}.md\n" in out
    assert f"  1. Copy the prompt from PROMPT_{TAG}.md\n" in out
    assert f"  3. Save the AI output to TAGMSG_{TAG}.txt\n" in out


def test_main_does_not_prefix_a_note_without_max_commits(cli):
    cli.run()
    assert cli.prompt().startswith("**Role:**")


# Each row: the tag and the version label a template file renders for it
VERSION_LABELS = [
    pytest.param("v1.6.1-de", "1.6.1-de", id="leading-v-dropped"),
    pytest.param("1.6.1-de", "1.6.1-de", id="no-v-kept"),
    pytest.param("vv2", "v2", id="only-the-first-v"),
    pytest.param("rev1", "rev1", id="inner-v-kept"),
]


@pytest.mark.parametrize("tag, label", VERSION_LABELS)
def test_main_derives_the_version_label_from_the_tag(tag, label, cli):
    (cli.out / "label.md").write_text("Version {version_label}", "utf-8")
    cli.run("--template-file", "{out}/label.md", tag=tag)
    assert cli.prompt(tag) == f"Version {label}"


def test_main_renders_a_custom_template_file(cli):
    template = cli.out / "template.md"
    template.write_text(
        "Tag {tag} on {branch}, label {version_label}\n{git_log}", "utf-8"
    )
    cli.run("--template-file", str(template), "--template", "en")
    assert cli.prompt() == f"Tag {TAG} on {BRANCH}, label 1.6.1-de\n{FILTERED_HISTORY}"


def test_main_emits_a_json_summary(cli, capsys):
    cli.run("--emit-json")
    summary = json.loads((cli.out / f"COMMITS_{TAG}.json").read_text("utf-8"))
    datetime.fromisoformat(summary.pop("timestamp"))
    assert summary == {
        "tag": TAG,
        "branch": BRANCH,
        "total_commits": 2,
        "categories": {
            "content_style": [
                {
                    "hash": SHA_A,
                    "subject": "feat: add content chapter",
                    "author": AUTHOR,
                    "date": DATE,
                }
            ],
            "imagery_accessibility": [
                {
                    "hash": SHA_C,
                    "subject": "fix: image alt attributes",
                    "author": AUTHOR,
                    "date": DATE,
                }
            ],
            "structure_typography": [],
            "metadata_build": [],
            "other": [],
        },
    }
    out = capsys.readouterr().out
    assert "📊 Generating JSON commit summary...\n" in out
    assert f"  📊 JSON Summary: {cli.out}/COMMITS_{TAG}.json\n" in out


def test_main_writes_no_json_by_default(cli, capsys):
    cli.run()
    assert not (cli.out / f"COMMITS_{TAG}.json").exists()
    assert "JSON" not in capsys.readouterr().out


# Each row: the arguments, the stub content before (None: no file), after,
# whether the summary lists the stub
STUB_DECISIONS = [
    pytest.param([], None, None, False, id="off-by-default"),
    pytest.param(["--auto-stub"], None, STUB, True, id="auto-stub-creates"),
    pytest.param(["--auto-stub"], "my notes", "my notes", True, id="auto-stub-keeps"),
    pytest.param(
        ["--auto-stub", "--force-stub"], "my notes", STUB, True, id="force-overwrites"
    ),
    pytest.param(
        ["--force-stub"], "my notes", "my notes", False, id="force-alone-keeps"
    ),
    pytest.param(["--force-stub"], None, None, False, id="force-alone-creates-nothing"),
    pytest.param([], "my notes", "my notes", False, id="off-leaves-a-file-alone"),
]


@pytest.mark.parametrize("tail, before, after, listed", STUB_DECISIONS)
def test_main_stub_decisions(tail, before, after, listed, cli, capsys):
    if before is not None:
        cli.stub_path().write_text(before, encoding="utf-8")
    cli.run(*tail)
    stub = cli.stub_path()
    assert (stub.read_text(encoding="utf-8") if stub.exists() else None) == after
    assert (f"  📄 Message Stub: {stub}\n" in capsys.readouterr().out) is listed


# ===========================================================================
# main: tag creation
# ===========================================================================

MESSAGE = "A fine release with content and images.\n"

# Each row: the arguments, the message file content (None: no file), scripted
# confirmations, the abort message (None: runs through), the git commands
# after the log, a line printed
TAG_CREATIONS = [
    pytest.param(
        ["--create-tag"],
        MESSAGE,
        {},
        None,
        [["git", "tag", "-a", TAG, "-F", f"{{out}}/TAGMSG_{TAG}.txt", BRANCH]],
        f"✅ Created tag {TAG} at {BRANCH}\n",
        id="creates",
    ),
    pytest.param(
        ["--create-tag", "--push"],
        MESSAGE,
        {},
        None,
        [
            ["git", "tag", "-a", TAG, "-F", f"{{out}}/TAGMSG_{TAG}.txt", BRANCH],
            ["git", "push", "origin", TAG],
        ],
        f"✅ Pushed tag {TAG} to origin\n",
        id="creates-and-pushes",
    ),
    pytest.param(
        ["--create-tag", "--message-file", "{out}/notes/msg.txt"],
        MESSAGE,
        {},
        None,
        [["git", "tag", "-a", TAG, "-F", "{out}/notes/msg.txt", BRANCH]],
        f"🏷️  Creating tag {TAG}...\n",
        id="named-message-file",
    ),
    pytest.param(
        ["--push"],
        MESSAGE,
        {},
        None,
        [],
        "  4. Run with --create-tag --push to finalize\n",
        id="push-alone-does-nothing",
    ),
    pytest.param(
        ["--create-tag"],
        "short",
        {},
        f"Message file appears to be empty or too small: {{out}}/TAGMSG_{TAG}.txt",
        [],
        "✅ Generated files:",
        id="tiny-message-aborts-after-generating",
    ),
    pytest.param(
        ["--create-tag", "--interactive"],
        MESSAGE,
        {"Create tag": False},
        "Aborted before tag creation.",
        [],
        "✅ Generated files:",
        id="creation-declined",
    ),
    pytest.param(
        ["--create-tag", "--push", "--interactive"],
        MESSAGE,
        {"Create tag": True, "Push tag": False},
        None,
        [["git", "tag", "-a", TAG, "-F", f"{{out}}/TAGMSG_{TAG}.txt", BRANCH]],
        "Skipped push.\n",
        id="push-declined",
    ),
    pytest.param(
        ["--create-tag", "--push", "--interactive"],
        MESSAGE,
        {"Create tag": True, "Push tag": True},
        None,
        [
            ["git", "tag", "-a", TAG, "-F", f"{{out}}/TAGMSG_{TAG}.txt", BRANCH],
            ["git", "push", "origin", TAG],
        ],
        f"📤 Pushing tag {TAG}...\n",
        id="both-confirmed",
    ),
]


@pytest.mark.parametrize(
    "tail, content, confirms, abort, commands, printed", TAG_CREATIONS
)
def test_main_tag_creation(
    tail, content, confirms, abort, commands, printed, cli, capsys
):
    args = parse(*cli.argv(*tail)[1:])
    if content is not None:
        mtm.write_file(mtm.Path(message_path(args)), content)
    cli.monkeypatch.setattr(mtm, "fill_from_interactive", lambda args: args)
    script = ask(cli.monkeypatch, confirms)
    if abort is None:
        cli.run(*tail)
    else:
        with pytest.raises(SystemExit) as exc:
            cli.run(*tail)
        assert exc.value.code == abort.format(out=cli.out)
    log_index = cli.git.calls.index(cli.git.commands("log")[0])
    expected = [[part.format(out=cli.out) for part in cmd] for cmd in commands]
    assert cli.git.calls[log_index + 1 :] == expected
    assert printed in capsys.readouterr().out
    create_prompt = f"Create tag {TAG} at {BRANCH} using {message_path(args)}?"
    push_prompt = f"Push tag {TAG} to origin?"
    if not confirms:
        assert script.prompts() == []
    elif confirms["Create tag"]:
        assert script.prompts() == [create_prompt, push_prompt]
    else:
        assert script.prompts() == [create_prompt]


def test_main_confirms_creation_with_the_message_path_and_default_yes(cli):
    mtm.write_file(cli.stub_path(), MESSAGE)
    cli.monkeypatch.setattr(mtm, "fill_from_interactive", lambda args: args)
    script = ask(cli.monkeypatch, {"Create tag": True, "Push tag": True})
    cli.run("--create-tag", "--push", "--interactive")
    assert script.asked == [
        (f"Create tag {TAG} at {BRANCH} using {cli.stub_path()}?", {"default": True}),
        (f"Push tag {TAG} to origin?", {"default": True}),
    ]


def test_main_aborts_when_the_message_file_vanishes_after_preflight(cli):
    cli.monkeypatch.setattr(mtm, "preflight_checks", lambda args: [])
    with pytest.raises(SystemExit) as exc:
        cli.run("--create-tag")
    assert exc.value.code == (
        f"--create-tag specified, but message file not found:\n  {cli.stub_path()}\n"
        "➡️ Tip: Save the AI output to this path first"
    )
    assert cli.git.commands("tag") == []


def test_main_lets_a_failing_git_tag_propagate(cli):
    mtm.write_file(cli.stub_path(), MESSAGE)
    cli.git.answers["tag"] = (128, "")
    with pytest.raises(RuntimeError, match="Command failed: git tag -a"):
        cli.run("--create-tag", "--push")
    assert cli.git.commands("push") == []


# ===========================================================================
# the __main__ guard
# ===========================================================================

# Each row: the arguments and the exit status of the script run as __main__
# (no tag given: a usage error, which a dry run swallows)
MAIN_GUARD_EXITS = [
    pytest.param(["--dry-run"], 0, id="dry-run-exits-0"),
    pytest.param([], 2, id="usage-error-exits-2"),
]


@pytest.mark.parametrize("tail, code", MAIN_GUARD_EXITS)
def test_script_run_as_main(tail, code, cli, capsys):
    cli.monkeypatch.setattr(sys, "argv", cli.argv(*tail, tag=None))
    with pytest.raises(SystemExit) as exc:
        runpy.run_path(mtm.__file__, run_name="__main__")
    assert exc.value.code == code
    assert "--tag is required" in capsys.readouterr().err
