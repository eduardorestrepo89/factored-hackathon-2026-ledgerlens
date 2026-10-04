import { describe, it, expect, vi, beforeEach } from "vitest"
import { render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import ChatInterface from "@/components/chat/ChatInterface"
import { GlobalContextProvider } from "@/app/context/GlobalContext"

const { invoke, created } = vi.hoisted(() => ({ invoke: vi.fn(), created: vi.fn() }))

vi.mock("@/lib/agentcore-client", () => ({
  AgentCoreClient: class {
    invoke = invoke
    constructor(config: unknown) {
      created(config)
    }
  },
}))
vi.mock("react-oidc-context", () => ({
  useAuth: () => ({ user: { access_token: "token", id_token: "id", profile: { name: "Carlos Rendón" } } }),
}))
vi.mock("@/hooks/useAuth", () => ({ useAuth: () => ({ isAuthenticated: false, signOut: vi.fn() }) }))

const HAND_OFF = {
  hand_off_id: "HO-7Q3KX2MA",
  status: "queued",
  priority: "high",
  reason: "FRAUD_CONFIRMED",
  customer_id: "CLI-F2DZJYU0POJ9",
  summary: "No reconoce 2 cargos en Miami.",
  related_ids: ["TX-88", "TX-89"],
}
const GOODBYE = "Carlos, una persona del equipo de fraudes sigue contigo desde aquí."
const DESK = { name: "Escritorio del agente" }

type OnEvent = (event: Record<string, unknown>) => void

/** The agent's next turn: a line, the hand-off tool returning `result`, then the goodbye. */
function agentTurn(result: string) {
  invoke.mockImplementationOnce(async (_message: string, _session: string, _token: string, onEvent: OnEvent) => {
    onEvent({ type: "text", content: "Te paso con una persona." })
    onEvent({ type: "tool_use_start", toolUseId: "t1", name: "human-agent-hand-off-target___human_agent_hand_off" })
    onEvent({ type: "tool_result", toolUseId: "t1", result })
    onEvent({ type: "text", content: GOODBYE })
  })
}

async function startChat() {
  render(
    <GlobalContextProvider>
      <ChatInterface />
    </GlobalContextProvider>
  )
  await waitFor(() => expect(created).toHaveBeenCalled())
}

/** Waits until the turn has finished streaming (the send button stops saying "Pensando…"). */
const turnFinished = () => waitFor(() => expect(screen.queryByText("Pensando…")).toBeNull())
const pause = (ms: number) => new Promise(resolve => setTimeout(resolve, ms))

beforeEach(() => {
  invoke.mockReset()
  created.mockReset()
  Element.prototype.scrollIntoView = vi.fn()
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({ ok: true, json: async () => ({ agentRuntimeArn: "arn:aws:bedrock-agentcore:us-east-1:1:runtime/x" }) }))
  )
})

describe("hand-off flow", () => {
  it("opens the desk after the goodbye, mutes the bot and lets Laura join", async () => {
    const user = userEvent.setup()
    agentTurn(JSON.stringify(HAND_OFF))
    await startChat()

    await user.type(screen.getByPlaceholderText("Escribe un mensaje…"), "quiero hablar con una persona{Enter}")

    const desk = await screen.findByRole("region", DESK, { timeout: 2000 })
    expect(within(desk).getByText("Carlos Rendón")).toBeInTheDocument()
    expect(within(desk).getByText(HAND_OFF.summary)).toBeInTheDocument()
    expect(within(desk).getByText(GOODBYE, { selector: "blockquote" })).toBeInTheDocument()
    expect(within(desk).getByText("Conectando…")).toBeInTheDocument()

    // the customer keeps typing: the message reaches the desk, never the bot
    await user.type(screen.getByPlaceholderText("Escribe un mensaje…"), "¿sigues ahí?{Enter}")
    expect(invoke).toHaveBeenCalledTimes(1)
    expect(screen.getAllByText("¿sigues ahí?")).toHaveLength(2)

    // Laura answers: both views show that she joined
    await user.type(within(desk).getByLabelText("Mensaje de Laura"), "Hola Carlos, soy Laura.")
    await user.click(within(desk).getByRole("button", { name: /Enviar/ }))
    expect(screen.getAllByText(/Laura se unió a la conversación/)).toHaveLength(2)
    expect(within(desk).getByText("En conversación")).toBeInTheDocument()
  })

  it("an error result never opens the desk", async () => {
    const user = userEvent.setup()
    agentTurn(JSON.stringify({ error: "The hand-off couldn't be sent." }))
    await startChat()

    await user.type(screen.getByPlaceholderText("Escribe un mensaje…"), "quiero hablar con una persona{Enter}")
    await turnFinished()
    await pause(900)

    expect(screen.queryByRole("region", DESK)).toBeNull()
  })

  it("starting a new chat while the goodbye is still streaming cancels the split", async () => {
    const user = userEvent.setup()
    let finish: () => void = () => {}
    invoke.mockImplementationOnce(async (_message: string, _session: string, _token: string, onEvent: OnEvent) => {
      onEvent({ type: "text", content: "Te paso con una persona." })
      onEvent({ type: "tool_use_start", toolUseId: "t1", name: "human-agent-hand-off-target___human_agent_hand_off" })
      onEvent({ type: "tool_result", toolUseId: "t1", result: JSON.stringify(HAND_OFF) })
      await new Promise<void>(resolve => {
        finish = resolve
      })
      onEvent({ type: "text", content: GOODBYE })
    })
    await startChat()

    await user.type(screen.getByPlaceholderText("Escribe un mensaje…"), "quiero hablar con una persona{Enter}")
    await screen.findByText("Pensando…")
    await user.click(screen.getByRole("button", { name: /Nueva conversación/ }))
    finish()
    await turnFinished()
    await pause(900)

    expect(screen.queryByRole("region", DESK)).toBeNull()
  })

  it("starting a new chat during the pause cancels the split", async () => {
    const user = userEvent.setup()
    agentTurn(JSON.stringify(HAND_OFF))
    await startChat()

    await user.type(screen.getByPlaceholderText("Escribe un mensaje…"), "quiero hablar con una persona{Enter}")
    await turnFinished()
    await user.click(screen.getByRole("button", { name: /Nueva conversación/ }))
    await pause(900)

    expect(screen.queryByRole("region", DESK)).toBeNull()
  })
})
