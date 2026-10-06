import { useEffect, useRef, useState, type CSSProperties, type FormEvent } from "react"
import { Check, Send } from "lucide-react"
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

const LABEL = "text-xs font-medium text-muted-foreground"
const time = (iso: string) =>
  new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })

/** The human agent's side of the split: the case, the customer's live thread and a composer. */
export function AgentDesk({
  handOff,
  phase,
  messages,
  customerName,
  sessionId,
  onSend,
}: AgentDeskProps) {
  const { lang, t } = useI18n()
  const [draft, setDraft] = useState("")
  // Focus the composer without scrolling the desk: the case card's top must stay in view
  const composer = useRef<HTMLTextAreaElement>(null)
  useEffect(() => composer.current?.focus({ preventScroll: true }), [])
  const joined = phase === "joined"
  const sent = new Set(messages.filter(m => m.role === "human").map(m => m.content))

  const send = (e: FormEvent) => {
    e.preventDefault()
    if (!draft.trim()) return
    onSend(draft.trim())
    setDraft("")
  }

  return (
    <section aria-label={t("desk")} className="flex flex-col gap-2 min-[1100px]:min-h-0">
      <h2 className="px-2 text-sm font-medium text-muted-foreground">{t("deskTitle")}</h2>
      <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-[28px] border bg-card">
        <header className="flex items-center justify-between gap-3 border-b px-5 py-3">
          <div className="flex items-center gap-3">
            <span
              aria-hidden
              className="grid h-10 w-10 place-items-center rounded-full bg-mango text-lg font-bold text-[#161a33]"
            >
              L
            </span>
            <div className="leading-tight">
              <p className="font-semibold">Laura Restrepo</p>
              <p className="text-sm text-muted-foreground">{t("lauraRole")}</p>
            </div>
          </div>
          <span
            className={`flex items-center gap-2 rounded-full px-3 py-1 text-sm font-medium ${
              joined ? "bg-ok/10 text-ok" : "bg-human-bg text-human"
            }`}
          >
            <span
              className={`h-2 w-2 rounded-full ${joined ? "bg-ok" : "animate-pulse bg-mango"}`}
            />
            {joined ? t("inConversation") : t("connectingDesk")}
          </span>
        </header>

        <div className="grid min-h-0 flex-1 gap-5 overflow-y-auto p-5 lg:grid-cols-[minmax(0,5fr)_minmax(0,6fr)]">
          <article
            style={{ ...HAND_OFF_TRANSITION, "--perf": "4rem" } as CSSProperties}
            className="ticket flex flex-col self-start rounded-3xl bg-human-bg text-human"
          >
            <div className="flex h-16 items-center justify-between gap-3 px-5">
              <span className="flex items-center gap-2">
                <span className="display whitespace-nowrap text-2xl">{handOff.hand_off_id}</span>
                {!joined && (
                  <span className="rounded-full bg-mango px-2 py-0.5 text-xs font-bold text-[#161a33]">
                    {t("newBadge")}
                  </span>
                )}
              </span>
              <PriorityPill priority={handOff.priority} />
            </div>
            <div className="flex flex-col gap-4 px-5 pb-5 pt-5 text-foreground">
              <div>
                <h3 className="display text-4xl">{customerName || handOff.customer_id}</h3>
                <p className="mt-1.5 text-sm text-muted-foreground">
                  {t("queueLine", {
                    queue: queueFor(handOff.reason, lang),
                    reason: reasonLabel(handOff.reason, lang),
                  })}
                </p>
              </div>
              <dl className="grid grid-cols-2 gap-3 text-sm">
                <div>
                  <dt className={LABEL}>{t("customer")}</dt>
                  <dd className="figures mt-0.5 font-medium">{handOff.customer_id}</dd>
                </div>
                <div>
                  <dt className={LABEL}>{t("queuedSince")}</dt>
                  <dd className="figures mt-0.5 font-medium">{time(handOff.at)}</dd>
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
                <blockquote className="mt-1.5 rounded-2xl bg-card/80 px-4 py-3 text-sm leading-relaxed text-muted-foreground">
                  {handOff.goodbye}
                </blockquote>
              </div>
            </div>
          </article>

          <div className="flex min-h-0 flex-col gap-3">
            <div className="flex items-center justify-between px-1">
              <h4 className={LABEL}>{t("customerThread")}</h4>
              <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
                <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-ok" />
                {t("liveMirror")}
              </span>
            </div>
            <div className="min-h-[240px] flex-1 overflow-hidden rounded-3xl bg-page">
              <ChatMessages
                messages={messages}
                sessionId={sessionId}
                onFeedbackSubmit={async () => {}}
                hideFeedback
              />
            </div>

            <h4 className={`${LABEL} px-1`}>{t("suggestedReplies")}</h4>
            {suggestedReplies(handOff, customerName, lang).map(reply =>
              sent.has(reply) ? (
                <p
                  key={reply}
                  className="flex items-start gap-2 rounded-2xl bg-page px-4 py-3 text-sm text-muted-foreground"
                >
                  <Check className="mt-0.5 h-4 w-4 flex-none text-ok" />
                  {reply}
                </p>
              ) : (
                <div
                  key={reply}
                  className="flex items-start justify-between gap-3 rounded-2xl border border-mango/60 px-4 py-3 text-sm"
                >
                  <span>{reply}</span>
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    className="rounded-full border-mango text-human hover:bg-human-bg hover:text-human"
                    onClick={() => setDraft(reply)}
                  >
                    {t("use")}
                  </Button>
                </div>
              )
            )}

            <form onSubmit={send} className="flex flex-col gap-1.5">
              <div className="flex items-end gap-2 rounded-[22px] border bg-card p-2 pl-4 focus-within:border-mango focus-within:ring-4 focus-within:ring-mango/20">
                <Textarea
                  ref={composer}
                  value={draft}
                  onChange={e => setDraft(e.target.value)}
                  placeholder={t("writeAsLaura")}
                  aria-label={t("lauraMessage")}
                  rows={2}
                  className="min-h-[44px] resize-none border-0 bg-transparent px-0 shadow-none focus-visible:ring-0 focus-visible:ring-offset-0 dark:bg-transparent"
                />
                <Button
                  type="submit"
                  disabled={!draft.trim()}
                  className="rounded-full bg-mango text-[#161a33] hover:bg-mango/90"
                >
                  <Send className="h-4 w-4" />
                  {t("send")}
                </Button>
              </div>
              {!joined && (
                <p className="px-2 text-xs text-muted-foreground">{t("firstMessageHint")}</p>
              )}
            </form>
          </div>
        </div>
      </div>
    </section>
  )
}
