# LedgerLens Final Presentation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `docs/hackathon_final_doc/ledgerlens-final.html`, a six-slide HTML deck for the Factored Hackathon 2026 final.

**Architecture:** A single self-contained HTML file that reuses the shell of `docs/hackathon_final_doc/ledgerlens-pitch.html`: its palette, fonts, `data-step` reveals, navigation and deep links.
- Task 1 builds the shell with six stub slides.
- Tasks 2–5 each replace stub sections with real slides and add that slide's CSS under a marker comment.
- Slide 5 clones slide 4's SVG at load time, so the architecture diagram exists in only one place.
- The pytest tests parse the file with the stdlib `html.parser`, because `bs4` isn't installed. They check structure, content and the arithmetic.
- Task 6 checks the deck's behavior in Chrome.

**Tech Stack:** Plain HTML/CSS/JS with Google Fonts (Funnel Display and Funnel Sans). Python 3.13 with pytest 9 for the structural tests.

**Spec:** `docs/superpowers/specs/2026-10-04-final-presentation-design.md`

## Global Constraints

- Deliverable: `docs/hackathon_final_doc/ledgerlens-final.html`. `docs/hackathon_final_doc/ledgerlens-pitch.html` stays unchanged.
- One self-contained file. Plain HTML, CSS and JS, no frameworks. Fonts come from Google Fonts only, and there's no `<script src>`.
- English, at most 6 slides, with the counter showing "n / 6".
- Palette: `--bg #07081a`, `--ink #161a33`, `--text #f4f6fb`, `--soft #9aa0bb`, `--faint #3a3f5c`. Cobalt (`#2e46e8` / `#6f82ff`) means the AI; mango (`#f2a31b`) means humans.
- Every number carries a source tag:
  - `.src.data`: "Source: provided contact-center dataset", only for numbers from `docs/agent-handoff/metrics.json`
  - `.src.build`: "From the LedgerLens build"
  - `.src.bench`: "Benchmark: <publisher, year>"
  - `.src.assume`: "Illustrative assumption"
- No customer PII.
- Every cost figure on slide 6 shows a tooltip on hover and on keyboard focus.
- Use `.venv/Scripts/python` (3.13) and never Anaconda. Run tests from the repo root.
- `git add` only the files you name. Never stage `infra-cdk/config.yaml`, `frontend/.env` or `frontend/public/aws-exports.json`. Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Don't push.

## Review Focus

1. **Clicking or tapping a cost figure on slide 6 must not advance the slide.** The deck's click handler has to ignore `.cost`, `details`, `summary` and links. Task 1 adds a test for this.
2. **Key `6` and deep links `#6` / `#6.3` must reach slide 6.** The pitch only handled keys 1–5. Task 1 adds a test for this.
3. **A count-up number must end on exactly the value written in the HTML.** If the format code is wrong, a number such as $1.13 could finish as "1". Task 1 adds a test that every `[data-count]`'s static text equals its formatted value.
4. **Tooltips must stay on screen at 1366×768.** Tooltips in the right column need `tip-left`. Task 5 adds a test that the right-column `.cost` items use `tip-left`. Task 6 checks every tooltip by hovering.
5. **At 390 px wide there must be no horizontal scroll.** Every multi-column grid collapses to one column at ≤900 px. Task 1 adds a test that the media query lists every grid class. Task 6 checks it in Chrome.

---

## File structure

| File | Responsibility |
|---|---|
| `docs/hackathon_final_doc/ledgerlens-final.html` | The deck: shell, the six slides, their CSS and the navigation script |
| `tests/unit/final_deck/__init__.py` | Makes the test folder a package (empty, like `tests/unit/cedar_policy/__init__.py`) |
| `tests/unit/final_deck/deck_html.py` | Parses the deck into a small element tree for the tests |
| `tests/unit/final_deck/test_final_deck.py` | Structure, content and arithmetic tests, one section per task |

---

### Task 1: Test parser and deck shell

**Files:**
- Create: `tests/unit/final_deck/__init__.py`
- Create: `tests/unit/final_deck/deck_html.py`
- Create: `tests/unit/final_deck/test_final_deck.py`
- Create: `docs/hackathon_final_doc/ledgerlens-final.html`

**Interfaces:**
- Produces, in `deck_html.py`:
  - `DECK_PATH: Path`
  - `load_deck() -> Element`
  - `slides(root: Element) -> list[Element]`
  - `fmt(value: float, format: str) -> str`
  - `Element`, with `.tag`, `.attrs: dict`, `.classes() -> set[str]`, `.text() -> str`, `.iter()`, `.find_all(pred) -> list[Element]`
- Produces, in the deck:
  - Section classes `s-problem`, `s-solution`, `s-scope`, `s-arch`, `s-how`, `s-profit`, in that order.
  - CSS marker comments `/* ---------- slide N: <name> ---------- */`, where later tasks insert CSS.
  - The JS array `hooks`, into which later tasks push `(slide, step) => void` functions, at the marker `// slide hooks`.
  - The `data-count` / `data-format` count-up, with formats `int`, `pct`, `dec`, `usd2` and `usd3`.
  - The tooltip classes `.cost`, `.tip`, `.tip-left` and `.tip-down`.
  - The source tags `.src.data`, `.src.build`, `.src.bench` and `.src.assume`, inside a `.tags` row.
  - Shared `.card` and `.k` styles.

- [ ] **Step 1: Write the parser**

`tests/unit/final_deck/__init__.py`: an empty file.

`tests/unit/final_deck/deck_html.py`:

```python
"""Parse docs/hackathon_final_doc/ledgerlens-final.html into a small element tree for the tests.

bs4 isn't installed, so this builds the tree with the stdlib HTMLParser. Text is
kept in document order, so Element.text() reads the way the slide does.
"""

from html.parser import HTMLParser
from pathlib import Path

DECK_PATH = Path(__file__).resolve().parents[3] / "docs" / "pitch" / "ledgerlens-final.html"

VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


class Element:
    def __init__(self, tag, attrs, parent):
        self.tag = tag
        self.attrs = dict(attrs)
        self.parent = parent
        self.children = []

    def classes(self):
        return set((self.attrs.get("class") or "").split())

    def text(self):
        parts = [c if isinstance(c, str) else c.text() for c in self.children]
        return " ".join("".join(parts).split())

    def iter(self):
        yield self
        for child in self.children:
            if isinstance(child, Element):
                yield from child.iter()

    def find_all(self, pred):
        return [e for e in self.iter() if pred(e)]


class _Builder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Element("#root", [], None)
        self.cur = self.root

    def handle_starttag(self, tag, attrs):
        el = Element(tag, attrs, self.cur)
        self.cur.children.append(el)
        if tag not in VOID:
            self.cur = el

    def handle_startendtag(self, tag, attrs):
        self.cur.children.append(Element(tag, attrs, self.cur))

    def handle_endtag(self, tag):
        node = self.cur
        while node is not None and node.tag != tag:
            node = node.parent
        if node is not None and node.parent is not None:
            self.cur = node.parent

    def handle_data(self, data):
        self.cur.children.append(data)


def load_deck():
    builder = _Builder()
    builder.feed(DECK_PATH.read_text(encoding="utf-8"))
    return builder.root


def slides(root):
    return root.find_all(lambda e: e.tag == "section" and "slide" in e.classes())


def fmt(value, format):
    """Python twin of the deck's countUp() formats, so the tests can check the final text."""
    if format == "usd2":
        return f"${value:.2f}"
    if format == "usd3":
        return f"${value:.3f}"
    if format == "pct":
        return f"{value:.1f}%"
    if format == "dec":
        return ("−" if value < 0 else "") + f"{abs(value):.1f}"
    return f"{round(value):,}"
```

- [ ] **Step 2: Write the failing shell tests**

`tests/unit/final_deck/test_final_deck.py`:

```python
"""Structure, content and arithmetic checks for docs/hackathon_final_doc/ledgerlens-final.html.

Spec: docs/superpowers/specs/2026-10-04-final-presentation-design.md.
Behavior (navigation, tooltips on hover, layout) is checked in Chrome; these tests
pin what can be read from the file.
"""

import re
from urllib.parse import urlparse

import pytest

from tests.unit.final_deck.deck_html import DECK_PATH, fmt, load_deck, slides

SLIDE_CLASSES = ["s-problem", "s-solution", "s-scope", "s-arch", "s-how", "s-profit"]


@pytest.fixture(scope="module")
def deck():
    return load_deck()


@pytest.fixture(scope="module")
def source():
    return DECK_PATH.read_text(encoding="utf-8")


def slide(deck, name):
    return next(s for s in slides(deck) if name in s.classes())


# ---------- Task 1: shell ----------

def test_six_slides_in_order(deck):
    found = [next(c for c in s.classes() if c.startswith("s-")) for s in slides(deck)]
    assert found == SLIDE_CLASSES


def test_every_slide_has_a_label_and_step_count(deck):
    for s in slides(deck):
        assert s.attrs.get("aria-label")
        assert s.attrs.get("data-steps", "").isdigit()


def test_steps_never_exceed_the_slide_step_count(deck):
    for s in slides(deck):
        last = int(s.attrs["data-steps"])
        for el in s.find_all(lambda e: "data-step" in e.attrs and e is not s):
            assert 0 <= int(el.attrs["data-step"]) <= last, el.attrs


def test_counter_starts_at_one_of_six(deck):
    count = deck.find_all(lambda e: e.attrs.get("id") == "count")[0]
    assert count.text() == "1 / 6"


def test_only_google_fonts_and_no_external_scripts(deck):
    for link in deck.find_all(lambda e: e.tag == "link" and e.attrs.get("href", "").startswith("http")):
        assert urlparse(link.attrs["href"]).hostname in {"fonts.googleapis.com", "fonts.gstatic.com"}
    assert not deck.find_all(lambda e: e.tag == "script" and "src" in e.attrs)


def test_ids_are_unique(deck):
    ids = [e.attrs["id"] for e in deck.iter() if "id" in e.attrs]
    assert len(ids) == len(set(ids))


def test_keys_and_deep_links_reach_slide_six(source):
    assert "/^[1-6]$/" in source
    assert r"location.hash.match(/^#(\d)(?:\.(\d))?$/)" in source


def test_click_to_advance_ignores_tooltips_details_and_links(source):
    assert "closest('a,button,.cost,details,summary')" in source


def test_count_up_numbers_end_on_their_static_text(deck):
    for el in deck.find_all(lambda e: "data-count" in e.attrs):
        expected = fmt(float(el.attrs["data-count"]), el.attrs.get("data-format", "int"))
        assert el.text() == expected, (el.attrs, el.text())


def test_narrow_screens_collapse_every_grid(source):
    narrow = source.split("@media (max-width: 900px)")[1].split("}\n}")[0]
    for cls in [".beats", ".pillars", ".outcomes", ".cols", ".out-grid", ".how", ".profit"]:
        assert cls in narrow, cls
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/unit/final_deck -q`
Expected: every test errors with `FileNotFoundError` naming `ledgerlens-final.html`.

- [ ] **Step 4: Write the shell**

`docs/hackathon_final_doc/ledgerlens-final.html`:

