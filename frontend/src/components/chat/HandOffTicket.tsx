import type { CSSProperties } from "react"
import { Loader2 } from "lucide-react"
import type { ToolRenderProps } from "@/hooks/useToolRenderer"
import { parseHandOffResult, reasonLabel } from "@/lib/handoff"
import { useI18n } from "@/lib/i18n"
import { ToolCallDisplay } from "./ToolCallDisplay"

/** The split's shared element: the ticket in the chat, then the case card on the desk. */
export const HAND_OFF_TRANSITION = { viewTransitionName: "handoff-ticket" } as CSSProperties

export function PriorityPill({ priority }: { priority: string }) {
  const { t } = useI18n()
  return priority === "high" ? (
    <span className="shrink-0 rounded-full bg-destructive/10 px-2.5 py-0.5 text-xs font-semibold text-destructive">
      {t("priorityHigh")}
    </span>
  ) : (
    <span className="shrink-0 rounded-full bg-muted px-2.5 py-0.5 text-xs font-semibold text-muted-foreground">
      {t("priorityNormal")}
    </span>
  )
}

export function IdChips({ ids }: { ids: string[] }) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {ids.map(id => (
        <span key={id} className="figures rounded-full bg-card px-2.5 py-0.5 text-xs text-foreground ring-1 ring-border">
          {id}
        </span>
      ))}
    </div>
  )
}

/** Renders human_agent_hand_off: a spinner while it runs, then the case as a branch turn ticket. */
export function HandOffTicket({ tagged, ...props }: ToolRenderProps & { tagged: boolean }) {
  const { lang, t } = useI18n()
  if (props.status !== "complete") {
    return (
      <div className="flex items-center gap-2 text-sm font-medium text-human">
        <Loader2 className="h-4 w-4 animate-spin" />
        {t("handingOff")}
      </div>
    )
  }
  const result = parseHandOffResult(props.result)
  if (!result) return <ToolCallDisplay {...props} />
  return (
    <div
      style={tagged ? HAND_OFF_TRANSITION : undefined}
      className="ticket flex w-full max-w-sm flex-col rounded-2xl bg-human-bg text-human animate-in fade-in slide-in-from-bottom-1 duration-200"
    >
      <div className="flex h-13 items-center justify-between gap-3 px-4">
        <span className="display whitespace-nowrap text-xl">{t("caseId", { id: result.hand_off_id })}</span>
        <PriorityPill priority={result.priority} />
      </div>
      <div className="flex flex-col gap-2.5 px-4 pb-4 pt-3.5 text-foreground">
        <span className="font-medium">{reasonLabel(result.reason, lang)}</span>
        {result.related_ids.length > 0 && <IdChips ids={result.related_ids} />}
        <span className="flex items-center gap-2 text-sm font-medium text-human">
          <span className="h-2 w-2 rounded-full bg-mango" />
          {t("sentToPerson")}
        </span>
      </div>
    </div>
  )
}
