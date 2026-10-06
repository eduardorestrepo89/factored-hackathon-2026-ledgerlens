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
    for call in ["cloneNode(true)", "removeAttribute('id')", "id = 'ah-mini'",
                 "removeAttribute('data-step')"]:
        assert call in source, call

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


# ---------- Task 6: fixes from the browser check ----------

def test_left_edge_tooltip_opens_rightwards(deck, source):
    legend = slide(deck, "s-profit").find_all(lambda e: "legend" in e.classes())[0]
    first = legend.find_all(lambda e: "cost" in e.classes())[0]
    assert "tip-right" in first.classes()
    assert ".cost.tip-right .tip" in source


def test_slides_shrink_to_fit_short_screens(source):
    for code in ["function fit()", "addEventListener('resize', fit)", "document.fonts?.ready.then(fit)"]:
        assert code in source, code


# ---------- Final review fixes ----------

def test_mini_diagram_keeps_its_own_arrowheads(source):
    assert "clone.querySelector('defs')?.remove()" not in source
    assert "ah-mini" in source


def test_phone_tooltips_span_the_card(source):
    narrow = source[source.index("@media (max-width: 900px)"):]
    narrow = narrow[:narrow.index("@media (prefers-reduced-motion")]
    assert ".cost .tip" in narrow


def test_moving_on_closes_a_focused_tooltip(source):
    assert "closest?.('.cost')?.blur()" in source


def test_latam_range_follows_its_formula(deck):
    text = slide(deck, "s-profit").text()
    assert "$0.75" not in text
    assert "$0.93–1.54" in text


def test_fcr_is_labelled_a_proxy(deck):
    assert "first-contact resolution (proxy)" in slide(deck, "s-problem").text().lower()
    assert "70.1% (proxy)" in slide(deck, "s-solution").text()


# ---------- Big average savings ----------

def test_profit_slide_leads_with_big_average_savings(deck):
    band = slide(deck, "s-profit").find_all(lambda e: "big-save" in e.classes())
    assert band, "no .big-save band"
    counts = band[0].find_all(lambda e: "data-count" in e.attrs)
    assert [c.attrs["data-count"] for c in counts] == ["83", "97"]
    text = band[0].text()
    for part in ["vs LATAM", "vs global",
                 "(92.0% + 87.3% + 68.8%) ÷ 3 = 82.7%",
                 "(98.6% + 97.8% + 94.7%) ÷ 3 = 97.0%"]:
        assert part in text, part


# ---------- Slide 5: the diagram gets the full width ----------

def test_walkthrough_puts_the_diagram_first_at_full_width(deck, source):
    how = slide(deck, "s-how").find_all(lambda e: "how" in e.classes())[0]
    blocks = [c for c in how.children if not isinstance(c, str)]
    assert blocks[0].attrs.get("id") == "archMini"
    assert ".how { display: grid; grid-template-columns: minmax(0, 1fr);" in source


def test_walkthrough_shows_one_detail_per_step_under_a_row_of_titles(deck, source):
    s = slide(deck, "s-how")
    titles = s.find_all(lambda e: e.tag == "li" and "data-focus" in e.attrs)
    assert all([c.tag for c in li.children if not isinstance(c, str)] == ["b"] for li in titles)
    details = s.find_all(lambda e: "walk-detail" in e.classes())[0]
    assert len([c for c in details.children if not isinstance(c, str)]) == 5
    assert "grid-template-columns: repeat(5, minmax(0, 1fr))" in source
    assert "'.walk-detail > div'" in source
    assert ".walk" in source.split("@media (max-width: 900px)")[1].split("}\n}")[0]