```html
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>LedgerLens Final</title>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Cpath d='M15.2 2.5A18.2 18.2 0 0 0 15.2 29.5Z' fill='%232e46e8'/%3E%3Cpath d='M16.8 2.5A18.2 18.2 0 0 1 16.8 29.5Z' fill='%23f2a31b'/%3E%3C/svg%3E">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Funnel+Display:wght@300..800&family=Funnel+Sans:wght@300..800&display=swap" rel="stylesheet">
<style>
/* Palette from the app (frontend/src/styles/globals.css): ink, cobalt = AI, mango = human.
   Shell copied from ledgerlens-pitch.html. */
:root {
  --bg: #07081a;
  --ink: #161a33;
  --text: #f4f6fb;
  --soft: #9aa0bb;
  --faint: #3a3f5c;
  --line: rgba(244, 246, 251, 0.09);
  --cobalt: #2e46e8;
  --cobalt-hi: #6f82ff;
  --mango: #f2a31b;
  --green: #3fbf8f;
  --ease: cubic-bezier(0.22, 1, 0.36, 1);
  --display: "Funnel Display", "Funnel Sans", system-ui, sans-serif;
  --sans: "Funnel Sans", system-ui, -apple-system, "Segoe UI", sans-serif;
  --mono: ui-monospace, Consolas, monospace;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
html, body { height: 100%; background: var(--bg); color: var(--text); font-family: var(--sans); overflow: hidden; -webkit-font-smoothing: antialiased; }
button { font: inherit; color: inherit; background: none; border: 0; cursor: pointer; }
:focus-visible { outline: 2px solid var(--cobalt-hi); outline-offset: 4px; border-radius: 6px; }

/* ---------- deck shell ---------- */
.deck { position: relative; width: 100vw; height: 100vh; height: 100dvh; }
.slide {
  position: absolute; inset: 0; display: grid; place-items: center;
  padding: clamp(56px, 8vh, 96px) clamp(16px, 6vw, 96px);
  opacity: 0; visibility: hidden; transform: scale(1.02);
  transition: opacity .9s var(--ease), transform 1.1s var(--ease), visibility 0s .9s;
  overflow: hidden;
}
.slide.active { opacity: 1; visibility: visible; transform: none; transition: opacity .9s var(--ease), transform 1.1s var(--ease), visibility 0s; }
.slide.past { transform: scale(.98); }
.inner { width: min(1180px, 100%); position: relative; }

/* Reveal: [data-step=n] shows once the slide reaches step n */
[data-step] { opacity: 0; transform: translateY(18px); filter: blur(6px); transition: opacity .9s var(--ease), transform .9s var(--ease), filter .9s var(--ease); }
[data-step].on { opacity: 1; transform: none; filter: none; }
[data-stagger] > * { opacity: 0; transform: translateY(14px); transition: opacity .8s var(--ease), transform .8s var(--ease); }
[data-stagger].on > * { opacity: 1; transform: none; }
[data-stagger].on > *:nth-child(2) { transition-delay: .12s; }
[data-stagger].on > *:nth-child(3) { transition-delay: .24s; }

.eyebrow { font-size: 13px; letter-spacing: .22em; text-transform: uppercase; color: var(--soft); }
h1, h2 { font-family: var(--display); font-weight: 300; letter-spacing: -0.035em; line-height: 1.02; }
h1 { font-size: clamp(44px, 8.4vw, 124px); }
h2 { font-size: clamp(36px, 5.6vw, 84px); }
.grad { background: linear-gradient(100deg, var(--cobalt-hi) 0%, #a9b6ff 45%, var(--mango) 100%); -webkit-background-clip: text; background-clip: text; color: transparent; }
.lede { font-size: clamp(17px, 1.6vw, 22px); line-height: 1.5; color: var(--soft); max-width: 40ch; }

/* chrome */
.progress { position: fixed; left: 0; top: 0; height: 2px; background: linear-gradient(90deg, var(--cobalt), var(--mango)); width: 0; transition: width .8s var(--ease); z-index: 10; }
.brand { position: fixed; left: clamp(16px, 3vw, 32px); top: 22px; display: flex; align-items: center; gap: 10px; font-family: var(--display); font-size: 15px; letter-spacing: -0.01em; color: var(--soft); z-index: 10; opacity: 0; transition: opacity .8s; }
.brand.show { opacity: 1; }
.brand svg { width: 18px; height: 18px; }
.hud { position: fixed; right: clamp(16px, 3vw, 32px); bottom: 20px; display: flex; align-items: center; gap: 6px; z-index: 10; font-size: 13px; color: var(--soft); font-variant-numeric: tabular-nums; }
.hud button { width: 34px; height: 34px; border-radius: 50%; display: grid; place-items: center; border: 1px solid var(--line); transition: background .3s, border-color .3s; }
.hud button:hover { background: rgba(255,255,255,.06); border-color: rgba(255,255,255,.2); }
.hud .count { padding: 0 8px; }
.hint { position: fixed; left: 50%; bottom: 24px; transform: translateX(-50%); font-size: 12px; letter-spacing: .14em; text-transform: uppercase; color: var(--faint); z-index: 10; transition: opacity .6s; }

/* ---------- lens mark ---------- */
.mark { position: relative; width: var(--s, 120px); height: var(--s, 120px); }
.mark .half { position: absolute; top: 0; width: 50%; height: 100%; transition: transform 1.4s var(--ease), opacity 1s; }
.mark .half svg { width: 100%; height: 100%; overflow: visible; }
.mark .l { left: 0; } .mark .r { right: 0; }
.mark.split .l { transform: translateX(-60%); opacity: 0; }
.mark.split .r { transform: translateX(60%); opacity: 0; }
.mark .glow { position: absolute; inset: -60%; border-radius: 50%; background: radial-gradient(closest-side, rgba(46,70,232,.35), rgba(242,163,27,.10) 60%, transparent 75%); opacity: 0; transition: opacity 2s var(--ease); pointer-events: none; }
.mark:not(.split) .glow { opacity: 1; animation: breathe 6s ease-in-out infinite; }
@keyframes breathe { 50% { transform: scale(1.08); opacity: .75; } }

/* ---------- shared: cards, source tags ---------- */
.card { position: relative; padding: 24px 24px 26px; border-radius: 22px; border: 1px solid var(--line); background: linear-gradient(180deg, rgba(255,255,255,.045), rgba(255,255,255,.012)); }
.card .k { font-size: 12px; letter-spacing: .18em; text-transform: uppercase; color: var(--cobalt-hi); margin-bottom: 12px; display: flex; align-items: center; gap: 8px; }
.card .k::before { content: ""; width: 6px; height: 6px; border-radius: 50%; background: currentColor; box-shadow: 0 0 12px currentColor; }
.card.warn .k { color: var(--mango); }
.card p { color: var(--soft); font-size: 15px; line-height: 1.5; }
.tags { display: flex; flex-wrap: wrap; align-items: center; gap: 6px 18px; }
.src { display: inline-flex; align-items: center; gap: 7px; font-size: 11.5px; letter-spacing: .04em; color: #7d83a3; }
.src::before { content: ""; flex: none; width: 6px; height: 6px; border-radius: 50%; background: var(--dot); }
.src.data { --dot: var(--green); }
.src.build { --dot: var(--cobalt-hi); }
.src.bench { --dot: var(--mango); }
.src.assume { --dot: var(--soft); }

/* ---------- shared: cost tooltips (hover and keyboard focus) ---------- */
.cost { position: relative; cursor: help; border-bottom: 1px dotted rgba(244,246,251,.35); }
.cost .tip {
  position: absolute; left: 50%; bottom: calc(100% + 12px); z-index: 20;
  width: max-content; max-width: min(380px, 80vw); padding: 14px 16px; border-radius: 14px;
  background: #0f1230; border: 1px solid rgba(111,130,255,.35); box-shadow: 0 20px 60px -20px rgba(0,0,0,.8);
  color: var(--text); font: 400 13.5px/1.55 var(--sans); letter-spacing: 0; text-align: left; text-transform: none; white-space: normal;
  opacity: 0; visibility: hidden; pointer-events: none; transform: translate(-50%, 6px);
  transition: opacity .25s, transform .25s, visibility 0s .25s;
}
.cost .tip b { display: block; color: var(--cobalt-hi); font-weight: 500; margin-bottom: 4px; }
.cost .tip .f { display: block; font-family: var(--mono); font-size: 12.5px; color: #c9cff0; margin: 4px 0 8px; }
.cost:hover .tip, .cost:focus .tip, .cost:focus-within .tip { opacity: 1; visibility: visible; transform: translate(-50%, 0); transition: opacity .25s, transform .25s, visibility 0s; }
.cost.tip-left .tip { left: auto; right: 0; transform: translateY(6px); }
.cost.tip-left:hover .tip, .cost.tip-left:focus .tip, .cost.tip-left:focus-within .tip { transform: none; }
.cost.tip-down .tip { bottom: auto; top: calc(100% + 12px); }

/* ---------- slide 1: problem ---------- */

/* ---------- slide 2: solution ---------- */

/* ---------- slide 3: scope ---------- */

/* ---------- slide 4: architecture ---------- */

/* ---------- slide 5: technical solution ---------- */

/* ---------- slide 6: profitability ---------- */

/* ---------- responsive ---------- */
@media (max-width: 900px) {
  html, body { overflow: auto; }
  .slide { place-items: start center; overflow-y: auto; padding-top: 72px; padding-bottom: 80px; }
  .beats, .pillars, .outcomes, .cols, .out-grid, .how, .profit { grid-template-columns: 1fr !important; }
  .hint { display: none; }
}
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { animation: none !important; transition-duration: .01ms !important; transition-delay: 0s !important; }
}
</style>
</head>
<body>
<div class="progress" id="progress"></div>

<div class="brand" id="brand" aria-hidden="true">
  <svg viewBox="0 0 32 32"><path d="M15.2 2.5A18.2 18.2 0 0 0 15.2 29.5Z" fill="#2e46e8"/><path d="M16.8 2.5A18.2 18.2 0 0 1 16.8 29.5Z" fill="#f2a31b"/></svg>
  LedgerLens
</div>

<main class="deck" id="deck">

  <!-- 1 · The problem -->
  <section class="slide s-problem" data-steps="0" aria-label="The problem">
    <div class="inner"><h2>The problem</h2></div>
  </section>

  <!-- 2 · The solution -->
  <section class="slide s-solution" data-steps="0" aria-label="The solution">
    <div class="inner"><h2>The solution</h2></div>
  </section>

  <!-- 3 · Technical scope -->
  <section class="slide s-scope" data-steps="0" aria-label="Technical scope">
    <div class="inner"><h2>Technical scope</h2></div>
  </section>

  <!-- 4 · Architecture -->
  <section class="slide s-arch" data-steps="0" aria-label="Architecture">
    <div class="inner"><h2>Architecture</h2></div>
  </section>

  <!-- 5 · Technical solution -->
  <section class="slide s-how" data-steps="0" aria-label="Technical solution">
    <div class="inner"><h2>Technical solution</h2></div>
  </section>

  <!-- 6 · Profitability -->
  <section class="slide s-profit" data-steps="0" aria-label="Profitability">
    <div class="inner"><h2>Profitability</h2></div>
  </section>

</main>

<div class="hint" id="hint">Press → to begin</div>
<nav class="hud" aria-label="Slide navigation">
  <button id="prev" aria-label="Previous"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><path d="m15 18-6-6 6-6"/></svg></button>
  <span class="count" id="count">1 / 6</span>
  <button id="next" aria-label="Next"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><path d="m9 18 6-6-6-6"/></svg></button>
  <button id="fs" aria-label="Full screen"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/></svg></button>
</nav>

<script>
(() => {
  const slides = [...document.querySelectorAll('.slide')];
  const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const hooks = [];
  let cur = 0, step = 0;

  // The HTML holds each number's final text; countUp animates from 0 to it.
  function countUp(el) {
    const target = parseFloat(el.dataset.count), fmt = el.dataset.format || 'int';
    const show = v => fmt === 'usd2' ? '$' + v.toFixed(2)
      : fmt === 'usd3' ? '$' + v.toFixed(3)
      : fmt === 'pct' ? v.toFixed(1) + '%'
      : fmt === 'dec' ? (v < 0 ? '−' : '') + Math.abs(v).toFixed(1)
      : Math.round(v).toLocaleString('en-US');
    if (reduce) { el.textContent = show(target); return; }
    const t0 = performance.now(), dur = 1600;
    const tick = t => {
      const p = Math.min(1, (t - t0) / dur), e = 1 - Math.pow(1 - p, 4);
      el.textContent = show(target * e);
      if (p < 1) requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  }

  // slide hooks

  function render() {
    slides.forEach((s, i) => {
      s.classList.toggle('active', i === cur);
      s.classList.toggle('past', i < cur);
      s.setAttribute('aria-hidden', i !== cur);
      if (i === cur) s.dataset.at = step;
    });
    const s = slides[cur];
    s.querySelectorAll('[data-step]').forEach(el => el.classList.toggle('on', +el.dataset.step <= step));

    // Numbers count up the first time their step shows; leaving the slide resets them
    slides.forEach((sl, i) => sl.querySelectorAll('[data-count]').forEach(el => {
      const holder = el.closest('[data-step]');
      const shown = i === cur && (!holder || +holder.dataset.step <= step);
      if (shown && !el.dataset.counted) { el.dataset.counted = '1'; countUp(el); }
      if (!shown) delete el.dataset.counted;
    }));
    hooks.forEach(h => h(s, step));

    const total = slides.reduce((n, sl) => n + 1 + +sl.dataset.steps, 0);
    const done = slides.slice(0, cur).reduce((n, sl) => n + 1 + +sl.dataset.steps, 0) + step + 1;
    document.getElementById('progress').style.width = (done / total * 100) + '%';
    document.getElementById('count').textContent = (cur + 1) + ' / ' + slides.length;
    document.getElementById('brand').classList.toggle('show', !s.classList.contains('s-solution'));
    document.getElementById('hint').style.opacity = cur === 0 && step === 0 ? 1 : 0;
  }

  function next() {
    if (step < +slides[cur].dataset.steps) step++;
    else if (cur < slides.length - 1) { cur++; step = 0; }
    render();
  }
  function prev() {
    if (step > 0) step--;
    else if (cur > 0) { cur--; step = +slides[cur].dataset.steps; }
    render();
  }
  function go(i) { cur = Math.max(0, Math.min(slides.length - 1, i)); step = 0; render(); }

  addEventListener('keydown', e => {
    if (['ArrowRight', 'ArrowDown', 'PageDown', ' ', 'Enter'].includes(e.key)) { e.preventDefault(); next(); }
    else if (['ArrowLeft', 'ArrowUp', 'PageUp', 'Backspace'].includes(e.key)) { e.preventDefault(); prev(); }
    else if (e.key === 'Home') go(0);
    else if (e.key === 'End') go(slides.length - 1);
    else if (/^[1-6]$/.test(e.key)) go(+e.key - 1);
    else if (e.key === 'f') toggleFs();
  });
  document.getElementById('next').onclick = next;
  document.getElementById('prev').onclick = prev;
  function toggleFs() { document.fullscreenElement ? document.exitFullscreen() : document.documentElement.requestFullscreen?.(); }
  document.getElementById('fs').onclick = toggleFs;

  // A click on the slide advances, except on tooltips, sources and links; swipe on touch
  document.getElementById('deck').addEventListener('click', e => { if (!e.target.closest('a,button,.cost,details,summary')) next(); });
  let tx = null;
  addEventListener('touchstart', e => { tx = e.touches[0].clientX; }, { passive: true });
  addEventListener('touchend', e => {
    if (tx === null) return;
    const dx = e.changedTouches[0].clientX - tx; tx = null;
    if (Math.abs(dx) > 50) dx < 0 ? next() : prev();
  });
  let wheelLock = 0;
  addEventListener('wheel', e => {
    if (innerWidth <= 900 || Date.now() < wheelLock || Math.abs(e.deltaY) < 20) return;
    wheelLock = Date.now() + 800; e.deltaY > 0 ? next() : prev();
  }, { passive: true });

  // Deep link: #3 opens slide 3, #3.2 opens it at step 2
  const m = location.hash.match(/^#(\d)(?:\.(\d))?$/);
  if (m) {
    cur = Math.max(0, Math.min(slides.length - 1, +m[1] - 1));
    step = Math.min(+(m[2] || 0), +slides[cur].dataset.steps);
  }
  render();
})();
</script>
</body>
</html>
```

