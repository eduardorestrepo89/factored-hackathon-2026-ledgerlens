"""Parse docs/hackathon_final_doc/ledgerlens-final.html into a small element tree for the tests.

bs4 isn't installed, so this builds the tree with the stdlib HTMLParser. Text is
kept in document order, so Element.text() reads the way the slide does.
"""

from html.parser import HTMLParser
from pathlib import Path

DECK_PATH = Path(__file__).resolve().parents[3] / "docs" / "hackathon_final_doc" / "ledgerlens-final.html"

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
