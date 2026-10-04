import { createContext, useContext, useEffect, useId, useRef } from "react"
import { Check, ShieldAlert, UserRound, X } from "lucide-react"
import { Button } from "@/components/ui/button"
import { bareToolName } from "@/hooks/useToolRenderer"
import { useI18n } from "@/lib/i18n"
import type { Confirmation } from "./types"

/** Answers a confirmation. Only the customer's live chat provides it, so the desk mirror and the phone show no buttons. */
export const ConfirmContext = createContext<((c: Confirmation, approved: boolean, label: string) => void) | null>(null)

/**
 * The Yes/No card for a tool call the agent paused (agent tools/confirmation_hook.py). Only a
 * click on Yes runs the call; the backend treats anything else as No.
 */
export function ConfirmCard({ confirm }: { confirm: Confirmation }) {
  const { t } = useI18n()
  const answer = useContext(ConfirmContext)
  const titleId = useId()
  const no = useRef<HTMLButtonElement>(null)
  const tool = bareToolName(confirm.tool)
  const handOff = tool === "human_agent_hand_off"
  const ids = confirm.details.transaction_ids
  const count = Array.isArray(ids) ? ids.length : 1

  const [title, body] =
    tool === "open_claim"
      ? [t("confirmClaimTitle"), count === 1 ? t("confirmClaimOne") : t("confirmClaimMany", { n: String(count) })]
      : handOff
        ? [t("confirmHandOffTitle"), t("confirmHandOffBody")]
        : tool === "block_credit_card"
          ? [t("confirmBlockTitle", { last4: String(confirm.details.card_last4 ?? "") }), t("confirmBlockBody")]
          : [tool, ""]

  // While it's open the composer is locked: keyboard focus goes to the safe choice
  const open = !confirm.answer && answer !== null
  useEffect(() => {
    if (open) no.current?.focus({ preventScroll: true })
  }, [open])

  const Icon = handOff ? UserRound : ShieldAlert
  return (
    <section
      role="group"
      aria-labelledby={titleId}
      className="flex w-full max-w-md flex-col gap-3 rounded-3xl border border-mango/60 bg-card p-4 shadow-[0_12px_30px_-20px_rgb(22_26_51/.45)]"
    >
      <div className="flex items-start gap-3">
        <span className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-human-bg text-human">
          <Icon className="h-5 w-5" />
        </span>
        <div>
          <h3 id={titleId} className="font-semibold">
            {title}
          </h3>
          {body && <p className="mt-0.5 text-sm text-muted-foreground">{body}</p>}
        </div>
      </div>
      {confirm.answer ? (
        <p className="ml-12 inline-flex items-center gap-1.5 text-sm text-muted-foreground">
          {confirm.answer === "yes" ? (
            <Check className="h-4 w-4 text-ok" />
          ) : confirm.answer === "no" ? (
            <X className="h-4 w-4" />
          ) : null}
          {t(confirm.answer === "yes" ? "confirmYes" : confirm.answer === "no" ? "confirmNo" : "confirmTyped")}
        </p>
      ) : (
        answer && (
          <div className="flex justify-end gap-2">
            <Button ref={no} variant="outline" className="rounded-full px-5" onClick={() => answer(confirm, false, t("confirmNo"))}>
              {t("confirmNo")}
            </Button>
            <Button className="rounded-full px-5" onClick={() => answer(confirm, true, t("confirmYes"))}>
              {t("confirmYes")}
            </Button>
          </div>
        )
      )}
    </section>
  )
}