The Enter key advances the deck. On a focused `.cost`, the tooltip is already showing, so advancing is fine.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/unit/final_deck -q`
Expected: `10 passed`.

- [ ] **Step 6: Commit**

```bash
git add docs/superpowers/specs/2026-10-04-final-presentation-design.md docs/superpowers/plans/2026-10-04-final-presentation.md tests/unit/final_deck/__init__.py tests/unit/final_deck/deck_html.py tests/unit/final_deck/test_final_deck.py docs/hackathon_final_doc/ledgerlens-final.html
git commit -m "feat(pitch): final deck shell with six slide stubs

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Slides 1–3 (problem, solution, scope)

**Files:**
- Modify: `docs/hackathon_final_doc/ledgerlens-final.html`. Replace the stub sections `s-problem`, `s-solution` and `s-scope`. Insert CSS under the markers for slides 1, 2 and 3. Add a hook at `// slide hooks`.
- Modify: `tests/unit/final_deck/test_final_deck.py` (append)

**Interfaces:**
- Consumes from Task 1: `.card`, `.k`, `.tags`, `.src.*`, `data-count` (formats `int`, `pct`), `hooks`, the mark CSS, and `slide(deck, name)` in the tests.
- Produces: `#heroMark` on slide 2.

- [ ] **Step 1: Append the failing tests**

```python
# ---------- Task 2: slides 1-3 ----------

def test_problem_slide_numbers_match_the_dataset(deck):
    s = slide(deck, "s-problem")
    text = s.text()
    for value in ["35.0%", "6,661", "4,663", "12,297", "18.3%", "90.6%", "50.4%", "15.4 days",
                  "288", "−69.9", "2.91 / 4", "70.1%"]:
        assert value in text, value
    assert s.find_all(lambda e: {"src", "data"} <= e.classes())
    assert s.attrs["data-steps"] == "3"


def test_agent_hours_follow_from_calls_and_handle_time():
    assert round(4663 * 3.7 / 60) == 288


def test_reason_bars_are_scaled_to_the_largest_reason(deck):
    shares = {"Transactional": 35.0, "Product": 22.0, "Complaint": 17.1, "Technical": 15.0,
              "Commercial": 8.0, "Retention": 3.0}
    bars = slide(deck, "s-problem").find_all(lambda e: "bar" in e.classes())
    assert len(bars) == 6
    for bar in bars:
        name = next(n for n in shares if n in bar.text())
        width = float(re.search(r"--w:([\d.]+)%", bar.attrs["style"]).group(1))
        assert width == pytest.approx(shares[name] / 35.0 * 100, abs=0.06)


def test_solution_slide_has_three_pillars_and_outcomes(deck):
    s = slide(deck, "s-solution")
    text = s.text()
    for value in ["Hyperpersonalized", "Intent", "Fraud check", "Lower cost per contact",
                  "Higher first-contact resolution", "Higher satisfaction",
                  "Credit cards today. Any use case the bank wants tomorrow."]:
        assert value in text, value
    assert s.find_all(lambda e: e.attrs.get("id") == "heroMark")
    assert s.find_all(lambda e: {"src", "assume"} <= e.classes())


def test_scope_slide_lists_everything_in_and_out_of_scope(deck):
    text = slide(deck, "s-scope").text()
    for value in ["Prompt engineering", "Tool use", "Short-term memory", "Context window truncation",
                  "Context window compaction (summarization)", "Guardrails", "Model evaluation",
                  "Scalable, highly available services", "Security", "Serverless tools",
                  "Infrastructure as code", "Observability", "Build and ship to production",
                  "Data engineering", "Data science / ML", "Data analysis", "0.46"]:
        assert value in text, value
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/unit/final_deck -q`
Expected: the 4 slide tests FAIL, for example `AssertionError: 35.0%`. `test_agent_hours_follow_from_calls_and_handle_time` passes.

- [ ] **Step 3: Replace the `s-problem` stub section**

```html
  <!-- 1 · The problem -->
  <section class="slide s-problem" data-steps="3" aria-label="The problem">
    <div class="inner">
      <div data-step="0">
        <div class="eyebrow">The problem</div>
        <h2>A bank has to be <span class="grad">profitable.</span><br>Its contact center is one of its biggest costs.</h2>
      </div>
      <div class="beats">
        <div class="card beat" data-step="1">
          <div class="k">#1 reason to contact the bank</div>
          <div class="big"><span data-count="35" data-format="pct">35.0%</span></div>
          <p>are questions about a transaction: what a charge is, why it was declined.</p>
          <div class="bars" aria-label="Contacts by reason">
            <div class="bar hi" style="--w:100%"><span>Transactional</span><b>35.0%</b></div>
            <div class="bar" style="--w:62.9%"><span>Product</span><b>22.0%</b></div>
            <div class="bar" style="--w:48.9%"><span>Complaint</span><b>17.1%</b></div>
            <div class="bar" style="--w:42.9%"><span>Technical</span><b>15.0%</b></div>
            <div class="bar" style="--w:22.9%"><span>Commercial</span><b>8.0%</b></div>
            <div class="bar" style="--w:8.6%"><span>Retention</span><b>3.0%</b></div>
          </div>
          <p class="foot"><b data-count="6661">6,661</b> a month · <b data-count="4663">4,663</b> of them inbound calls</p>
        </div>
        <div class="card beat" data-step="2">
          <div class="k">#1 complaint</div>
          <div class="big"><span data-count="12297">12,297</span></div>
          <p>charges the customer doesn't recognize: 18.3% of all complaints, 90.6% of transaction complaints.</p>
          <ul class="facts">
            <li><b>50.4%</b> came in through the call center</li>
            <li><b>15.4 days</b> on average to resolve one</li>
          </ul>
        </div>
        <div class="card beat warn" data-step="3">
          <div class="k">Today, people answer every one</div>
          <div class="big"><span data-count="288">288</span><small> agent-hours a month</small></div>
          <p>4,663 inbound transactional calls × 3.7 min of handling. And customers still leave unhappy:</p>
          <ul class="facts">
            <li><b>−69.9</b> NPS</li>
            <li><b>2.91 / 4</b> CSAT</li>
            <li><b>70.1%</b> first-contact resolution</li>
          </ul>
        </div>
      </div>
      <div class="tags" data-step="1">
        <span class="src data">Source: provided contact-center dataset · 686,296 contacts, Jun 2023 to Jun 2026 (35 full months)</span>
        <span class="src assume">The dataset appears synthetic: its NPS answers range only from 2 to 7</span>
      </div>
    </div>
  </section>
```

