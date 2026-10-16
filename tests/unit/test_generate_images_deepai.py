# tests/test_generate_images_deepai.py
from __future__ import annotations
import pytest

pytestmark = pytest.mark.unit


import json
from types import SimpleNamespace
from typing import Any, List
import requests

import manuscripta.images.generate_deepai as mod


class FakeResponse:
    def __init__(self, status_code=200, json_data=None, text="", content=b"IMG"):
        self.status_code = status_code
        self._json_data = json_data or {}
        self.text = text
        self.content = content

    def json(self):
        return self._json_data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(self.text)


class FakeSession:
    def __init__(self, post_resp: FakeResponse, get_resp: FakeResponse):
        self._post_resp = post_resp
        self._get_resp = get_resp
        self.post_calls: List[Any] = []
        self.get_calls: List[Any] = []

    def post(self, url, data=None, headers=None, timeout=None):
        self.post_calls.append(
            {"url": url, "data": data, "headers": headers, "timeout": timeout}
        )
        return self._post_resp

    def get(self, url, timeout=None):
        self.get_calls.append({"url": url, "timeout": timeout})
        return self._get_resp


def _text_file(tmp_path, text: str):
    f = tmp_path / "bad.json"
    f.write_text(text, encoding="utf-8")
    return f


# Each row: the loader, a builder returning the path it loads, the error
# logged; every loader returns {} for the path
BAD_JSON_CASES = [
    pytest.param(
        mod.load_character_profiles,
        lambda d: d / "missing.json",
        "File not found",
        id="load-character-profiles-missing-returns-empty",
    ),
    pytest.param(
        mod.load_json,
        lambda d: _text_file(d, "{ invalid json"),
        "Invalid JSON",
        id="invalid-json-logged",
    ),
    pytest.param(
        mod.load_json,
        lambda d: d / "missing.json",
        "File not found",
        id="load-json-missing-returns-empty",
    ),
    pytest.param(
        mod.load_character_profiles,
        lambda d: _text_file(d, "{ invalid json"),
        "Invalid JSON",
        id="load-character-profiles-invalid-returns-empty",
    ),
]


@pytest.mark.parametrize("loader, make_path, logged", BAD_JSON_CASES)
def test_bad_json_returns_empty(tmp_path, caplog, loader, make_path, logged):
    caplog.set_level("ERROR")
    assert loader(make_path(tmp_path)) == {}
    assert logged in caplog.text


# Each row: the base prompt, the character key, the profiles, the global
# style and the prompt build_prompt composes
BUILD_PROMPT_CASES = [
    pytest.param(
        "finds a key",
        "Timmy",
        {"Timmy": "Timmy, a brave boy"},
        "moody lighting",
        "Timmy, a brave boy, finds a key, moody lighting",
        id="single-character-and-style",
    ),
    # Unknown is omitted; order preserved
    pytest.param(
        "in a cave",
        ["Timmy", "Unknown", "Boronius"],
        {"Timmy": "Timmy brave", "Boronius": "Boronius wise"},
        None,
        "Timmy brave, Boronius wise, in a cave",
        id="multiple-characters-and-missing",
    ),
    # empty base prompt + style only
    pytest.param(
        "", "T", {"T": "Tall hero"}, "noir", "Tall hero, noir", id="empty-base-prompt"
    ),
    # None character, just base + style
    pytest.param(
        "walks", None, {"T": "Tall hero"}, "noir", "walks, noir", id="none-character"
    ),
    # tuple character key
    pytest.param(
        "enters", ("T",), {"T": "Tall hero"}, None, "Tall hero, enters", id="tuple-key"
    ),
    pytest.param(
        "walks",
        "Unknown",
        {"T": "Tall hero"},
        "noir",
        "walks, noir",
        id="unknown-single-character-omitted",
    ),
    pytest.param("walks", None, {}, None, "walks", id="base-prompt-alone"),
]


@pytest.mark.parametrize(
    "base, character, profiles, style, expected", BUILD_PROMPT_CASES
)
def test_build_prompt(base, character, profiles, style, expected):
    assert mod.build_prompt(base, character, profiles, style) == expected


POST_OK = FakeResponse(json_data={"output_url": "http://x/y.png"})

# Each row: the bytes already at out/a.png (None: no file), the POST and GET
# responses, extra keyword arguments, the result, the line logged, the bytes
# at out/a.png afterwards (None: no file), the POST and GET call counts
GENERATE_IMAGE_CASES = [
    pytest.param(
        b"OLD",
        FakeResponse(),
        FakeResponse(),
        {},
        True,
        "Skipped (exists)",
        b"OLD",
        (0, 0),
        id="skips-if-exists",
    ),
    pytest.param(
        None,
        FakeResponse(status_code=500, text="boom"),
        FakeResponse(),
        {},
        False,
        "DeepAI error 500",
        None,
        (1, 0),
        id="handles-api-error",
    ),
    pytest.param(
        None,
        POST_OK,
        FakeResponse(status_code=200, content=b"PNGDATA"),
        {},
        True,
        "Saved:",
        b"PNGDATA",
        (1, 1),
        id="success-writes-file",
    ),
    pytest.param(
        None,
        FakeResponse(json_data={}),
        FakeResponse(),
        {},
        False,
        "missing output_url",
        None,
        (1, 0),
        id="missing-output-url",
    ),
    pytest.param(
        b"OLD",
        POST_OK,
        FakeResponse(status_code=200, content=b"NEW"),
        {"overwrite": True},
        True,
        "Saved:",
        b"NEW",
        (1, 1),
        id="overwrite-true-will-not-skip",
    ),
    pytest.param(
        None,
        POST_OK,
        FakeResponse(status_code=404, text="not found"),
        {},
        False,
        "Failed to save image",
        None,
        (1, 1),
        id="download-raises-http-error",
    ),
]


