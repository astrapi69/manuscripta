"""Unit tests for manuscripta.images.generate, the module-level DeepAI script.

The sibling tests/unit/test_generate_images_deepai.py covers the
session-based rewrite (generate_deepai). This module calls
``requests.post`` / ``requests.get`` directly, reads argv itself and
reports by printing, so the HTTP functions are stubbed in the module
namespace and the prints are read from capsys.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit

import json
import sys
from pathlib import Path

import manuscripta.images.generate as mod

TEXT2IMG_URL = "https://api.deepai.org/api/text2img"


class FakeResponse:
    def __init__(self, status_code=200, json_data=None, text="", content=b"IMG"):
        self.status_code = status_code
        self._json_data = json_data or {}
        self.text = text
        self.content = content

    def json(self):
        return self._json_data


class FakeRequests:
    """Stand-in for the two ``requests`` calls generate_image makes.

    ``get_resp`` may be an exception instance; the GET then raises it.
    """

    def __init__(self, post_resp, get_resp):
        self._post_resp = post_resp
        self._get_resp = get_resp
        self.posts: list[tuple[str, dict, dict]] = []
        self.gets: list[str] = []

    def post(self, url, data=None, headers=None):
        self.posts.append((url, data, headers))
        return self._post_resp

    def get(self, url):
        self.gets.append(url)
        if isinstance(self._get_resp, Exception):
            raise self._get_resp
        return self._get_resp


@pytest.fixture
def fake_requests(monkeypatch):
    """Install a FakeRequests for the given responses; return it."""

    def install(post_resp, get_resp):
        fake = FakeRequests(post_resp, get_resp)
        monkeypatch.setattr(mod.requests, "post", fake.post)
        monkeypatch.setattr(mod.requests, "get", fake.get)
        return fake

    return install


@pytest.fixture
def no_env_key(monkeypatch):
    """A key from the developer's environment or .env must not leak in."""
    monkeypatch.delenv("DEEPAI_API_KEY", raising=False)