- [ ] **Step 4: Replace the `s-solution` stub section**

```html
  <!-- 2 · The solution -->
  <section class="slide s-solution" data-steps="2" aria-label="The solution">
    <div class="inner">
      <div class="hero" data-step="0">
        <div class="mark split" id="heroMark" style="--s: clamp(54px, 6vw, 84px)">
          <div class="glow"></div>
          <div class="half l"><svg viewBox="0 0 16 32"><path d="M15.2 2.5A18.2 18.2 0 0 0 15.2 29.5Z" fill="#2e46e8"/></svg></div>
          <div class="half r"><svg viewBox="16 0 16 32"><path d="M16.8 2.5A18.2 18.2 0 0 1 16.8 29.5Z" fill="#f2a31b"/></svg></div>
        </div>
        <div class="wordmark">LedgerLens</div>
        <h1>Your customer's <span class="grad">right hand.</span></h1>
        <p class="lede">Not another chatbot. A partner who already knows them, for whatever they need from the bank.</p>
      </div>
      <div class="pillars" data-stagger data-step="1">
        <div class="pillar">
          <div class="k">Hyperpersonalized</div>
          <h3>Knows them before hello.</h3>
          <p>Their cards, charges, open cases, previous contacts and app events are loaded before the first word.</p>
        </div>
        <div class="pillar">
          <div class="k">Intent</div>
          <h3>Knows why they're here.</h3>
          <p>It anticipates why the customer is reaching out, so the first message already answers it.</p>
        </div>
        <div class="pillar">
          <div class="k">Fraud check</div>
          <h3>Has their back.</h3>
          <p>It checks an unrecognized charge, then blocks the card and opens the claim, only after the customer taps Yes.</p>
        </div>
      </div>
      <div class="outcomes" data-step="2">
        <div class="outcome"><b>Lower cost per contact</b><span>today: 3.7 min of a person per contact</span></div>
        <div class="outcome"><b>Higher first-contact resolution</b><span>today: 70.1%</span></div>
        <div class="outcome"><b>Higher satisfaction</b><span>today: CSAT 2.91 / 4 · NPS −69.9</span></div>
      </div>
      <div class="tags" data-step="2">
        <span class="src data">Today's values: provided contact-center dataset</span>
        <span class="src assume">The outcomes are goals, not measured results</span>
        <span class="line">Credit cards today. Any use case the bank wants tomorrow.</span>
      </div>
    </div>
  </section>
```

- [ ] **Step 5: Replace the `s-scope` stub section**

```html
  <!-- 3 · Technical scope -->
  <section class="slide s-scope" data-steps="3" aria-label="Technical scope">
    <div class="inner">
      <div data-step="0">
        <div class="eyebrow">Technical scope</div>
        <h2>We focused on <span class="grad">two things.</span></h2>
      </div>
      <div class="cols">
        <div class="card" data-step="1">
          <div class="k">Agentic AI</div>
          <ul class="chips">
            <li>Prompt engineering</li><li>Tool use</li><li>Short-term memory</li>
            <li>Context window truncation</li><li>Context window compaction (summarization)</li>
            <li>Guardrails</li><li>Model evaluation</li>
          </ul>
        </div>
        <div class="card" data-step="2">
          <div class="k">AI cloud architecture &amp; production</div>
          <ul class="chips">
            <li>Scalable, highly available services</li><li>Security</li><li>Serverless tools</li>
            <li>Infrastructure as code</li><li>Observability</li><li>Build and ship to production</li>
          </ul>
        </div>
      </div>
      <div class="out" data-step="3">
        <div class="out-h">Scoped out, on purpose</div>
        <div class="out-grid">
          <div><b>Data engineering</b><span>Light cleaning and an ingest pipeline into the database. We know the data has quality gaps and took it as is.</span></div>
          <div><b>Data science / ML</b><span>The intent and fraud models are heuristic mocks. They serve as agent tools and show where the product scales.</span></div>
          <div><b>Data analysis</b><span>Done, not shipped. A full EDA asked whether fraud could be flagged minutes after an approved charge. No variable related to the fraud label (test ROC-AUC <b>0.46</b>, PR-AUC 0.0008 vs a 0.0009 base rate), so the fraud tool is a mock.</span></div>
        </div>
        <span class="src build">From the LedgerLens build · EDA in the sibling repo testing-AI-driven-fraud-detection-model</span>
      </div>
    </div>
  </section>
```

- [ ] **Step 6: Insert the CSS under the slide 1, 2 and 3 markers**

Under `/* ---------- slide 1: problem ---------- */`:

```css
.s-problem .inner { display: grid; gap: clamp(18px, 3vh, 32px); }
.s-problem h2 { font-size: clamp(32px, 4.4vw, 64px); max-width: 22ch; margin-top: 12px; }
.beats { display: grid; grid-template-columns: repeat(3, 1fr); gap: clamp(14px, 2vw, 26px); }
.big { font-family: var(--display); font-weight: 300; font-size: clamp(38px, 3.8vw, 56px); letter-spacing: -0.03em; font-variant-numeric: tabular-nums; margin-bottom: 8px; }
.big small { font-family: var(--sans); font-size: 15px; color: var(--soft); letter-spacing: 0; }
.bars { display: grid; gap: 6px; margin: 16px 0 14px; }
.bar { position: relative; display: flex; justify-content: space-between; font-size: 12.5px; color: var(--soft); padding: 4px 8px; }
.bar::before { content: ""; position: absolute; inset: 0; width: var(--w); border-radius: 6px; background: rgba(255,255,255,.06); transform-origin: left; transform: scaleX(0); transition: transform 1.2s var(--ease) .3s; }
.on .bar::before { transform: scaleX(1); }
.bar.hi { color: var(--text); }
.bar.hi::before { background: linear-gradient(90deg, rgba(46,70,232,.55), rgba(46,70,232,.2)); }
.bar span, .bar b { position: relative; font-weight: 400; }
.facts { list-style: none; display: grid; gap: 8px; margin-top: 14px; font-size: 14.5px; color: var(--soft); }
.facts b { color: var(--text); font-weight: 500; margin-right: 4px; }
.foot { margin-top: 4px; font-size: 14px; }
.foot b { color: var(--text); font-weight: 500; }
```

Under `/* ---------- slide 2: solution ---------- */`:

```css
.s-solution .inner { display: grid; justify-items: center; text-align: center; gap: clamp(14px, 2.6vh, 28px); }
.s-solution .hero { display: grid; justify-items: center; gap: 14px; }
.s-solution h1 { font-size: clamp(36px, 5vw, 72px); }
.s-solution .lede { max-width: 56ch; margin-inline: auto; }
.wordmark { font-family: var(--display); font-weight: 400; font-size: clamp(18px, 2vw, 24px); letter-spacing: -0.01em; color: var(--soft); }
.pillars { display: grid; grid-template-columns: repeat(3, 1fr); gap: clamp(14px, 2vw, 28px); text-align: left; width: min(1080px, 100%); }
.pillar { padding: 24px 24px 26px; border-radius: 22px; background: linear-gradient(180deg, rgba(255,255,255,.045), rgba(255,255,255,.015)); border: 1px solid var(--line); }
.pillar .k { font-size: 12px; letter-spacing: .18em; text-transform: uppercase; color: var(--cobalt-hi); margin-bottom: 14px; display: flex; align-items: center; gap: 8px; }
.pillar .k::before { content: ""; width: 6px; height: 6px; border-radius: 50%; background: currentColor; box-shadow: 0 0 12px currentColor; }
.pillar:nth-child(3) .k { color: var(--mango); }
.pillar h3 { font-family: var(--display); font-weight: 400; font-size: clamp(22px, 2.1vw, 30px); letter-spacing: -0.02em; line-height: 1.1; margin-bottom: 10px; }
.pillar p { color: var(--soft); line-height: 1.5; font-size: 15.5px; }
.outcomes { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; width: min(1080px, 100%); }
.outcome { display: grid; gap: 4px; padding: 14px 18px; border-radius: 16px; border: 1px solid rgba(111,130,255,.28); background: rgba(46,70,232,.08); text-align: left; }
.outcome b { font-weight: 500; font-size: 16px; }
.outcome span { font-size: 13.5px; color: var(--soft); }
.s-solution .tags { justify-content: center; }
.s-solution .line { font-family: var(--display); font-size: clamp(16px, 1.5vw, 20px); color: var(--text); }
```

Under `/* ---------- slide 3: scope ---------- */`:

```css
.s-scope .inner { display: grid; gap: clamp(16px, 2.6vh, 28px); }
.s-scope h2 { margin-top: 12px; }
.cols { display: grid; grid-template-columns: 1fr 1fr; gap: clamp(14px, 2vw, 26px); }
.chips { list-style: none; display: flex; flex-wrap: wrap; gap: 8px; }
.chips li { padding: 8px 14px; border-radius: 99px; border: 1px solid rgba(111,130,255,.3); background: rgba(46,70,232,.1); font-size: 15px; }
.out { display: grid; gap: 12px; padding: 18px 22px; border-radius: 20px; border: 1.5px dashed rgba(242,163,27,.4); }
.out-h { font-size: 12px; letter-spacing: .18em; text-transform: uppercase; color: var(--mango); }
.out-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 18px; }
.out-grid b { display: block; font-weight: 500; margin-bottom: 4px; }
.out-grid span { color: var(--soft); font-size: 14px; line-height: 1.5; }
.out-grid span b { display: inline; color: var(--text); }
```

- [ ] **Step 7: Add the lens hook at `// slide hooks`**

```js
  // Solution slide: the lens closes as the slide arrives
  hooks.push(s => document.getElementById('heroMark').classList.toggle('split', !s.classList.contains('s-solution')));
```

- [ ] **Step 8: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/unit/final_deck -q`
Expected: `15 passed`.

- [ ] **Step 9: Commit**

```bash
git add docs/hackathon_final_doc/ledgerlens-final.html tests/unit/final_deck/test_final_deck.py
git commit -m "feat(pitch): problem, solution and scope slides

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Slide 4 (architecture SVG)

**Files:**
- Modify: `docs/hackathon_final_doc/ledgerlens-final.html`. Replace the `s-arch` stub section, and insert CSS under the slide 4 marker.
- Modify: `tests/unit/final_deck/test_final_deck.py` (append)

**Interfaces:**
- Produces:
  - `<svg id="archSvg">`, whose nodes are `<g class="node" data-node="<name>">`, with the names in `ARCH_NODES` below
  - the arrowhead marker `#ah` inside `<defs>`
  - the CSS classes `.arch`, `.arch.focusing` and `.node.focus`, which Task 4 uses to highlight nodes

- [ ] **Step 1: Append the failing tests**

