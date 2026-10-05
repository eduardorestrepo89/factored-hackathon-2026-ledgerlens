import { createContext, useContext, useEffect, useId, useRef, useState } from "react"
import { Check, Fingerprint, ShieldAlert, UserRound, X } from "lucide-react"
import { Button } from "@/components/ui/button"
import { bareToolName } from "@/hooks/useToolRenderer"
import { useI18n } from "@/lib/i18n"
import type { BiometricCheck, Confirmation } from "./types"

/** Answers a confirmation. Only the customer's live chat provides it, so the desk mirror and the phone show no buttons. */
export const ConfirmContext = createContext<
  ((c: Confirmation, approved: boolean, label: string, check?: BiometricCheck) => void) | null
>(null)

export const SCAN_MS = 3000

const ANSWERED = {
  yes: { key: "confirmYes", Icon: Check },
  verified: { key: "confirmVerified", Icon: Check },
  no: { key: "confirmNo", Icon: X },
  unverified: { key: "confirmUnverified", Icon: X },
  typed: { key: "confirmTyped", Icon: null },
} as const

/**
 * The Yes/No card for a tool call the agent paused (agent tools/confirmation_hook.py). Only a
 * click on Yes runs the call; the backend treats anything else as No. A card block asks for a
 * biometric check after Yes, and only a passed check sends the Yes.
 */
export function ConfirmCard({ confirm }: { confirm: Confirmation }) {
  const { t } = useI18n()
  const answer = useContext(ConfirmContext)
  const titleId = useId()
  const no = useRef<HTMLButtonElement>(null)
  const tool = bareToolName(confirm.tool)
  const handOff = tool === "human_agent_hand_off"
  const block = tool === "block_credit_card"
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
  const [scanning, setScanning] = useState(false)
  useEffect(() => {
    if (open) no.current?.focus({ preventScroll: true })
  }, [open, scanning])

  const scan = useRef<ReturnType<typeof setTimeout>>(undefined)
  // A card that goes away mid-check (a new chat) never approves afterwards
  useEffect(() => () => clearTimeout(scan.current), [])
  const yes = () => {
    if (!answer) return
    if (!block) return answer(confirm, true, t("confirmYes"))
    // ponytail: a demo check that always passes, Cancelar is its only failure; the bank's step-up auth (WebAuthn, OTP) goes here
    setScanning(true)
    scan.current = setTimeout(() => answer(confirm, true, t("confirmYes"), "verified"), SCAN_MS)
  }
  const cancel = () => {
    clearTimeout(scan.current)
    answer?.(confirm, false, t("confirmNo"), "unverified")
  }
  const done = confirm.answer && ANSWERED[confirm.answer]

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
      {done ? (
        <p className="ml-12 inline-flex items-center gap-1.5 text-sm text-muted-foreground">
          {done.Icon && <done.Icon className={`h-4 w-4 ${done.Icon === Check ? "text-ok" : ""}`} />}
          {t(done.key)}
        </p>
      ) : scanning ? (
        <div className="flex flex-col items-center gap-1 pt-1">
          <span className="relative grid h-16 w-16 place-items-center rounded-full bg-ai-bg text-ai">
            <span className="absolute inset-0 rounded-full bg-ai/20 motion-safe:animate-ping" />
            <Fingerprint className="h-9 w-9" />
          </span>
          <p role="status" className="mt-2 text-sm font-medium">
            {t("confirmScanning")}
          </p>
          <p className="text-xs text-muted-foreground">{t("confirmScanHint")}</p>
          <Button ref={no} variant="outline" className="self-end rounded-full px-5" onClick={cancel}>
            {t("cancel")}
          </Button>
        </div>
      ) : (
        answer && (
          <div className="flex justify-end gap-2">
            <Button ref={no} variant="outline" className="rounded-full px-5" onClick={() => answer(confirm, false, t("confirmNo"))}>
              {t("confirmNo")}
            </Button>
            <Button className="rounded-full px-5" onClick={yes}>
              {t("confirmYes")}
            </Button>
          </div>
        )
      )}
    </section>
  )
}
