# LedgerLens design system

## Product context
LedgerLens is LATAM Bank's AI customer-service assistant for credit cards (Colombia first, es-CO copy).
A customer chats with an AI agent (AWS AgentCore + Strands) that can explain declines and FX charges,
block a card, open a fraud claim and, when needed, hand the conversation to a human agent.

Audience for this design: hackathon judges watching a live demo on a projector (1440–1920 px wide).
The demo must make one moment unmistakable: **the bot hands off, the context travels, the customer
never repeats anything.**

### Key screens
1. **Customer chat** (existing): full-width chat, header, streaming assistant messages with inline
   tool-call rows, composer at the bottom.
2. **Hand-off split** (new): the chat becomes a phone-framed customer view on the left (~390 px);
   a **Human agent desk** opens on the right with the case card, the customer's thread mirrored,
   suggested replies and a composer for the human agent ("Laura · Fraudes y servicio").

### JTBD
- Customer: get a clear answer or a person, without repeating themselves.
- Human agent: understand the case in 5 seconds (who, verified how, what was done, ids, priority) and
  reply.
- Judge: see that the hand-off is real (driven by the live tool call) and that it is humane.

## Brand and color (v2, 2026-10-04: "the lens")
Concept: the **lens band**, after Cruz-Diez's Physichromies: thin vertical cobalt lines (the AI)
interleaved with mango lines (a person). The band is the strip under the header (it changes owner
with the conversation: `data-phase` ai → connecting → joined) and the face of the card on the
sign-in page. That band is the one bold element; everything around it stays quiet.

Mark (`LensMark`, `public/favicon.svg`): a biconvex lens seen edge-on, split into a cobalt half
(the AI) and a mango half (a person) by a hairline gap. Both halves solid as the logo; as an
avatar or status, the half that doesn't own the conversation is drawn as an outline.

Sign-in hero (`LensScene.tsx`, three.js via @react-three/fiber and drei, lazy-loaded): a LATAM
Bank card whose face is the band, under a glass lens (drei `MeshTransmissionMaterial`) that rests
over the last 4 digits, follows the pointer and magnifies. Lit by drei `Lightformer`s, no HDR
download. Without WebGL2, or if the scene fails, the SVG slab (lines plus a CSS lens) stands in.

Fonts (v3): **Funnel Display** for the wordmark and headlines (`.display`: weight 400, tracking
-0.035em; big headlines add `font-light`, the wordmark `font-medium`) and **Funnel Sans** for
everything else. Minimal but not plain: wide, light letterforms with their own details. Ids and
amounts use `.figures` (tabular, slashed zero), not a monospace. No other families.

Confirmations (contract: `docs/handoffs/2026-10-04-confirmation-buttons-frontend.md`): when the
agent's `ConfirmationHook` pauses `block_credit_card`, `open_claim` or `human_agent_hand_off`, the
runtime streams a `confirmation` event and the paused tool row becomes a `ConfirmCard` (title, one
line, No / Sí, mango border; a person icon for a hand-off). The composer is locked until the
customer taps; the tap is sent as `confirmations: [{interruptId, approved}]`, and only Sí runs the
call.

| Token | Light | Dark | Use |
|---|---|---|---|
| page | #F4F6FB | #0F1226 | app background (cool white, not cream) |
| card / background | #FFFFFF | #171B35 | surfaces |
| foreground / primary | #161A33 | #E8EAF6 | text, primary buttons |
| ink | #161A33 | #2A3170 | **customer**: bubbles, phone bezel |
| ai / ai-bg | #2E46E8 / #E9ECFE | #93A3FF / #1D2350 | **AI assistant** |
| mango | #F2A31B | #F2A31B | **human** fills (avatars, send, band); ink text on it |
| human / human-bg | #8F5300 / #FDF0D5 | #FFC35C / #33270F | human text / human surfaces |
| ok | #12805C | #4FD1A0 | joined, done |
| destructive | #C8323F | #FF7A86 | high priority, errors |
| border | #DDE1EC | #2A3052 | lines |

Tier color is meaning, not decoration: cobalt = AI assistant, mango = human, ink = customer.
Never purple, pink, neon or whole-page gradients.

## Shape, spacing, depth
- Radius: 12 px base; bubbles 20 px with one 6 px tail corner; composers 22 px; desk 28 px; phone
  40 px bezel / 32 px screen; buttons and chips are pills.
- Spacing on a 4 px grid; panels 20 px padding.
- Shadows only on the phone, the composer and the lens.
- Labels: sentence case, 12–14 px, 500, `muted`. No all-caps tracked labels, no "A · B" strings.

## Components
- **Bubble**: customer right on ink; AI left on ai-bg with a cobalt `LensMark` avatar and a
  "LedgerLens" tag; human left on human-bg with a mango "L" avatar and "Laura, asesora".
- **Tool row**: pill with a check or spinner and a plain-language label per tool
  (`tool.<name>` in i18n, e.g. "Revisando movimientos"); opens to the raw name, input and result.
- **Hand-off ticket**: a branch turn ticket ("turno"): human-bg, two side notches and a dashed tear
  line (`.ticket`, `--perf`); stub shows "Caso HO-…" in `.display` and the priority pill; below the
  tear: reason, id chips, "Enviado a una persona".
- **Case card** (desk): the same ticket, larger: id + "Nuevo", priority; customer name in
  `.display`, reason and queue, customer id, queued since, summary, related ids, "Lo que ya se le dijo".
- **Suggested reply**: mango-outlined row with an "Usar" pill.
- **System divider**: centered human-bg pill ("Laura se unió a la conversación a las 03:18").
- Icons: lucide-react only.

## Motion
- Native View Transitions API for the layout split (no animation library).
- Beat 1: ticket appears in chat (rise 220 ms ease-out).
- Beat 2 (after the agent's goodbye finishes streaming + ~600 ms): chat column morphs into the phone
  frame on the left; desk slides in from the right (320 ms); the ticket morphs into the case card
  header (shared `view-transition-name: handoff-ticket`).
- Beat 3: phone shows "Conectando con una persona…" with a soft pulsing mango dot until the human
  agent sends the first message, then a "Laura se unió" divider and mango bubbles; the header band turns from cobalt to mango (1.4 s).
- Respect `prefers-reduced-motion`: cross-fade only; the band changes owner at once.

## Requirements
- Copy in Spanish (es-CO) for customer- and agent-facing text.
- WCAG AA contrast; focus-visible rings in cobalt.
- The desk must be readable from the back of a room: case card title 36 px display, summary 14–15 px.
- No promised wait time anywhere ("Don't promise a time").