```python
# ---------- Task 3: architecture ----------

ARCH_NODES = {"customer", "amplify", "cognito", "pretoken", "agent", "memory", "identity", "bedrock",
              "guardrail", "observability", "gateway", "tools", "dsql", "handoff", "sfn", "codebuild",
              "s3", "feedback"}


def arch_svg(deck):
    return deck.find_all(lambda e: e.tag == "svg" and e.attrs.get("id") == "archSvg")[0]


def test_architecture_has_every_component(deck):
    svg = arch_svg(deck)
    nodes = {e.attrs["data-node"] for e in svg.find_all(lambda e: "data-node" in e.attrs)}
    assert nodes == ARCH_NODES
    assert svg in slide(deck, "s-arch").find_all(lambda e: e.tag == "svg")


def test_architecture_lanes_reveal_left_to_right(deck):
    lanes = arch_svg(deck).find_all(lambda e: "lane" in e.classes())
    assert [lane.attrs["data-step"] for lane in lanes] == ["0", "1", "2", "3"]


def test_architecture_names_the_key_facts(deck):
    text = slide(deck, "s-arch").text()
    for value in ["OIDC · Auth Code + PKCE", "adds customer_id", "prompt v10", "DeepSeek v3.2",
                  "Cedar policy", "VPC · no public IP", "VPC endpoint · IAM auth",
                  "outside the VPC · no DB", "API Gateway → Lambda → DynamoDB", "AWS CDK"]:
        assert value in text, value
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/unit/final_deck -q -k architecture`
Expected: FAIL with `IndexError: list index out of range` in `arch_svg`.

- [ ] **Step 3: Replace the `s-arch` stub section**

```html
  <!-- 4 · Architecture (redrawn from docs/architecture-diagram/ledgerlens-architecture.drawio) -->
  <section class="slide s-arch" data-steps="3" aria-label="Architecture">
    <div class="inner">
      <div data-step="0">
        <div class="eyebrow">Architecture</div>
        <h2>Serverless, secure, <span class="grad">in production on AWS.</span></h2>
      </div>
      <div class="arch">
        <svg id="archSvg" viewBox="0 0 1200 540" role="img" aria-label="LedgerLens architecture on AWS">
          <defs>
            <marker id="ah" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0 10 5 0 10z" fill="#6f82ff"/></marker>
          </defs>

          <g class="lane" data-step="0">
            <text class="lane-t" x="135" y="24">CHANNEL</text>
            <g class="node" data-node="customer"><rect x="20" y="44" width="230" height="50" rx="12"/><text x="135" y="74">Customer</text></g>
            <g class="node" data-node="amplify"><rect x="20" y="130" width="230" height="64" rx="12"/><text x="135" y="157">React web chat<tspan class="d" x="135" dy="20">Amplify Hosting</tspan></text></g>
            <g class="node" data-node="cognito"><rect x="20" y="230" width="230" height="64" rx="12"/><text x="135" y="257">Amazon Cognito<tspan class="d" x="135" dy="20">OIDC · Auth Code + PKCE</tspan></text></g>
            <g class="node" data-node="pretoken"><rect x="20" y="330" width="230" height="64" rx="12"/><text x="135" y="357">Pre-Token V3 Lambda<tspan class="d" x="135" dy="20">adds customer_id</tspan></text></g>
            <path class="edge" d="M135 94 V128" marker-end="url(#ah)"/>
            <path class="edge" d="M135 194 V228" marker-end="url(#ah)"/>
            <path class="edge" d="M135 294 V328" marker-end="url(#ah)"/>
          </g>

          <g class="lane" data-step="1">
            <text class="lane-t" x="440" y="24">AGENT ENGINE</text>
            <rect class="box" x="290" y="40" width="300" height="340" rx="16"/>
            <text class="box-t" x="306" y="60">AgentCore Runtime</text>
            <g class="node ai" data-node="agent"><rect x="310" y="72" width="260" height="64" rx="12"/><text x="440" y="99">Strands agent<tspan class="d" x="440" dy="20">prompt v10 · Yes/No confirmation hook</tspan></text></g>
            <g class="node ai" data-node="memory"><rect x="310" y="152" width="125" height="60" rx="12"/><text x="372" y="177">Memory<tspan class="d" x="372" dy="19">short-term</tspan></text></g>
            <g class="node ai" data-node="identity"><rect x="445" y="152" width="125" height="60" rx="12"/><text x="507" y="177">Identity<tspan class="d" x="507" dy="19">token vault</tspan></text></g>
            <g class="node ai" data-node="bedrock"><rect x="310" y="228" width="260" height="64" rx="12"/><text x="440" y="255">Amazon Bedrock<tspan class="d" x="440" dy="20">DeepSeek v3.2 · Haiku 4.5 · Sonnet 4.5</tspan></text></g>
            <g class="node ai" data-node="guardrail"><rect x="310" y="308" width="260" height="52" rx="12"/><text x="440" y="339">Bedrock Guardrail</text></g>
            <g class="node" data-node="observability"><rect x="290" y="400" width="300" height="52" rx="12"/><text x="440" y="431">CloudWatch observability</text></g>
            <path class="edge" d="M250 162 H270 V104 H308" marker-end="url(#ah)"/>
            <text class="el" x="262" y="96">invoke + JWT</text>
          </g>

          <g class="lane" data-step="2">
            <text class="lane-t" x="770" y="24">TOOLS</text>
            <g class="node ai" data-node="gateway"><rect x="630" y="72" width="280" height="64" rx="12"/><text x="770" y="99">AgentCore Gateway (MCP)<tspan class="d" x="770" dy="20">Cedar policy approves each call</tspan></text></g>
            <rect class="box vpc" x="630" y="160" width="280" height="214" rx="16"/>
            <text class="box-t vpc-t" x="646" y="180">VPC · no public IP</text>
            <g class="node" data-node="tools"><rect x="650" y="192" width="240" height="64" rx="12"/><text x="770" y="219">8 tool Lambdas<tspan class="d" x="770" dy="20">cards · charges · fraud · intent</tspan></text></g>
            <g class="node" data-node="dsql"><rect x="650" y="290" width="240" height="64" rx="12"/><text x="770" y="317">Aurora DSQL<tspan class="d" x="770" dy="20">VPC endpoint · IAM auth</tspan></text></g>
            <g class="node human" data-node="handoff"><rect x="630" y="394" width="280" height="64" rx="12"/><text x="770" y="421">human_agent_hand_off<tspan class="d" x="770" dy="20">outside the VPC · no DB</tspan></text></g>
            <path class="edge" d="M570 104 H628" marker-end="url(#ah)"/>
            <text class="el" x="580" y="96">MCP</text>
            <path class="edge" d="M770 136 V190" marker-end="url(#ah)"/>
            <path class="edge" d="M770 256 V288" marker-end="url(#ah)"/>
            <path class="edge" d="M910 104 H924 V426 H912" marker-end="url(#ah)"/>
          </g>

          <g class="lane" data-step="3">
            <text class="lane-t" x="1065" y="24">DATA &amp; FEEDBACK</text>
            <g class="node" data-node="sfn"><rect x="950" y="72" width="230" height="48" rx="12"/><text x="1065" y="101">Step Functions</text></g>
            <g class="node" data-node="codebuild"><rect x="950" y="140" width="230" height="64" rx="12"/><text x="1065" y="167">CodeBuild<tspan class="d" x="1065" dy="20">ingest · transform · curate · load</tspan></text></g>
            <g class="node" data-node="s3"><rect x="950" y="224" width="230" height="48" rx="12"/><text x="1065" y="253">Amazon S3</text></g>
            <g class="node" data-node="feedback"><rect x="950" y="394" width="230" height="64" rx="12"/><text x="1065" y="421">Feedback API<tspan class="d" x="1065" dy="20">API Gateway → Lambda → DynamoDB</tspan></text></g>
            <path class="edge" d="M1065 120 V138" marker-end="url(#ah)"/>
            <path class="edge" d="M1065 204 V222" marker-end="url(#ah)"/>
            <path class="edge" d="M950 248 H936 V322 H892" marker-end="url(#ah)"/>
            <text class="el" x="944" y="290" text-anchor="end">load</text>
            <path class="edge soft" d="M20 162 H8 V500 H1065 V460" marker-end="url(#ah)"/>
            <text class="el" x="600" y="494">thumbs up / down from the chat</text>
          </g>
        </svg>
      </div>
      <div class="tags" data-step="3">
        <span class="line">Everything deployed as code with AWS CDK.</span>
        <span class="src build">From the LedgerLens build · docs/architecture-diagram/ledgerlens-architecture.drawio</span>
      </div>
    </div>
  </section>
```

- [ ] **Step 4: Insert the CSS under `/* ---------- slide 4: architecture ---------- */`**

```css
.s-arch .inner { width: min(1320px, 100%); display: grid; gap: clamp(12px, 2vh, 22px); }
.s-arch h2 { font-size: clamp(30px, 3.6vw, 54px); margin-top: 10px; }
.s-arch .arch svg { width: 100%; height: auto; max-height: calc(100dvh - 300px); display: block; }
.s-arch .line { font-family: var(--display); font-size: clamp(16px, 1.5vw, 20px); }
.arch .node rect { fill: rgba(255,255,255,.04); stroke: rgba(255,255,255,.16); stroke-width: 1.2; transition: fill .5s, stroke .5s; }
.arch .node.ai rect { stroke: rgba(111,130,255,.55); fill: rgba(46,70,232,.12); }
.arch .node.human rect { stroke: rgba(242,163,27,.6); fill: rgba(242,163,27,.08); }
.arch .node { transition: opacity .5s; }
.arch text { fill: var(--text); font-family: var(--sans); font-size: 15px; text-anchor: middle; }
.arch .d { fill: var(--soft); font-size: 12px; }
.arch .lane-t { fill: var(--soft); font-size: 12px; letter-spacing: .18em; }
.arch .box { fill: none; stroke: rgba(111,130,255,.35); stroke-dasharray: 5 5; }
.arch .box.vpc { stroke: rgba(63,191,143,.5); }
.arch .box-t { text-anchor: start; font-size: 12px; fill: var(--cobalt-hi); letter-spacing: .06em; }
.arch .box-t.vpc-t { fill: var(--green); }
.arch .edge { fill: none; stroke: rgba(111,130,255,.6); stroke-width: 1.6; stroke-dasharray: 6 6; animation: flow 1.6s linear infinite; }
.arch .edge.soft { stroke: rgba(154,160,187,.35); }
.arch .el { fill: var(--soft); font-size: 11.5px; text-anchor: start; }
@keyframes flow { to { stroke-dashoffset: -12; } }
.arch.focusing .node { opacity: .28; }
.arch.focusing .node.focus { opacity: 1; }
.arch.focusing .node.focus rect { stroke: var(--cobalt-hi); fill: rgba(46,70,232,.28); }
.arch.focusing .node.human.focus rect { stroke: var(--mango); fill: rgba(242,163,27,.2); }
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/unit/final_deck -q`
Expected: `18 passed`.

- [ ] **Step 6: Commit**

```bash
git add docs/hackathon_final_doc/ledgerlens-final.html tests/unit/final_deck/test_final_deck.py
git commit -m "feat(pitch): animated architecture slide

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Slide 5 (technical solution)

**Files:**
- Modify: `docs/hackathon_final_doc/ledgerlens-final.html`. Replace the `s-how` stub section, insert CSS under the slide 5 marker, and add a hook at `// slide hooks`.
- Modify: `tests/unit/final_deck/test_final_deck.py` (append)

