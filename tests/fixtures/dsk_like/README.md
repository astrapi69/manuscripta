# `dsk_like` — realistic book fixture for e2e_wheel tests

This fixture mirrors the structure of
[`der-selbststaendige-sklave`](https://github.com/astrapi69/der-selbststaendige-sklave)
(the canonical manuscripta consumer) at a reduced scale, to keep
fixture size and build time bounded:

- `manuscript/front-matter/foreword.md` — one front-matter page with an image reference
- `manuscript/chapters/` — two short chapters with images and headings
- `manuscript/back-matter/imprint.md` — one back-matter page
- `config/metadata.yaml` — realistic metadata (German content, typical publisher / rights fields)
- `assets/figures/` — two small solid-colour PNGs referenced from the chapters
- `assets/covers/cover.png` — cover image

The fixture is intentionally **static** (checked into git) rather than
generated at test time. See `docs/TESTING.md` §6.3: "Realistic fixtures
for E2E live under `tests/fixtures/` as static files, not generated
programmatically."

Scope: consumed by `tests/e2e_wheel/` only. Other layers build ad-hoc
programmatic fixtures in `tmp_path`.
