import { useState, type FormEvent } from "react"
import { Check, Send, Ticket, User } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { type HandOff, type Phase, queueFor, reasonLabel, suggestedReplies } from "@/lib/handoff"
import { useI18n } from "@/lib/i18n"
import { ChatMessages } from "./ChatMessages"
import { HAND_OFF_TRANSITION, IdChips, PriorityPill } from "./HandOffTicket"
import type { Message } from "./types"

interface AgentDeskProps {
  handOff: HandOff
  phase: Phase
  messages: Message[]
  customerName: string
  sessionId: string
  onSend: (text: string) => void
}

const LABEL = "text-[11px] font-semibold uppercase tracking-[.08em] text-muted-foreground"
const time = (iso: string) => new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })

/** The human agent's side of the split: the case, the customer's live thread and a composer. */
export function AgentDesk({ handOff, phase, messages, customerName, sessionId, onSend }: AgentDeskProps) {
  const { lang, t } = useI18n()
  const [draft, setDraft] = useState("")
  const joined = phase === "joined"
  const sent = new Set(messages.filter(m => m.role === "human").map(m => m.content))

  const send = (e: FormEvent) => {
    e.preventDefault()
    if (!draft.trim()) return
    onSend(draft.trim())
    setDraft("")
  }

  return (
    <section aria-label={t("desk")} className="flex min-h-0 flex-col gap-2">
      <h2 className={LABEL}>{t("deskTitle")}</h2>
      <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-2xl border bg-card">
        <header className="flex items-center justify-between gap-3 border-b bg-page px-4 py-3">
          <div className="flex items-center gap-3">
            <span className="grid h-9 w-9 place-items-center rounded-full bg-human text-white">
              <User className="h-4 w-4" />
            </span>
            <div className="leading-tight">
              <p className="font-semibold">Laura Restrepo</p>
              <p className="text-xs text-muted-foreground">{t("lauraRole")}</p>
            </div>
          </div>
          <span
            className={`rounded-full border px-3 py-1 text-[11px] font-semibold uppercase tracking-[.06em] ${
              joined ? "border-ai text-ai" : "border-human text-human"
            }`}
          >
            {joined ? t("inConversation") : t("connectingDesk")}
          </span>
        </header>

        <div className="grid min-h-0 flex-1 gap-4 overflow-y-auto p-4 lg:grid-cols-[minmax(0,5fr)_minmax(0,6fr)]">
          <article
            style={HAND_OFF_TRANSITION}
            className="flex flex-col gap-3 self-start rounded-xl border border-human bg-human-bg/40 p-4"
          >
            <div className="flex items-center justify-between gap-2">
              <span className="flex items-center gap-2 font-mono text-sm font-semibold text-human">
                <Ticket className="h-4 w-4" />
                {handOff.hand_off_id}
                {!joined && (
                  <span className="rounded bg-human px-1.5 py-0.5 font-sans text-[10px] font-bold uppercase text-white">
                    {t("newBadge")}
                  </span>
                )}
              </span>
              <PriorityPill priority={handOff.priority} />
            </div>
            <div>
              <h3 className="text-xl font-semibold">{customerName || handOff.customer_id}</h3>
              <p className="text-sm text-muted-foreground">
                {t("queueLine", { queue: queueFor(handOff.reason, lang), reason: reasonLabel(handOff.reason, lang) })}
              </p>
            </div>
            <dl className="grid grid-cols-2 gap-3 text-sm">
              <div>
                <dt className={LABEL}>{t("customer")}</dt>
                <dd className="font-mono">{handOff.customer_id}</dd>
              </div>
              <div>
                <dt className={LABEL}>{t("queuedSince")}</dt>
                <dd className="font-mono">{time(handOff.at)}</dd>
              </div>
            </dl>
            <div>
              <h4 className={LABEL}>{t("assistantSummary")}</h4>
              <p className="mt-1 text-[15px] leading-relaxed">{handOff.summary}</p>
            </div>
            {handOff.related_ids.length > 0 && (
              <div className="flex flex-col gap-1.5">
                <h4 className={LABEL}>{t("relatedIds")}</h4>
                <IdChips ids={handOff.related_ids} />
              </div>
            )}
            <div>
              <h4 className={LABEL}>{t("alreadyTold")}</h4>
              <blockquote className="mt-1 border-l-2 border-human pl-3 text-sm text-muted-foreground">
                {handOff.goodbye}
              </blockquote>
            </div>
          </article>

          <div className="flex min-h-0 flex-col gap-3">
            <div className="flex items-center justify-between">
              <h4 className={LABEL}>{t("customerThread")}</h4>
              <span className="text-xs text-muted-foreground">{t("liveMirror")}</span>
            </div>
            <div className="min-h-[240px] flex-1 overflow-hidden rounded-xl border bg-page/60">
              <ChatMessages messages={messages} sessionId={sessionId} onFeedbackSubmit={async () => {}} hideFeedback />
            </div>

            <h4 className={LABEL}>{t("suggestedReplies")}</h4>
            {suggestedReplies(handOff, customerName, lang).map(reply =>
              sent.has(reply) ? (
                <p key={reply} className="flex items-start gap-2 rounded-lg border border-dashed p-3 text-sm text-muted-foreground">
                  <Check className="mt-0.5 h-4 w-4 flex-none text-ai" />
                  {reply}
                </p>
              ) : (
                <div key={reply} className="flex items-start justify-between gap-3 rounded-lg border border-dashed border-human/60 p-3 text-sm">
                  <span>{reply}</span>
                  <Button type="button" size="sm" variant="outline" className="border-human text-human" onClick={() => setDraft(reply)}>
                    {t("use")}
                  </Button>
                </div>
              )
            )}

            <form onSubmit={send} className="flex flex-col gap-1">
              <div className="flex items-end gap-2 rounded-xl border border-human/70 bg-card p-2 focus-within:ring-2 focus-within:ring-human/40">
                <Textarea
                  value={draft}
                  onChange={e => setDraft(e.target.value)}
                  placeholder={t("writeAsLaura")}
                  aria-label={t("lauraMessage")}
                  rows={2}
                  className="min-h-[44px] resize-none border-0 shadow-none focus-visible:ring-0"
                  autoFocus
                />
                <Button type="submit" disabled={!draft.trim()} className="bg-human hover:bg-human/90">
                  <Send className="mr-1 h-4 w-4" />
                  {t("send")}
                </Button>
              </div>
              {!joined && <p className="text-xs text-muted-foreground">{t("firstMessageHint")}</p>}
            </form>
          </div>
        </div>
      </div>
    </section>
  )
}