**Interfaces:**
- Consumes from Task 3: `#archSvg`, `[data-node]` names (`ARCH_NODES` in the tests), `#ah` in `<defs>`, and `.arch.focusing` / `.node.focus`.
- Produces: `#archMini`, which receives the clone of `#archSvg` at load. The clone has its `id`, its `<defs>` and all `data-step` attributes stripped, so the page has no duplicate ids and every lane shows.

- [ ] **Step 1: Append the failing tests**

```python
# ---------- Task 4: technical solution ----------

TOOLS = ["get_session_context", "classify_call_type", "list_credit_cards", "list_card_transactions",
         "explain_transaction", "transaction_fraud_detection", "block_credit_card", "open_claim",
         "human_agent_hand_off"]


def test_walkthrough_has_five_steps_that_focus_real_nodes(deck):
    s = slide(deck, "s-how")
    items = s.find_all(lambda e: "data-focus" in e.attrs)
    assert [i.attrs["data-step"] for i in items] == ["0", "1", "2", "3", "4"]
    for item in items:
        assert set(item.attrs["data-focus"].split()) <= ARCH_NODES, item.attrs["data-focus"]


def test_walkthrough_lists_all_nine_tools(deck):
    codes = [c.text() for c in slide(deck, "s-how").find_all(lambda e: e.tag == "code")]
    assert sorted(codes) == sorted(TOOLS)


def test_walkthrough_states_the_cedar_rules_and_the_mocks(deck):
    text = slide(deck, "s-how").text()
    for value in ["OIDC (Authorization Code + PKCE)", "30-message sliding window, active",
                  "summarization, built and switchable by config", "DeepSeek v3.2",
                  "Haiku 4.5 or Sonnet 4.5", "linked customer_id", "that same customer",
                  "the customer confirmed", "Mock models", "Simulated"]:
        assert value in text, value


def test_mini_diagram_is_cloned_not_copied(deck, source):
    mini = deck.find_all(lambda e: e.attrs.get("id") == "archMini")[0]
    assert not [c for c in mini.children if not isinstance(c, str)]
    for call in ["cloneNode(true)", "removeAttribute('id')", "querySelector('defs')?.remove()",
                 "removeAttribute('data-step')"]:
        assert call in source, call
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/unit/final_deck -q -k "walkthrough or mini"`
Expected: 4 failures. For example, the first fails with `assert [] == ['0', '1', '2', '3', '4']`.

- [ ] **Step 3: Replace the `s-how` stub section**

```html
  <!-- 5 · Technical solution -->
  <section class="slide s-how" data-steps="4" aria-label="Technical solution">
    <div class="inner">
      <div data-step="0">
        <div class="eyebrow">The technical solution</div>
        <h2>One chat turn, <span class="grad">end to end.</span></h2>
      </div>
      <div class="how">
        <ol class="walk">
          <li data-step="0" data-focus="customer amplify cognito pretoken">
            <b>Sign in</b>
            <span>The React chat signs the customer in with Amazon Cognito over OIDC (Authorization Code + PKCE). The token goes with every call to the agent's invocation entry point.</span>
          </li>
          <li data-step="1" data-focus="amplify agent memory bedrock guardrail">
            <b>Session</b>
            <span>AgentCore Runtime validates the token and opens the session: short-term memory, context truncation (30-message sliding window, active) and compaction (summarization, built and switchable by config). Bedrock runs DeepSeek v3.2; Haiku 4.5 or Sonnet 4.5 swap in by config. A Guardrail screens input and output.</span>
          </li>
          <li data-step="2" data-focus="agent identity gateway">
            <b>Every tool call is authorized</b>
            <span>The agent presents a Cognito token from the Identity token vault to the MCP Gateway. A Cedar policy approves the call only if the token carries a linked customer_id, the call is about that same customer and, to block a card or open a claim, the customer confirmed.</span>
          </li>
          <li data-step="3" data-focus="gateway tools dsql handoff">
            <b>The tools</b>
            <div class="toolset">
              <div><i>Session start</i><code>get_session_context</code><code>classify_call_type</code></div>
              <div><i>Cards &amp; charges</i><code>list_credit_cards</code><code>list_card_transactions</code><code>explain_transaction</code></div>
              <div><i>Fraud</i><code>transaction_fraud_detection</code></div>
              <div><i>Actions, on the customer's Yes</i><code>block_credit_card</code><code>open_claim</code><code>human_agent_hand_off</code></div>
            </div>
          </li>
          <li data-step="4" data-focus="tools handoff">
            <b>Honest about the mocks</b>
            <span><em class="badge">Mock models</em> Intent and fraud are heuristic rules that simulate a model's decision, deliberately out of scope. <em class="badge human">Simulated</em> The hand-off is a web simulation that triggers a human-agent hand-off.</span>
          </li>
        </ol>
        <div class="arch arch-mini" id="archMini" aria-hidden="true"></div>
      </div>
      <div class="tags" data-step="0">
        <span class="src build">From the LedgerLens build · agent/ledgerlens, gateway/policies/policy.cedar, infra-cdk</span>
      </div>
    </div>
  </section>
```

- [ ] **Step 4: Insert the CSS under `/* ---------- slide 5: technical solution ---------- */`**

```css
.s-how .inner { width: min(1320px, 100%); display: grid; gap: clamp(12px, 2vh, 22px); }
.s-how h2 { font-size: clamp(30px, 3.6vw, 52px); margin-top: 10px; }
.how { display: grid; grid-template-columns: minmax(0, .9fr) minmax(0, 1.1fr); gap: clamp(20px, 3vw, 44px); align-items: center; }
.walk { list-style: none; counter-reset: w; display: grid; gap: 12px; }
.walk li { counter-increment: w; position: relative; padding-left: 40px; }
.walk li::before { content: counter(w); position: absolute; left: 0; top: 0; width: 26px; height: 26px; border-radius: 50%; display: grid; place-items: center; font-size: 13px; background: rgba(46,70,232,.2); color: var(--cobalt-hi); }
.walk li b { display: block; font-weight: 500; font-size: 16.5px; margin-bottom: 3px; }
.walk li span { color: var(--soft); font-size: 14px; line-height: 1.5; }
.walk li[data-step].on:not(.current) { opacity: .45; }
.toolset { display: grid; gap: 6px; margin-top: 4px; }
.toolset div { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
.toolset i { font-style: normal; font-size: 12.5px; color: var(--soft); margin-right: 4px; }
.toolset code { font-family: var(--mono); font-size: 12px; padding: 3px 8px; border-radius: 8px; background: rgba(46,70,232,.14); color: #c9cff0; }
.badge { font-style: normal; font-size: 11px; letter-spacing: .12em; text-transform: uppercase; padding: 2px 8px; border-radius: 99px; border: 1px solid rgba(111,130,255,.5); color: var(--cobalt-hi); margin-right: 4px; }
.badge.human { border-color: rgba(242,163,27,.6); color: var(--mango); }
.arch-mini svg { width: 100%; height: auto; max-height: calc(100dvh - 260px); display: block; }
```

- [ ] **Step 5: Add the focus hook at `// slide hooks`**

```js
  // Technical solution: a clone of the architecture; each step highlights its part
  const mini = document.getElementById('archMini');
  const clone = document.getElementById('archSvg').cloneNode(true);
  clone.removeAttribute('id');
  clone.querySelector('defs')?.remove();
  clone.querySelectorAll('[data-step]').forEach(el => el.removeAttribute('data-step'));
  mini.appendChild(clone);
  hooks.push((s, st) => {
    if (!s.classList.contains('s-how')) return;
    const shown = [...s.querySelectorAll('[data-focus]')].filter(li => +li.dataset.step <= st);
    const last = shown.at(-1);
    const focus = new Set((last?.dataset.focus || '').split(' '));
    mini.classList.add('focusing');
    mini.querySelectorAll('[data-node]').forEach(n => n.classList.toggle('focus', focus.has(n.dataset.node)));
    s.querySelectorAll('.walk li').forEach(li => li.classList.toggle('current', li === last));
  });
```

The clone keeps `marker-end="url(#ah)"`. That still resolves to the original marker in slide 4's `<defs>`.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/unit/final_deck -q`
Expected: `22 passed`.

- [ ] **Step 7: Commit**

```bash
git add docs/hackathon_final_doc/ledgerlens-final.html tests/unit/final_deck/test_final_deck.py
git commit -m "feat(pitch): technical solution walkthrough slide

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Slide 6 (profitability with cost tooltips)

**Files:**
- Modify: `docs/hackathon_final_doc/ledgerlens-final.html`. Replace the `s-profit` stub section, and insert CSS under the slide 6 marker.
- Modify: `tests/unit/final_deck/test_final_deck.py` (append)

**Interfaces:**
- Consumes from Task 1:
  - the tooltip classes `.cost`, `.tip`, `.tip-left` and `.tip-down`, with tooltip text in `.tip > b` and `.tip > .f`
  - the `usd2` count-up format
  - `.card`, `.tags` and `.src.*`

The arithmetic test below recomputes every figure from the spec's inputs. If a value in the HTML drifts from the spec's math, the test fails.

- [ ] **Step 1: Append the failing tests**

```python
# ---------- Task 5: profitability ----------

VOLUME = 6661
HUMAN_LATAM = 1.23
HUMAN_GLOBAL = 7.20
GUARDRAIL, VARIABLE, FIXED = 0.0072, 0.0322, 25.54 / VOLUME
TOKENS = {"DeepSeek v3.2": 0.0554, "Haiku 4.5": 0.1134, "Sonnet 4.5": 0.3401}


def model_total(name):
    return TOKENS[name] + GUARDRAIL + VARIABLE + FIXED


def test_inputs_reproduce_the_spec_totals():
    assert round(16 / 60 * 3.7 / 0.8, 2) == HUMAN_LATAM
    assert [round(model_total(m), 3) for m in TOKENS] == [0.099, 0.157, 0.383]
    assert round(FIXED, 4) == 0.0038
    assert round(0.0203 + 0.0089 + 0.0014 + 0.0016, 4) == VARIABLE
    assert round(14.60 + 7.30 + 1.58 + 1.20 + 0.81 + 0.05, 2) == 25.54


def test_profit_slide_shows_every_computed_figure(deck):
    text = slide(deck, "s-profit").text()
    assert "$1.23" in text and "$7.20" in text
    for name in TOKENS:
        total = model_total(name)
        latam, glob = HUMAN_LATAM - total, HUMAN_GLOBAL - total
        monthly_latam = VOLUME * HUMAN_LATAM - VOLUME * total
        monthly_glob = VOLUME * HUMAN_GLOBAL - VOLUME * total
        for value in [f"${total:.3f}", f"${latam:.2f}", f"{round(latam / HUMAN_LATAM * 100)}%",
                      f"${glob:.2f}", f"{round(glob / HUMAN_GLOBAL * 100)}%",
                      f"${round(monthly_latam):,}", f"${round(monthly_glob):,}"]:
            assert value in text, (name, value)


