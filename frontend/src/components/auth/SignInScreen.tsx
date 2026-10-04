import { useId, useRef, type CSSProperties, type PointerEvent } from "react"
import { Button } from "@/components/ui/button"
import { LanguageSelect, LensMark, ThemeToggle } from "@/components/chat/ChatHeader"
import { useI18n } from "@/lib/i18n"

/**
 * The band's lines, drawn in SVG: cobalt lines (the AI) fade out down the slab while mango
 * lines (a person) fade in. SVG, not the CSS .band, because Chrome rasterizes large CSS
 * masks in tiles and the seams show at this size.
 */
function Stripes() {
  const id = useId()
  return (
    <svg aria-hidden className="absolute inset-0 h-full w-full">
      <defs>
        <linearGradient id={`${id}ai`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0.1" style={{ stopColor: "var(--ai)" }} />
          <stop offset="0.8" style={{ stopColor: "var(--ai)", stopOpacity: 0 }} />
        </linearGradient>
        <linearGradient id={`${id}human`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0.2" style={{ stopColor: "var(--mango)", stopOpacity: 0 }} />
          <stop offset="0.9" style={{ stopColor: "var(--mango)" }} />
        </linearGradient>
        <pattern id={`${id}lines`} width="8" height="100%" patternUnits="userSpaceOnUse">
          <rect width="3" height="100%" fill={`url(#${id}ai)`} />
          <rect x="4" width="3" height="100%" fill={`url(#${id}human)`} />
        </pattern>
      </defs>
      <rect width="100%" height="100%" fill={`url(#${id}lines)`} />
    </svg>
  )
}

/**
 * The band as a tall slab with a lens over it: the lens follows the pointer and shows the
 * lines magnified, so the cobalt and mango lines that blend at a distance come apart.
 */
function LensSlab() {
  const ref = useRef<HTMLDivElement>(null)
  const move = (e: PointerEvent) => {
    const el = ref.current
    if (!el) return
    const r = el.getBoundingClientRect()
    el.style.setProperty("--x", `${e.clientX - r.left}px`)
    el.style.setProperty("--y", `${e.clientY - r.top}px`)
  }
  // ponytail: the slab is decorative, so the lens only answers a pointer; keyboards skip it
  return (
    <div
      ref={ref}
      aria-hidden
      onPointerMove={move}
      style={{ "--x": "50cqw", "--y": "48cqh", "--r": "clamp(64px, 9vw, 128px)", containerType: "size" } as CSSProperties}
      className="relative h-full overflow-hidden rounded-[32px] bg-card"
    >
      <Stripes />
      <div
        className="absolute rounded-full shadow-[0_24px_50px_-20px_rgb(22_26_51/.55)] ring-1 ring-border"
        style={{
          left: "calc(var(--x) - var(--r))",
          top: "calc(var(--y) - var(--r))",
          width: "calc(var(--r) * 2)",
          height: "calc(var(--r) * 2)",
        }}
      >
        {/* clip-path, not overflow: Chrome lets scaled layers bleed past a rounded overflow */}
        <div className="absolute inset-0 bg-card [clip-path:circle(50%)]">
          {/* The same lines, scaled about the lens center */}
          <div
            className="absolute h-[100cqh] w-[100cqw]"
            style={{
              left: "calc(var(--r) - var(--x))",
              top: "calc(var(--r) - var(--y))",
              transform: "scale(1.9)",
              transformOrigin: "var(--x) var(--y)",
            }}
          >
            <Stripes />
          </div>
        </div>
        <div className="absolute inset-0 rounded-full bg-[radial-gradient(circle_at_30%_25%,rgb(255_255_255/.28),transparent_40%)]" />
      </div>
    </div>
  )
}

/** The first screen: what LedgerLens does, and the way in. */
export function SignInScreen({ onSignIn }: { onSignIn: () => void }) {
  const { t } = useI18n()
  return (
    <main className="grid min-h-screen grid-rows-[auto_1fr] gap-4 bg-page p-4 sm:p-6 lg:grid-cols-[minmax(0,7fr)_minmax(0,5fr)] lg:grid-rows-1 lg:gap-6">
      <div className="h-44 lg:order-2 lg:h-auto">
        <LensSlab />
      </div>
      <div className="flex flex-col justify-between gap-12 px-2 py-4 sm:px-6 lg:py-6">
        <div className="flex items-center justify-between gap-3">
          <span className="flex items-center gap-3">
            <LensMark />
            <span className="leading-none">
              <span className="display block text-2xl">LedgerLens</span>
              <span className="mt-0.5 block text-xs text-muted-foreground">LATAM Bank</span>
            </span>
          </span>
          <span className="flex items-center gap-1.5">
            <LanguageSelect />
            <ThemeToggle />
          </span>
        </div>

        <div className="max-w-2xl">
          <h1 className="display text-balance text-[clamp(3.5rem,8vw,8.5rem)]">{t("signInTitle")}</h1>
          <p className="mt-6 max-w-[46ch] text-lg leading-relaxed text-muted-foreground">{t("signInBody")}</p>
          <Button
            onClick={onSignIn}
            className="mt-10 h-12 rounded-full px-8 text-base"
          >
            {t("signIn")}
          </Button>
        </div>

        <p className="text-sm text-muted-foreground">Factored AI &amp; Data Hackathon 2026</p>
      </div>
    </main>
  )
}

/** Full-screen wait while auth settles. */
export function Splash() {
  const { t } = useI18n()
  return (
    <div role="status" className="grid min-h-screen place-items-center bg-page">
      <span className="flex items-center gap-3 text-muted-foreground">
        <LensMark className="h-8 w-8 animate-pulse" />
        {t("loading")}
      </span>
    </div>
  )
}