@pytest.mark.parametrize(
    "existing, post_resp, get_resp, kwargs, ok, logged, saved, calls",
    GENERATE_IMAGE_CASES,
)
def test_generate_image(
    tmp_path, caplog, existing, post_resp, get_resp, kwargs, ok, logged, saved, calls
):
    caplog.set_level("INFO")
    out_dir = tmp_path / "out"
    target = out_dir / "a.png"
    if existing is not None:
        out_dir.mkdir()
        target.write_bytes(existing)
    session = FakeSession(post_resp, get_resp)

    result = mod.generate_image(
        session=session,
        prompt="p",
        filename="a.png",
        output_dir=out_dir,
        api_key="k",
        **kwargs,
    )
    assert result is ok
    assert logged in caplog.text
    assert (target.read_bytes() if target.exists() else None) == saved
    assert (len(session.post_calls), len(session.get_calls)) == calls


# Each row: what os.getenv returns for DEEPAI_API_KEY, the error logged for
# an absent prompt file
MAKE_CONFIG_FAILURES = [
    pytest.param(None, "No API key provided", id="requires-api-key"),
    pytest.param("", "No API key provided", id="empty-api-key-rejected"),
    pytest.param("abc", "Prompt file does not exist", id="missing-prompt-file"),
]


@pytest.mark.parametrize("env_key, logged", MAKE_CONFIG_FAILURES)
def test_make_config_failures(monkeypatch, tmp_path, caplog, env_key, logged):
    caplog.set_level("ERROR")
    # block getenv so a real key from the environment or .env cannot leak in
    monkeypatch.setattr(mod.os, "getenv", lambda *a, **k: env_key)
    args = SimpleNamespace(
        prompt_file=str(tmp_path / "nope.json"),
        output_dir=str(tmp_path / "out"),
        api_key=None,
        character_profile=str(tmp_path / "chars.json"),
        overwrite=False,
    )
    assert mod.make_config(args) is None
    assert logged in caplog.text


def test_api_key_flag_overrides_env(tmp_path, monkeypatch):
    # prepare prompt file
    pf = tmp_path / "p.json"
    pf.write_text('{"chapters":[]}', encoding="utf-8")
    monkeypatch.setenv("DEEPAI_API_KEY", "ENVKEY")
    args = ["--prompt-file", str(pf), "--api-key", "FLAGKEY"]
    cfg = mod.make_config(mod.parse_args(args))
    assert cfg is not None
    assert cfg.api_key == "FLAGKEY"


# Each row: the prompt JSON, the character profiles, what generate_image
# returns per call in order, the exit status, the prompts sent in order
MAIN_CASES = [
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
        [True, True],
        0,
        [
            "Timmy brave, scene one, cinematic",
            "Timmy brave, Boronius wise, scene two, cinematic",
        ],
        id="happy-path",
    ),
    # first ok, second fails
    pytest.param(
        {
            "chapters": [
                {
                    "prompts": [
                        {"prompt": "a", "filename": "a.png"},
                        {"prompt": "b", "filename": "b.png"},
                    ]
                }
            ]
        },
        {},
        [True, False],
        1,
        ["a", "b"],
        id="returns-failure-if-any-generation-fails",
    ),
    pytest.param({"chapters": []}, {}, [], 0, [], id="no-prompts-is-success"),
]


@pytest.mark.parametrize("prompts, chars, results, rc, sent", MAIN_CASES)
def test_main(monkeypatch, tmp_path, prompts, chars, results, rc, sent):
    prompt_file = tmp_path / "prompts.json"
    prompt_file.write_text(json.dumps(prompts), encoding="utf-8")
    char_file = tmp_path / "characters.json"
    char_file.write_text(json.dumps(chars), encoding="utf-8")

    # Fake generate_image to avoid network/files
    called = []

    def fake_generate_image(**kwargs):
        called.append(kwargs)
        return results[len(called) - 1]

    monkeypatch.setattr(mod, "generate_image", fake_generate_image)
    monkeypatch.setenv("DEEPAI_API_KEY", "abc123")

    assert (
        mod.main(
            [
                "--prompt-file",
                str(prompt_file),
                "--output-dir",
                str(tmp_path / "out"),
                "--character-profile",
                str(char_file),
            ]
        )
        == rc
    )
    assert [k["prompt"] for k in called] == sent