def test_every_cost_figure_has_a_focusable_tooltip(deck):
    costs = slide(deck, "s-profit").find_all(lambda e: "cost" in e.classes())
    assert len(costs) >= 15
    for cost in costs:
        assert cost.attrs.get("tabindex") == "0", cost.text()
        tips = [c for c in cost.children if not isinstance(c, str) and "tip" in c.classes()]
        assert len(tips) == 1 and tips[0].attrs.get("role") == "tooltip", cost.text()
        assert len(tips[0].text()) > 40, cost.text()


def test_tooltips_explain_how_each_figure_was_calculated(deck):
    tips = " ".join(t.text() for t in slide(deck, "s-profit").find_all(lambda e: "tip" in e.classes()))
    for value in ["$16/hr ÷ 60 × 3.7 min ÷ 0.8 = $1.23", "FusionCX", "ContactBabel", "$8.01",
                  "9-turn session", "12 model calls", "$0.62", "$1.85", "$1.10", "$5.50", "$3.30",
                  "$16.50", "Cost Explorer", "$0.15 per 1K", "Cognito M2M", "$25.54 a month ÷ 6,661",
                  "about $0.091", "about $0.186"]:
        assert value in tips, value


def test_right_column_tooltips_open_leftwards(deck):
    save = slide(deck, "s-profit").find_all(lambda e: "save" in e.classes())[0]
    for cost in save.find_all(lambda e: "cost" in e.classes()):
        assert "tip-left" in cost.classes(), cost.text()


def test_profit_slide_carries_the_caveat_and_sources(deck):
    s = slide(deck, "s-profit")
    assert "A contact handed to a person still costs a human contact." in s.text()
    assert "LedgerLens. Every customer, understood." in s.text()
    links = [a.attrs["href"] for a in s.find_all(lambda e: e.tag == "a")]
    assert any("contactbabel.com" in h for h in links)
    assert any("fusioncx.com" in h for h in links)
    assert any("aws.amazon.com/bedrock/pricing" in h for h in links)
    for cls in ["data", "build", "bench", "assume"]:
        assert s.find_all(lambda e, c=cls: {"src", c} <= e.classes()), cls
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/unit/final_deck -q -k "profit or tooltip or inputs or leftwards"`
Expected: `test_inputs_reproduce_the_spec_totals` passes. The other 5 FAIL, for example `AssertionError: ('DeepSeek v3.2', '$0.099')` and `IndexError` for `.save`.

- [ ] **Step 3: Replace the `s-profit` stub section**

The `.tip` spans hold a `<b>` title, an optional `.f` formula line, then plain text. Keep all tooltip markup inline (spans only), because a tooltip sits inside a `<span>` or `<td>`.

```html
  <!-- 6 · Profitability -->
  <section class="slide s-profit" data-steps="3" aria-label="Profitability">
    <div class="inner">
      <div data-step="0">
        <div class="eyebrow">Profitability</div>
        <h2>Your contact center is expensive.<br><span class="grad">Keep it low, and increase your margins.</span></h2>
      </div>
      <div class="profit">
        <div class="card ladder">
          <div class="k">Cost per contact</div>
          <div class="rung human" data-step="1">
            <div class="who">Person, LATAM bank<small>conservative baseline</small></div>
            <div class="track"><div class="fill" style="--w:100%"></div></div>
            <span class="cost amt" tabindex="0">$1.23<span class="tip" role="tooltip"><b>How we got $1.23</b><span class="f">$16/hr ÷ 60 × 3.7 min ÷ 0.8 = $1.23</span>$16/hr is the midpoint of the $12–20/hr fully loaded agent cost in Colombia (FusionCX, 2026). 3.7 min is the average handle time of a transactional contact in the dataset. 0.8 assumes agents spend 80% of paid time on calls (our assumption). Range: $0.75–1.55. The 2.0 min wait is left out: it costs the customer's time, not the agent's.</span></span>
          </div>
          <p class="ref" data-step="1">Global reference: <span class="cost" tabindex="0">$7.20 per inbound call<span class="tip" role="tooltip"><b>Global benchmark</b>ContactBabel, 2026 US Contact Center Decision-Makers' Guide: $7.20 average cost per inbound call. Gartner's 2019 poll gives $8.01 per live-channel contact. Published benchmarks run higher than our LATAM figure because they assume longer calls and include after-call work, technology and overhead.</span></span></p>
          <div class="rung" data-step="2">
            <div class="who">LedgerLens · DeepSeek v3.2<small>deployed</small></div>
            <div class="track"><div class="fill" style="--w:8.0%"><i style="flex:554"></i><i style="flex:72"></i><i style="flex:322"></i><i style="flex:38"></i></div></div>
            <span class="cost amt" tabindex="0">$0.099<span class="tip" role="tooltip"><b>DeepSeek v3.2: $0.099 per contact</b><span class="f">tokens $0.0554 + Guardrail $0.0072 + variable infra $0.0322 + fixed $0.0038</span>One contact is a 9-turn session: 12 model calls and 7 tool calls. Tokens: about 85.2K in × $0.62 per 1M + 1.4K out × $1.85 per 1M (Bedrock on-demand, us-east-1). Calibrated on Bedrock token metrics from our AWS account; unit prices match Cost Explorer. Bedrock offers no prompt caching for DeepSeek.</span></span>
          </div>
          <div class="rung" data-step="2">
            <div class="who">LedgerLens · Haiku 4.5</div>
            <div class="track"><div class="fill" style="--w:12.7%"><i style="flex:1134"></i><i style="flex:72"></i><i style="flex:322"></i><i style="flex:38"></i></div></div>
            <span class="cost amt" tabindex="0">$0.157<span class="tip" role="tooltip"><b>Claude Haiku 4.5: $0.157 per contact</b><span class="f">tokens $0.1134 + Guardrail $0.0072 + variable infra $0.0322 + fixed $0.0038</span>Same 9-turn session with 12 model calls. Tokens: about 95.5K in × $1.10 per 1M + 1.5K out × $5.50 per 1M (us geo inference profile, us-east-1). Unit prices match Cost Explorer. With prompt caching of the system prompt and tools: about $0.091.</span></span>
          </div>
          <div class="rung" data-step="2">
            <div class="who">LedgerLens · Sonnet 4.5</div>
            <div class="track"><div class="fill" style="--w:31.2%"><i style="flex:3401"></i><i style="flex:72"></i><i style="flex:322"></i><i style="flex:38"></i></div></div>
            <span class="cost amt" tabindex="0">$0.383<span class="tip" role="tooltip"><b>Claude Sonnet 4.5: $0.383 per contact</b><span class="f">tokens $0.3401 + Guardrail $0.0072 + variable infra $0.0322 + fixed $0.0038</span>Same 9-turn session with 12 model calls. Tokens: about 95.5K in × $3.30 per 1M + 1.5K out × $16.50 per 1M (us geo inference profile, us-east-1). Unit prices match Cost Explorer. With prompt caching of the system prompt and tools: about $0.186.</span></span>
          </div>
          <div class="legend" data-step="2">
            <span class="cost lg tok" tabindex="0">Tokens<span class="tip" role="tooltip"><b>Tokens</b>Input and output tokens per contact × the Bedrock on-demand price in us-east-1, per 1M tokens in / out: DeepSeek v3.2 $0.62 / $1.85, Haiku 4.5 $1.10 / $5.50, Sonnet 4.5 $3.30 / $16.50.</span></span>
            <span class="cost lg grd" tabindex="0">Guardrail $0.0072<span class="tip" role="tooltip"><b>Bedrock Guardrail</b><span class="f">$0.0006 × 12 model calls = $0.0072</span>2 ApplyGuardrail calls per model call (input and output), content and topic policies, 1 text unit each at $0.15 per 1K text units.</span></span>
            <span class="cost lg var" tabindex="0">Variable infra $0.0322<span class="tip" role="tooltip"><b>Variable infra per contact</b>Cognito M2M tokens $0.0203 (a new token on each of 9 invocations × $0.00225) · AgentCore Runtime $0.0089 · Aurora DSQL $0.0014 · Memory, Gateway, Cedar, Lambda and logs about $0.0016.</span></span>
            <span class="cost lg fix" tabindex="0">Fixed infra $0.0038<span class="tip" role="tooltip"><b>Fixed infra, spread over the volume</b><span class="f">$25.54 a month ÷ 6,661 contacts = $0.0038</span>API Gateway cache $14.60 · DSQL VPC endpoint $7.30 · DSQL storage $1.58 · Secrets Manager $1.20 · DSQL background reads $0.81 · ECR and Amplify $0.05. The one-off data pipeline is excluded.</span></span>
          </div>
        </div>

        <div class="card save" data-step="3">
          <div class="k">Saved per contact, at 6,661 contacts a month</div>
          <table class="savings">
            <thead><tr><th></th><th>vs LATAM $1.23</th><th>vs global $7.20</th><th>a month, LATAM / global</th></tr></thead>
            <tbody>
              <tr>
                <th>DeepSeek v3.2</th>
                <td><span class="cost tip-left" tabindex="0"><span data-count="1.13" data-format="usd2">$1.13</span> <small>92%</small><span class="tip" role="tooltip"><b>Saved vs a person, LATAM</b><span class="f">$1.23 − $0.099 = $1.13 (92%)</span>The human cost per contact minus LedgerLens on DeepSeek v3.2.</span></span></td>
                <td><span class="cost tip-left" tabindex="0"><span data-count="7.10" data-format="usd2">$7.10</span> <small>99%</small><span class="tip" role="tooltip"><b>Saved vs a person, global</b><span class="f">$7.20 − $0.099 = $7.10 (99%)</span>ContactBabel's 2026 cost per inbound call minus LedgerLens on DeepSeek v3.2.</span></span></td>
                <td><span class="cost tip-left" tabindex="0">$7,536 / $47,302<span class="tip" role="tooltip"><b>Saved a month, DeepSeek v3.2</b><span class="f">$8,193 − $657 = $7,536</span><span class="f">$47,959 − $657 = $47,302</span>People: 6,661 contacts × $1.23 = $8,193, or × $7.20 = $47,959. LedgerLens: 6,661 × $0.0986 (the unrounded total) = $657. 6,661 is the average of transactional contacts a month in the dataset.</span></span></td>
              </tr>
              <tr>
                <th>Haiku 4.5</th>
                <td><span class="cost tip-left" tabindex="0"><span data-count="1.07" data-format="usd2">$1.07</span> <small>87%</small><span class="tip" role="tooltip"><b>Saved vs a person, LATAM</b><span class="f">$1.23 − $0.157 = $1.07 (87%)</span>The human cost per contact minus LedgerLens on Claude Haiku 4.5.</span></span></td>
                <td><span class="cost tip-left" tabindex="0"><span data-count="7.04" data-format="usd2">$7.04</span> <small>98%</small><span class="tip" role="tooltip"><b>Saved vs a person, global</b><span class="f">$7.20 − $0.157 = $7.04 (98%)</span>ContactBabel's 2026 cost per inbound call minus LedgerLens on Claude Haiku 4.5.</span></span></td>
                <td><span class="cost tip-left" tabindex="0">$7,150 / $46,916<span class="tip" role="tooltip"><b>Saved a month, Haiku 4.5</b><span class="f">$8,193 − $1,043 = $7,150</span><span class="f">$47,959 − $1,043 = $46,916</span>People: 6,661 contacts × $1.23 = $8,193, or × $7.20 = $47,959. LedgerLens: 6,661 × $0.1566 (the unrounded total) = $1,043. 6,661 is the average of transactional contacts a month in the dataset.</span></span></td>
              </tr>
              <tr>
                <th>Sonnet 4.5</th>
                <td><span class="cost tip-left" tabindex="0"><span data-count="0.85" data-format="usd2">$0.85</span> <small>69%</small><span class="tip" role="tooltip"><b>Saved vs a person, LATAM</b><span class="f">$1.23 − $0.383 = $0.85 (69%)</span>The human cost per contact minus LedgerLens on Claude Sonnet 4.5.</span></span></td>
                <td><span class="cost tip-left" tabindex="0"><span data-count="6.82" data-format="usd2">$6.82</span> <small>95%</small><span class="tip" role="tooltip"><b>Saved vs a person, global</b><span class="f">$7.20 − $0.383 = $6.82 (95%)</span>ContactBabel's 2026 cost per inbound call minus LedgerLens on Claude Sonnet 4.5.</span></span></td>
                <td><span class="cost tip-left" tabindex="0">$5,640 / $45,406<span class="tip" role="tooltip"><b>Saved a month, Sonnet 4.5</b><span class="f">$8,193 − $2,553 = $5,640</span><span class="f">$47,959 − $2,553 = $45,406</span>People: 6,661 contacts × $1.23 = $8,193, or × $7.20 = $47,959. LedgerLens: 6,661 × $0.3833 (the unrounded total) = $2,553. 6,661 is the average of transactional contacts a month in the dataset.</span></span></td>
              </tr>
            </tbody>
          </table>
          <p class="caveat">Assumes the contact is fully automated. A contact handed to a person still costs a human contact.</p>
          <details class="sources">
            <summary>Sources</summary>
            <ul>
              <li><a href="https://www.fusioncx.com/blog/locations/colombia-vs-us-call-center-costs/" target="_blank" rel="noopener">FusionCX, Colombia vs. US Call Center Costs (2026)</a></li>
              <li><a href="https://www.contactbabel.com/the-us-contact-center-decision-makers-guide/" target="_blank" rel="noopener">ContactBabel, The US Contact Center Decision-Makers' Guide (2026)</a></li>
              <li><a href="https://www.destinationcrm.com/Articles/CRM-Insights/Insight/Gartner-Survey-Finds-Self-Service-Insufficient-135436.aspx" target="_blank" rel="noopener">Gartner poll via DestinationCRM (2019)</a></li>
              <li><a href="https://aws.amazon.com/bedrock/pricing/" target="_blank" rel="noopener">Amazon Bedrock and Guardrails pricing</a></li>
              <li><a href="https://aws.amazon.com/bedrock/agentcore/pricing/" target="_blank" rel="noopener">Amazon Bedrock AgentCore pricing</a></li>
              <li><a href="https://aws.amazon.com/cognito/pricing/" target="_blank" rel="noopener">Amazon Cognito pricing</a> · <a href="https://aws.amazon.com/rds/aurora/dsql/pricing/" target="_blank" rel="noopener">Aurora DSQL pricing</a> · <a href="https://aws.amazon.com/privatelink/pricing/" target="_blank" rel="noopener">PrivateLink pricing</a> · <a href="https://aws.amazon.com/api-gateway/pricing/" target="_blank" rel="noopener">API Gateway pricing</a></li>
            </ul>
          </details>
        </div>
      </div>
      <p class="close" data-step="3"><span class="grad">LedgerLens.</span> Every customer, understood.</p>
      <div class="tags" data-step="1">
        <span class="src bench">Benchmarks: FusionCX 2026, ContactBabel 2026</span>
        <span class="src build">LedgerLens costs: Bedrock CloudWatch metrics and Cost Explorer, us-east-1, Oct 2026</span>
        <span class="src data">Volume and handle time: provided contact-center dataset</span>
        <span class="src assume">80% occupancy and the 9-turn session are assumptions</span>
      </div>
    </div>
  </section>
