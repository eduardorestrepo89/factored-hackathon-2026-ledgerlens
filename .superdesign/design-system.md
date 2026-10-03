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

## Brand and color
Fonts: **Geist** (UI) and **Geist Mono** (ids, amounts, timestamps, codes). No other families.

Brand tokens (from `frontend/src/styles/globals.css`):
| Token | Value | Use |
|---|---|---|
| brand-dark | hsl(197 37% 24%) | primary actions, customer bubbles, header |
| brand-teal | hsl(173 58% 39%) | AI assistant tier |
| brand-lime | hsl(43 74% 66%) | highlights, router/system accents (sparingly) |
| brand-yellow | hsl(27 87% 67%) | warnings |
| brand-orange | hsl(12 76% 61%) | **human tier**: hand-off ticket, desk accents, human bubbles |

Semantic surfaces (light; a dark set mirrors them):
| Role | Light | Dark |
|---|---|---|
| bg | hsl(195 22% 95%) | hsl(200 26% 7%) |
| surface | #fff | hsl(200 22% 11%) |
| sunk | hsl(195 22% 92%) | hsl(200 22% 14%) |
| fg | hsl(200 32% 12%) | hsl(195 20% 92%) |
| muted | hsl(198 12% 38%) | hsl(195 10% 64%) |
| line | hsl(195 18% 85%) | hsl(200 16% 22%) |
| ai / ai-bg | hsl(173 62% 26%) / hsl(173 42% 90%) | hsl(173 55% 62%) / hsl(173 35% 16%) |
| human / human-bg | hsl(12 68% 42%) / hsl(12 80% 94%) | hsl(14 88% 70%) / hsl(12 35% 18%) |
| danger | hsl(0 62% 42%) | hsl(0 72% 68%) |
| ok | hsl(150 52% 28%) | hsl(150 50% 62%) |

Tier color is meaning, not decoration: teal = AI assistant, orange = human, brand-dark = customer.
Never use purple, pink, neon or gradients across the whole page.

## Shape, spacing, depth
- Radius: 10 px base (`--radius: 0.625rem`); bubbles 14 px with one 4 px tail corner; phone frame 28 px;
  pills 999 px.
- Spacing on a 4 px grid; panels 16 px padding; 16 px gaps between panes.
- Borders 1 px `line`; shadows are soft and low (`0 18px 40px -28px hsl(200 40% 10% / .45)` on the
  phone only).
- Labels: 11 px, 600, uppercase, letter-spacing .08em, `muted`.
- Numbers: tabular-nums; amounts and ids in Geist Mono.

## Components
- **Bubble**: customer right-aligned on brand-dark; AI left on ai-bg with a small "Asistente IA" tag;
  human left on human-bg with "Laura · Persona" tag.
- **Tool row** (existing): collapsible row with wrench icon, tool name, spinner or check.
- **Hand-off ticket** (new, inline in chat): orange-bordered card on human-bg: "Caso HO-7Q3K",
  priority pill (ALTA in danger outline / Normal), reason ("Fraude confirmado"), related id chips
  (TX-88, TX-89, C-20931) in mono, status "En cola para una persona".
- **Case card** (desk header): customer name, product (•••• 4821, bloqueada), verified-by, queue,
  priority pill, hand-off id, summary paragraph, related-id chips, "Lo que ya se le dijo".
- **Suggested reply**: dashed-border row with the text and an "Usar" button.
- **System divider**: centered 11.5 px muted text ("Laura se unió a la conversación · 03:18").
- Icons: lucide-react only (User, Bot, ShieldCheck, Ticket, ArrowRightLeft, Send, Check, Loader2).

## Motion
- Native View Transitions API for the layout split (no animation library).
- Beat 1: ticket appears in chat (rise 220 ms ease-out).
- Beat 2 (after the agent's goodbye finishes streaming + ~600 ms): chat column morphs into the phone
  frame on the left; desk slides in from the right (320 ms); the ticket morphs into the case card
  header (shared `view-transition-name: handoff-ticket`).
- Beat 3: phone shows "Conectando con una persona…" with a soft pulsing orange dot until the human
  agent sends the first message, then a "Laura se unió" divider and orange bubbles.
- Respect `prefers-reduced-motion`: cross-fade only.

## Requirements
- Copy in Spanish (es-CO) for customer- and agent-facing text.
- WCAG AA contrast; focus-visible rings in brand-dark/teal.
- The desk must be readable from the back of a room: case card title 18–20 px, summary 14–15 px.
- No promised wait time anywhere ("Don't promise a time").
