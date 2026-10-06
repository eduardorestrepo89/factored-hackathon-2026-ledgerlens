import { useState, type CSSProperties } from "react"
import { Button } from "@/components/ui/button"
import { LogOut, Moon, Plus, Sun } from "lucide-react"
import { useAuth } from "@/hooks/useAuth"
import type { Phase } from "@/lib/handoff"
import { LANGS, useI18n, type Lang } from "@/lib/i18n"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog"

type ChatHeaderProps = {
  title?: string | undefined
  onNewChat: () => void
  canStartNewChat: boolean
  phase?: Phase
}

/** A lens seen edge-on, as two halves: the AI (cobalt) and a person (mango). public/favicon.svg draws the same. */
export const LENS_HALVES = {
  ai: "M15.2 2.5A18.2 18.2 0 0 0 15.2 29.5Z",
  human: "M16.8 2.5A18.2 18.2 0 0 1 16.8 29.5Z",
}

/** The brand mark. The half that doesn't own the conversation is drawn as an outline. */
export function LensMark({
  className = "h-8 w-8",
  phase = "connecting",
}: {
  className?: string
  phase?: Phase
}) {
  const half = (on: boolean, color: string): CSSProperties =>
    on
      ? { fill: color }
      : { fill: "none", stroke: color, strokeWidth: 1.5, strokeLinejoin: "round" }
  return (
    <svg aria-hidden viewBox="0 0 32 32" className={`shrink-0 ${className}`}>
      <path d={LENS_HALVES.ai} style={half(phase !== "joined", "var(--ai)")} />
      <path d={LENS_HALVES.human} style={half(phase !== "ai", "var(--mango)")} />
    </svg>
  )
}

/** Who owns the conversation, in words; the band under the header shows it in color. */
function StatusTrack({ phase }: { phase: Phase }) {
  const { t } = useI18n()
  const human = phase !== "ai"
  return (
    <p className="hidden items-center gap-2 text-sm font-medium md:flex" aria-live="polite">
      <span
        className={`h-2 w-2 rounded-full ${human ? "bg-mango" : "bg-ai"} ${phase === "connecting" ? "animate-pulse" : ""}`}
      />
      <span className={human ? "text-human" : "text-ai"}>
        {phase === "ai"
          ? t("ownerAi")
          : phase === "connecting"
            ? t("connectingToPerson")
            : t("ownerHuman")}
      </span>
    </p>
  )
}

export function LanguageSelect() {
  const { lang, setLang, t } = useI18n()
  return (
    <select
      value={lang}
      onChange={e => setLang(e.target.value as Lang)}
      aria-label={t("language")}
      className="h-9 cursor-pointer rounded-full border bg-card px-2 text-sm font-medium sm:px-3"
    >
      {LANGS.map(l => (
        <option key={l.code} value={l.code}>
          {l.label}
        </option>
      ))}
    </select>
  )
}

/** Flips the `dark` class main.tsx set before the first paint, and remembers the choice. */
export function ThemeToggle() {
  const { t } = useI18n()
  const [dark, setDark] = useState(() => document.documentElement.classList.contains("dark"))
  const toggle = () => {
    document.documentElement.classList.toggle("dark", !dark)
    try {
      localStorage.setItem("theme", dark ? "light" : "dark")
    } catch {
      // the choice still applies for this visit
    }
    setDark(!dark)
  }
  const label = dark ? t("lightMode") : t("darkMode")
  return (
    <Button
      variant="ghost"
      size="icon"
      className="shrink-0 rounded-full"
      onClick={toggle}
      aria-label={label}
      title={label}
    >
      {dark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
    </Button>
  )
}

export function ChatHeader({ title, onNewChat, canStartNewChat, phase = "ai" }: ChatHeaderProps) {
  const { isAuthenticated, signOut } = useAuth()
  const { t } = useI18n()

  return (
    <header className="w-full bg-card">
      <div className="flex h-16 items-center justify-between gap-2 px-3 sm:gap-4 sm:px-6">
        <div className="flex items-center gap-3">
          <LensMark />
          <div className="leading-none">
            <h1 className="display text-2xl font-medium">{title || "LedgerLens"}</h1>
            <p className="mt-0.5 text-xs text-muted-foreground">LATAM Bank</p>
          </div>
        </div>
        <StatusTrack phase={phase} />
        <div className="flex items-center gap-1 sm:gap-1.5">
          <LanguageSelect />
          <ThemeToggle />
          <Button
            onClick={onNewChat}
            variant="outline"
            className="gap-2 rounded-full max-sm:w-9 max-sm:px-0"
            disabled={!canStartNewChat}
            aria-label={t("newChat")}
          >
            <Plus className="h-4 w-4" />
            <span className="max-sm:sr-only">{t("newChat")}</span>
          </Button>
          {isAuthenticated && (
            <AlertDialog>
              <AlertDialogTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon"
                  className="rounded-full"
                  aria-label={t("logout")}
                  title={t("logout")}
                >
                  <LogOut className="h-4 w-4" />
                </Button>
              </AlertDialogTrigger>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle>{t("logoutTitle")}</AlertDialogTitle>
                  <AlertDialogDescription>{t("logoutBody")}</AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                  <AlertDialogCancel>{t("cancel")}</AlertDialogCancel>
                  <AlertDialogAction onClick={() => signOut()}>{t("logout")}</AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
          )}
        </div>
      </div>
      {/* The band changes owner with the conversation: cobalt for the AI, mango once a person has it */}
      <div aria-hidden data-phase={phase} className="band h-1.5 w-full" />
    </header>
  )
}
