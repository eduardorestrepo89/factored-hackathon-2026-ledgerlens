"use client"

import { useState } from "react"
import { Check, ChevronDown, Loader2 } from "lucide-react"
import { bareToolName, type ToolRenderProps } from "@/hooks/useToolRenderer"
import { hasKey, useI18n } from "@/lib/i18n"

/** A tool call as one line in plain words; it opens to the raw input and result. */
export function ToolCallDisplay({ name, args, status, result }: ToolRenderProps) {
  const { t } = useI18n()
  const [expanded, setExpanded] = useState(false)
  const bare = bareToolName(name)
  const key = `tool.${bare}`
  const done = status === "complete"

  return (
    <div className="text-sm">
      <button
        type="button"
        onClick={() => setExpanded(!expanded)}
        aria-expanded={expanded}
        className="inline-flex items-center gap-2 rounded-full border bg-card py-1 pl-1 pr-3 text-muted-foreground transition-colors hover:text-foreground"
      >
        <span
          className={`grid h-6 w-6 place-items-center rounded-full ${done ? "bg-ai-bg text-ai" : "text-ai"}`}
        >
          {done ? (
            <Check size={13} strokeWidth={3} />
          ) : (
            <Loader2 size={15} className="animate-spin" />
          )}
        </span>
        {hasKey(key) ? t(key) : bare}
        <ChevronDown size={14} className={`transition-transform ${expanded ? "rotate-180" : ""}`} />
      </button>

      {expanded && (
        <div className="mt-2 space-y-2 rounded-2xl border bg-card p-3">
          <p className="figures text-xs font-medium text-muted-foreground">{bare}</p>
          {args && (
            <div>
              <div className="text-xs text-muted-foreground">{t("toolInput")}</div>
              <pre className="figures mt-0.5 whitespace-pre-wrap break-words text-xs text-foreground/80">
                {args}
              </pre>
            </div>
          )}
          {result && (
            <div>
              <div className="text-xs text-muted-foreground">{t("toolResult")}</div>
              <pre className="figures mt-0.5 whitespace-pre-wrap break-words text-xs text-foreground/80">
                {result}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
