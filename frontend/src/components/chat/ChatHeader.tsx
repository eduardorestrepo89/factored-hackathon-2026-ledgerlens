import { useState } from "react"
import { Button } from "@/components/ui/button"
import { Check, Moon, Plus, ShieldCheck, Sun } from "lucide-react"
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

const STEP = "flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-[.08em]"

/** Who owns the conversation: the AI assistant, then the person it handed off to. */
function StatusTrack({ phase }: { phase: Phase }) {
  const { t } = useI18n()
  const human = phase !== "ai"
  return (
    <div className="hidden items-center gap-3 md:flex" aria-live="polite">
      <span className={`${STEP} text-ai`}>
        {human ? <Check className="h-3.5 w-3.5" /> : <span className="h-2 w-2 rounded-full bg-ai" />}
        LedgerLens AI
      </span>
      <span className="h-px w-8 bg-border" />
      <span className={`${STEP} ${human ? "text-human" : "text-muted-foreground/60"}`}>
        <span
          className={`h-2 w-2 rounded-full ${human ? "bg-human" : "bg-muted-foreground/30"} ${
            phase === "connecting" ? "animate-pulse" : ""
          }`}
        />
        {human ? t("personLaura") : t("person")}
        {phase === "connecting" && <span className="font-normal normal-case tracking-normal">{t("connecting")}</span>}
      </span>
    </div>
  )
}

/** Flips the `dark` class main.tsx set before the first paint, and remembers the choice. */
function ThemeToggle() {
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
    <Button variant="outline" size="icon" onClick={toggle} aria-label={label} title={label}>
      {dark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
    </Button>
  )
}

export function ChatHeader({ title, onNewChat, canStartNewChat, phase = "ai" }: ChatHeaderProps) {
  const { isAuthenticated, signOut } = useAuth()
  const { lang, setLang, t } = useI18n()

  return (
    <header className="flex h-14 w-full items-center justify-between gap-4 border-b bg-card px-4">
      <div className="flex items-center gap-2">
        <span className="grid h-8 w-8 place-items-center rounded-lg bg-brand-dark text-white">
          <ShieldCheck className="h-4 w-4" />
        </span>
        <div className="leading-tight">
          <h1 className="text-base font-bold">{title || "LedgerLens"}</h1>
          <p className="text-xs text-muted-foreground">LATAM Bank</p>
        </div>
      </div>
      <StatusTrack phase={phase} />
      <div className="flex items-center gap-2">
        <select
          value={lang}
          onChange={e => setLang(e.target.value as Lang)}
          aria-label={t("language")}
          className="h-9 rounded-md border bg-background px-2 text-sm"
        >
          {LANGS.map(l => (
            <option key={l.code} value={l.code}>
              {l.label}
            </option>
          ))}
        </select>
        <ThemeToggle />
        <Button onClick={onNewChat} variant="outline" className="gap-2" disabled={!canStartNewChat}>
          <Plus className="h-4 w-4" />
          {t("newChat")}
        </Button>
        {isAuthenticated && (
          <AlertDialog>
            <AlertDialogTrigger asChild>
              <Button variant="outline">{t("logout")}</Button>
            </AlertDialogTrigger>
            <AlertDialogContent>
              <AlertDialogHeader>
                <AlertDialogTitle>{t("logoutTitle")}</AlertDialogTitle>
                <AlertDialogDescription>{t("logoutBody")}</AlertDialogDescription>
              </AlertDialogHeader>
              <AlertDialogFooter>
                <AlertDialogCancel>{t("cancel")}</AlertDialogCancel>
                <AlertDialogAction onClick={() => signOut()}>{t("confirm")}</AlertDialogAction>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
        )}
      </div>
    </header>
  )
}