```

Bar widths are each unrounded total ÷ $1.23: 0.0986 → 8.0%, 0.1566 → 12.7% and 0.3833 → 31.2%. The monthly column shows whole dollars, not "$7.2K"-style rounding, so each tooltip's subtraction matches the cell exactly. This corrects the spec's Haiku LATAM figure: $7,150 is $7.1K, not $7.2K. Each segment's `flex` is its cost in units of $0.0001.

- [ ] **Step 4: Insert the CSS under `/* ---------- slide 6: profitability ---------- */`**

```css
.s-profit .inner { width: min(1320px, 100%); display: grid; gap: clamp(14px, 2.4vh, 26px); }
.s-profit h2 { font-size: clamp(30px, 3.6vw, 54px); margin-top: 10px; }
.profit { display: grid; grid-template-columns: 1.05fr .95fr; gap: clamp(14px, 2vw, 26px); align-items: start; }
.rung { display: grid; grid-template-columns: minmax(150px, 34%) 1fr auto; gap: 14px; align-items: center; padding: 10px 0; border-top: 1px solid var(--line); }
.who { font-size: 15px; }
.who small { display: block; font-size: 12px; color: var(--soft); }
.track { height: 14px; border-radius: 99px; background: rgba(255,255,255,.04); overflow: hidden; }
.fill { display: flex; height: 100%; width: var(--w); border-radius: 99px; background: var(--cobalt-hi); transform-origin: left; transform: scaleX(0); transition: transform 1.3s var(--ease) .2s; }
.rung.on .fill { transform: scaleX(1); }
.rung.human .fill { background: var(--mango); }
.fill i { display: block; height: 100%; }
.fill i:nth-child(1) { background: var(--cobalt-hi); }
.fill i:nth-child(2) { background: #a9b6ff; }
.fill i:nth-child(3) { background: var(--green); }
.fill i:nth-child(4) { background: var(--soft); }
.amt { font-family: var(--display); font-size: clamp(22px, 2vw, 30px); font-variant-numeric: tabular-nums; }
.ref { font-size: 13.5px; color: var(--soft); padding: 6px 0 4px; }
.legend { display: flex; flex-wrap: wrap; gap: 8px 16px; margin-top: 10px; font-size: 12.5px; color: var(--soft); }
.lg::before { content: ""; display: inline-block; width: 10px; height: 10px; border-radius: 3px; margin-right: 6px; background: var(--c); vertical-align: -1px; }
.lg.tok { --c: var(--cobalt-hi); } .lg.grd { --c: #a9b6ff; } .lg.var { --c: var(--green); } .lg.fix { --c: var(--soft); }
.savings { width: 100%; border-collapse: collapse; font-variant-numeric: tabular-nums; }
.savings th, .savings td { text-align: left; padding: 10px 8px; border-top: 1px solid var(--line); font-weight: 400; }
.savings thead th { font-size: 11.5px; letter-spacing: .08em; text-transform: uppercase; color: var(--soft); border-top: 0; }
.savings tbody th { font-size: 14.5px; }
.savings td { font-family: var(--display); font-size: clamp(18px, 1.6vw, 24px); }
.savings td small { font-family: var(--sans); font-size: 12.5px; color: var(--green); margin-left: 4px; }
.caveat { margin-top: 12px; font-size: 13px; color: var(--soft); }
.sources { margin-top: 10px; }
.sources summary { cursor: pointer; font-size: 12px; color: #7d83a3; letter-spacing: .04em; }
.sources ul { margin-top: 8px; padding-left: 18px; display: grid; gap: 4px; font-size: 12px; color: #7d83a3; }
.sources a { color: var(--cobalt-hi); }
.s-profit .close { font-family: var(--display); font-weight: 300; font-size: clamp(22px, 2.4vw, 34px); letter-spacing: -0.02em; text-align: center; }
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/unit/final_deck -q`
Expected: `28 passed`.

- [ ] **Step 6: Commit**

```bash
git add docs/hackathon_final_doc/ledgerlens-final.html tests/unit/final_deck/test_final_deck.py
git commit -m "feat(pitch): profitability slide with cost tooltips

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Browser verification and fixes

**Files:**
- Modify: `docs/hackathon_final_doc/ledgerlens-final.html`, only to fix what this task finds.

**Interfaces:**
- Consumes: the finished deck.

Use the claude-in-chrome tools. Load `tabs_context_mcp`, `tabs_create_mcp`, `navigate`, `computer`, `read_console_messages`, `resize_window` and `javascript_tool` in one ToolSearch call.

- [ ] **Step 1: Open the deck and check the console**

Navigate a new tab to `file:///C:/GITHUB%20REPOS/ledgerlens-bank-assistant/docs/hackathon_final_doc/ledgerlens-final.html`. Then run `read_console_messages` with pattern `error|Error`.
Expected: no errors.

- [ ] **Step 2: Step through every slide at 1920×1080**

Resize the window to 1920×1080. Press → through the whole deck (the end is `#6.3`), taking a screenshot at the last step of each slide.
Expected:
- The counter reads 1 / 6 … 6 / 6.
- Nothing is clipped or overlapping.
- Slide 1's bars grow, and its numbers count up to 6,661, 4,663, 12,297 and 288.
- Slide 2's lens closes.
- Slide 4's lanes appear left to right.
- On slide 5, each step highlights its nodes in the mini diagram.
- Slide 6's savings count up to $1.13, $7.10, $1.07, $7.04, $0.85 and $6.82.

- [ ] **Step 3: Check navigation edge cases**

- Press ← from `#2` and confirm it goes back to slide 1, step 3.
- Load `#6.3`, then `#4`.
- Press `6`, then `Home`.

Expected: each lands on the right slide and step.

- [ ] **Step 4: Check every tooltip at 1366×768**

Resize to 1366×768 and go to `#6.3`. Run this in `javascript_tool`:

```js
[...document.querySelectorAll('.s-profit .cost')].map(c => {
  c.focus();
  const r = c.querySelector('.tip').getBoundingClientRect();
  return { text: c.firstChild.textContent.trim().slice(0, 24), left: Math.round(r.left), right: Math.round(r.right), top: Math.round(r.top), bottom: Math.round(r.bottom), visible: getComputedStyle(c.querySelector('.tip')).visibility };
}).filter(t => t.left < 0 || t.right > innerWidth || t.top < 0 || t.bottom > innerHeight || t.visible !== 'visible');
```

Expected: `[]`. Fix any element listed:
- one that runs off the top gets `tip-down`
- one that runs off the right edge gets `tip-left`

Then rerun the tests. Hover one cost figure with the mouse and click it. The tooltip should show, and the slide must not advance.

- [ ] **Step 5: Check the narrow layout**

Resize to 390×844, then run `document.documentElement.scrollWidth <= innerWidth` on `#1.3`, `#3.3`, `#4.3`, `#5.4` and `#6.3`.
Expected: `true` on each.

- [ ] **Step 6: Run the full test suite and confirm the pitch deck is untouched**

Run: `.venv/Scripts/python -m pytest tests/unit/final_deck -q`, then `git diff --stat docs/hackathon_final_doc/ledgerlens-pitch.html`.
Expected: `28 passed`, and an empty diff.

- [ ] **Step 7: Commit any fixes**

Run this only if Step 4 or Step 5 changed the file:

```bash
git add docs/hackathon_final_doc/ledgerlens-final.html tests/unit/final_deck/test_final_deck.py
git commit -m "fix(pitch): tooltip placement and layout after browser check

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```
