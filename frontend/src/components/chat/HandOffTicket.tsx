import type { CSSProperties } from "react"
import { Loader2, Ticket } from "lucide-react"
import type { ToolRenderProps } from "@/hooks/useToolRenderer"
import { parseHandOffResult, reasonLabel } from "@/lib/handoff"
import { useI18n } from "@/lib/i18n"
import { ToolCallDisplay } from "./ToolCallDisplay"

/** The split's shared element: the ticket in the chat, then the case card on the desk. */
export const HAND_OFF_TRANSITION = { viewTransitionName: "handoff-ticket" } as CSSProperties

export function PriorityPill({ priority }: { priority: string }) {
  const { t } = useI18n()
  return priority === "high" ? (
    <span className="rounded-full border border-destructive px-2 py-0.5 text-[11px] font-semibold text-destructive">
      {t("priorityHigh")}
    </span>
  ) : (
    <span className="rounded-full border bg-muted px-2 py-0.5 text-[11px] font-semibold text-muted-foreground">
      {t("priorityNormal")}
    </span>
  )
}

export function IdChips({ ids }: { ids: string[] }) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {ids.map(id => (
        <span key={id} className="rounded-full border bg-card px-2 py-0.5 font-mono text-[11px]">
          {id}
        </span>
      ))}
    </div>
  )
}

/** Renders human_agent_hand_off: a spinner while it runs, then the case ticket. */
export function HandOffTicket({ tagged, ...props }: ToolRenderProps & { tagged: boolean }) {
  const { lang, t } = useI18n()
  if (props.status !== "complete") {
    return (
      <div className="flex items-center gap-2 text-sm text-human">
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
        {t("handingOff")}
      </div>
    )
  }
  const result = parseHandOffResult(props.result)
  if (!result) return <ToolCallDisplay {...props} />
  return (
    <div
      style={tagged ? HAND_OFF_TRANSITION : undefined}
      className="flex w-full max-w-md flex-col gap-2 rounded-xl border border-human bg-human-bg p-3 animate-in fade-in slide-in-from-bottom-1 duration-200"
    >
      <div className="flex items-center justify-between gap-2">
        <span className="flex items-center gap-2 font-mono text-sm font-semibold text-human">
          <Ticket className="h-4 w-4" />
          {t("caseId", { id: result.hand_off_id })}
        </span>
        <PriorityPill priority={result.priority} />
      </div>
      <span className="text-sm">{reasonLabel(result.reason, lang)}</span>
      {result.related_ids.length > 0 && <IdChips ids={result.related_ids} />}
      <span className="text-xs text-human">{t("sentToPerson")}</span>
    </div>
  )
}