def _json_file(directory: Path, name: str, payload) -> Path:
    path = directory / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _text_file(directory: Path, name: str, text: str) -> Path:
    path = directory / name
    path.write_text(text, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# load_character_profiles
# ---------------------------------------------------------------------------
# Each row: a builder returning the path to load, the profiles returned, the
# warning printed (None: nothing printed)
LOAD_PROFILES_CASES = [
    pytest.param(
        lambda d: _json_file(d, "chars.json", {"Timmy": "a brave boy"}),
        {"Timmy": "a brave boy"},
        None,
        id="valid-json-returns-mapping",
    ),
    pytest.param(
        lambda d: d / "missing.json",
        {},
        "Failed to load character profiles",
        id="missing-file-returns-empty",
    ),
    pytest.param(
        lambda d: _text_file(d, "bad.json", "{ invalid json"),
        {},
        "Failed to load character profiles",
        id="invalid-json-returns-empty",
    ),
]


@pytest.mark.parametrize("make_path, profiles, printed", LOAD_PROFILES_CASES)
def test_load_character_profiles(tmp_path, capsys, make_path, profiles, printed):
    assert mod.load_character_profiles(make_path(tmp_path)) == profiles
    out = capsys.readouterr().out
    if printed is None:
        assert out == ""
    else:
        assert printed in out


# ---------------------------------------------------------------------------
# generate_image
# ---------------------------------------------------------------------------
POST_OK = FakeResponse(json_data={"output_url": "http://x/y.png"})

# Each row: the bytes already at out/a.png (None: no file), the POST and GET
# responses (an exception as GET response is raised by the GET), the line
# printed, the bytes at out/a.png afterwards (None: no file), the POST and
# GET call counts
GENERATE_IMAGE_CASES = [
    pytest.param(
        b"OLD",
        POST_OK,
        FakeResponse(),
        "Skipped: a.png already exists",
        b"OLD",
        (0, 0),
        id="skips-if-exists",
    ),
    pytest.param(
        None,
        FakeResponse(status_code=500, text="boom"),
        FakeResponse(),
        "DeepAI error 500: boom",
        None,
        (1, 0),
        id="handles-api-error",
    ),
    pytest.param(
        None,
        POST_OK,
        FakeResponse(content=b"PNGDATA"),
        "Saved:",
        b"PNGDATA",
        (1, 1),
        id="success-writes-file",
    ),
    pytest.param(
        None,
        FakeResponse(json_data={}),
        FakeResponse(),
        "Failed to save image for prompt: p",
        None,
        (1, 0),
        id="missing-output-url",
    ),
    pytest.param(
        None,
        POST_OK,
        ConnectionError("no route"),
        "Failed to save image for prompt: p\nno route",
        None,
        (1, 1),
        id="download-raises",
    ),
]


@pytest.mark.parametrize(
    "existing, post_resp, get_resp, printed, saved, calls", GENERATE_IMAGE_CASES
)
def test_generate_image(
    tmp_path,
    capsys,
    fake_requests,
    existing,
    post_resp,
    get_resp,
    printed,
    saved,
    calls,
):
    out_dir = tmp_path / "out"
    target = out_dir / "a.png"
    if existing is not None:
        out_dir.mkdir()
        target.write_bytes(existing)
    fake = fake_requests(post_resp, get_resp)

    mod.generate_image(prompt="p", filename="a.png", output_dir=out_dir, api_key="k")

    assert printed in capsys.readouterr().out
    assert (target.read_bytes() if target.exists() else None) == saved
    assert (len(fake.posts), len(fake.gets)) == calls
    if fake.posts:
        assert fake.posts == [(TEXT2IMG_URL, {"text": "p"}, {"api-key": "k"})]
    if fake.gets:
        assert fake.gets == ["http://x/y.png"]


def test_generate_image_creates_missing_output_directory(tmp_path, fake_requests):
    out_dir = tmp_path / "deep" / "nested"
    fake_requests(POST_OK, FakeResponse(content=b"PNG"))

    mod.generate_image(prompt="p", filename="a.png", output_dir=out_dir, api_key="k")

    assert (out_dir / "a.png").read_bytes() == b"PNG"


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
@pytest.fixture
def capture_generate(monkeypatch):
    """Replace generate_image and return the list of its keyword arguments."""
    called: list[dict] = []
    monkeypatch.setattr(mod, "generate_image", lambda **kwargs: called.append(kwargs))
    return called


def _run_main(monkeypatch, *argv: str):
    monkeypatch.setattr(sys, "argv", ["generate-images", *argv])
    mod.main()


# Each row: the prompt JSON, the character profiles, the (prompt, filename)
# pairs generate_image receives in order
MAIN_PROMPT_CASES = [
    pytest.param(
        {
            "style": "cinematic",
            "chapters": [
                {
                    "prompts": [
                        {
                            "prompt": "scene one",
                            "character": "Timmy",
                            "filename": "img1.png",
                        },
                        {
                            "prompt": "scene two",
                            "character": ["Timmy", "Boronius"],
                            "filename": "img2.png",
                        },
                    ]
                }
            ],
        },
        {"Timmy": "Timmy brave", "Boronius": "Boronius wise"},
        [
            ("Timmy brave, scene one, cinematic", "img1.png"),
            ("Timmy brave, Boronius wise, scene two, cinematic", "img2.png"),
        ],
        id="characters-and-style-composed",
    ),
    pytest.param(
        {"chapters": [{"prompts": [{"prompt": "a cave"}]}]},
        {},
        [("a cave", "output.png")],
        id="bare-prompt-default-filename",
    ),
    pytest.param(
        {
            "chapters": [
                {
                    "prompts": [
                        {"prompt": "walks", "character": "Nobody", "filename": "w.png"}
                    ]
                }
            ]
        },
        {"Timmy": "Timmy brave"},
        [("walks", "w.png")],
        id="unknown-character-omitted",
    ),
    pytest.param(
        {
            "style": "noir",
            "chapters": [
                {
                    "prompts": [
                        {
                            "prompt": "walks",
                            "character": ["Nobody", "Timmy", "Ghost"],
                            "filename": "w.png",
                        }
                    ]
                }
            ],
        },
        {"Timmy": "Timmy brave"},
        [("Timmy brave, walks, noir", "w.png")],
        id="unknown-names-in-list-skipped",
    ),
    pytest.param(
        {
            "chapters": [
                {
                    "prompts": [
                        {
                            "prompt": "walks",
                            "character": ["Nobody", "Ghost"],
                            "filename": "w.png",
                        }
                    ]
                }
            ]
        },
        {"Timmy": "Timmy brave"},
        [("walks", "w.png")],
        id="list-of-unknown-names-leaves-bare-prompt",
    ),
    pytest.param(
        {
            "style": "noir",
            "chapters": [
                {"prompts": [{"prompt": "one", "filename": "1.png"}]},
                {},
                {"prompts": [{"prompt": "two", "filename": "2.png"}]},
            ],
        },
        {},
        [("one, noir", "1.png"), ("two, noir", "2.png")],
        id="chapter-without-prompts-skipped",
    ),
    pytest.param({}, {}, [], id="no-chapters-generates-nothing"),
]


@pytest.mark.parametrize("prompts, chars, sent", MAIN_PROMPT_CASES)
def test_main_composes_prompts(
    monkeypatch, tmp_path, capture_generate, prompts, chars, sent
):
    prompt_file = _json_file(tmp_path, "prompts.json", prompts)
    char_file = _json_file(tmp_path, "characters.json", chars)
    monkeypatch.setenv("DEEPAI_API_KEY", "abc123")

    _run_main(
        monkeypatch,
        "--prompt-file",
        str(prompt_file),
        "--output-dir",
        str(tmp_path / "out"),
        "--character-profile",
        str(char_file),
    )

    assert [(k["prompt"], k["filename"]) for k in capture_generate] == sent
    assert all(k["output_dir"] == tmp_path / "out" for k in capture_generate)
    assert all(k["api_key"] == "abc123" for k in capture_generate)


# Each row: the DEEPAI_API_KEY value (None: unset), the --api-key argument
# (None: not given), whether the prompt file exists, the error printed
MAIN_FAILURES = [
    pytest.param(None, None, True, "No API key provided", id="no-key-anywhere"),
    pytest.param("", None, True, "No API key provided", id="empty-env-key-rejected"),
    pytest.param(
        "abc", None, False, "Prompt file does not exist: ", id="missing-prompt-file"
    ),
    pytest.param(
        None, "FLAG", False, "Prompt file does not exist: ", id="flag-key-accepted"
    ),
]


@pytest.mark.parametrize("env_key, flag_key, prompt_exists, printed", MAIN_FAILURES)
def test_main_failures(
    monkeypatch,
    tmp_path,
    capsys,
    no_env_key,
    capture_generate,
    env_key,
    flag_key,
    prompt_exists,
    printed,
):
    if env_key is not None:
        monkeypatch.setenv("DEEPAI_API_KEY", env_key)
    prompt_file = tmp_path / "prompts.json"
    if prompt_exists:
        _json_file(tmp_path, "prompts.json", {"chapters": []})
    argv = ["--prompt-file", str(prompt_file)]
    if flag_key is not None:
        argv += ["--api-key", flag_key]

    _run_main(monkeypatch, *argv)

    out = capsys.readouterr().out
    assert printed in out
    if not prompt_exists:
        assert str(prompt_file) in out
    assert capture_generate == []


def test_api_key_flag_overrides_env(monkeypatch, tmp_path, capture_generate):
    prompt_file = _json_file(
        tmp_path, "prompts.json", {"chapters": [{"prompts": [{"prompt": "x"}]}]}
    )
    monkeypatch.setenv("DEEPAI_API_KEY", "ENVKEY")

    _run_main(monkeypatch, "--prompt-file", str(prompt_file), "--api-key", "FLAGKEY")

    assert [k["api_key"] for k in capture_generate] == ["FLAGKEY"]


def test_main_defaults_resolve_against_cwd(
    monkeypatch, tmp_path, capsys, capture_generate
):
    """Without arguments the prompt file, the profiles and the output
    directory are the documented paths relative to the working directory;
    an absent profile file is reported and does not stop the run."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config" / "data").mkdir(parents=True)
    _json_file(
        tmp_path / "config" / "data",
        "image_prompts.json",
        {"chapters": [{"prompts": [{"prompt": "x", "filename": "x.png"}]}]},
    )
    monkeypatch.setenv("DEEPAI_API_KEY", "abc")

    _run_main(monkeypatch)

    assert "Failed to load character profiles" in capsys.readouterr().out
    assert [(k["prompt"], k["output_dir"]) for k in capture_generate] == [
        ("x", Path("assets/illustrations"))
    ]
