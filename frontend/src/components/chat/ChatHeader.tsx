import { Button } from "@/components/ui/button"
import { Check, Plus, ShieldCheck } from "lucide-react"
import { useAuth } from "@/hooks/useAuth"
import type { Phase } from "@/lib/handoff"
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
  const human = phase !== "ai"
  return (
    <div className="hidden items-center gap-3 md:flex" aria-live="polite">
      <span className={`${STEP} text-ai`}>
        {human ? <Check className="h-3.5 w-3.5" /> : <span className="h-2 w-2 rounded-full bg-ai" />}
        Asistente IA
      </span>
      <span className="h-px w-8 bg-border" />
      <span className={`${STEP} ${human ? "text-human" : "text-muted-foreground/60"}`}>
        <span
          className={`h-2 w-2 rounded-full ${human ? "bg-human" : "bg-muted-foreground/30"} ${
            phase === "connecting" ? "animate-pulse" : ""
          }`}
        />
        {human ? "Persona · Laura" : "Persona"}
        {phase === "connecting" && <span className="font-normal normal-case tracking-normal">conectando</span>}
      </span>
    </div>
  )
}

export function ChatHeader({ title, onNewChat, canStartNewChat, phase = "ai" }: ChatHeaderProps) {
  const { isAuthenticated, signOut } = useAuth()

  return (
    <header className="flex h-14 w-full items-center justify-between gap-4 border-b bg-white px-4">
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
        <Button onClick={onNewChat} variant="outline" className="gap-2" disabled={!canStartNewChat}>
          <Plus className="h-4 w-4" />
          Nueva conversación
        </Button>
        {isAuthenticated && (
          <AlertDialog>
            <AlertDialogTrigger asChild>
              <Button variant="outline">Logout</Button>
            </AlertDialogTrigger>
            <AlertDialogContent>
              <AlertDialogHeader>
                <AlertDialogTitle>Confirm Logout</AlertDialogTitle>
                <AlertDialogDescription>
                  Are you sure you want to log out? You will need to sign in again to access your
                  account.
                </AlertDialogDescription>
              </AlertDialogHeader>
              <AlertDialogFooter>
                <AlertDialogCancel>Cancel</AlertDialogCancel>
                <AlertDialogAction onClick={() => signOut()}>Confirm</AlertDialogAction>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
        )}
      </div>
    </header>
  )
}
