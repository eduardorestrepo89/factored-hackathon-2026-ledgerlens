import { afterEach, describe, it, expect, vi } from "vitest"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { ChatHeader } from "@/components/chat/ChatHeader"
import { LanguageProvider } from "@/lib/i18n"
import { reasonLabel } from "@/lib/handoff"

vi.mock("@/hooks/useAuth", () => ({ useAuth: () => ({ isAuthenticated: false, signOut: vi.fn() }) }))

afterEach(() => {
  localStorage.clear()
  document.documentElement.classList.remove("dark")
})

describe("language and theme", () => {
  it("switches the UI language and remembers it", async () => {
    const user = userEvent.setup()
    render(
      <LanguageProvider>
        <ChatHeader onNewChat={() => {}} canStartNewChat />
      </LanguageProvider>
    )
    expect(screen.getByRole("button", { name: /Nueva conversación/ })).toBeInTheDocument()

    await user.selectOptions(screen.getByLabelText("Idioma"), "en")

    expect(screen.getByRole("button", { name: /New conversation/ })).toBeInTheDocument()
    expect(document.documentElement.lang).toBe("en")
    expect(localStorage.getItem("lang")).toBe("en")
  })

  it("toggles dark mode and remembers it", async () => {
    const user = userEvent.setup()
    render(<ChatHeader onNewChat={() => {}} canStartNewChat />)

    await user.click(screen.getByRole("button", { name: "Modo oscuro" }))

    expect(document.documentElement.classList.contains("dark")).toBe(true)
    expect(localStorage.getItem("theme")).toBe("dark")
    expect(screen.getByRole("button", { name: "Modo claro" })).toBeInTheDocument()
  })

  it("translates hand-off labels, passing unknown reasons through", () => {
    expect(reasonLabel("FRAUD_CONFIRMED", "pt")).toBe("Cobrança não reconhecida")
    expect(reasonLabel("FRAUD_CONFIRMED", "en")).toBe("Unrecognized charge")
    expect(reasonLabel("SOMETHING_NEW", "en")).toBe("SOMETHING_NEW")
  })
})
