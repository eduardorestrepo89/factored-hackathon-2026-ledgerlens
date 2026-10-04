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

type OnEvent = (event: Record<string, unknown>) => void
const CLAIM = "gateway_open-claim-target___open_claim"
const HAND_OFF_TOOL = "gateway_hand-off-target___human_agent_hand_off"
const HAND_OFF = {
  hand_off_id: "HO-7Q3KX2MA",
  status: "queued",
  priority: "high",
  reason: "CUSTOMER_REQUEST",
  customer_id: "CLI-F2DZJYU0POJ9",
  summary: "Pidió hablar con una persona.",
  related_ids: [],
}

/** The agent calls a tool and ConfirmationHook pauses it: the turn ends on a confirmation event. */
function paused(tool: string, toolUseId: string, id: string, details: Record<string, unknown>) {
  invoke.mockImplementationOnce(async (_m: string, _s: string, _t: string, onEvent: OnEvent) => {
    onEvent({ type: "tool_use_start", toolUseId, name: tool })
    onEvent({ type: "tool_use_delta", toolUseId, input: JSON.stringify(details) })
    onEvent({ type: "confirmation", id, tool: tool.split("___").pop(), toolUseId, details })
  })
}

const composer = () => screen.getByRole("textbox")

async function ask(text: string) {
  const user = userEvent.setup()
  render(
    <GlobalContextProvider>
      <ChatInterface />
    </GlobalContextProvider>
  )
  await waitFor(() => expect(created).toHaveBeenCalled())
  await user.type(composer(), `${text}{Enter}`)
  return user
}

beforeEach(() => {
  invoke.mockReset()
  created.mockReset()
  Element.prototype.scrollIntoView = vi.fn()
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({ ok: true, json: async () => ({ agentRuntimeArn: "arn:aws:bedrock-agentcore:us-east-1:1:runtime/x" }) }))
  )
})

describe("confirmation card (agent ConfirmationHook)", () => {
  it("shows a paused claim as a Yes/No card, locks the composer and resumes the call on Yes", async () => {
    paused(CLAIM, "tu2", "int-1", { transaction_ids: ["TRX-1", "TRX-2"], claim_type: "fraud" })
    const user = await ask("quiero disputar el cargo")

    const card = await screen.findByRole("group", { name: "¿Abrimos el reclamo?" })
    expect(within(card).getByText("Reclamo por 2 cargos que no reconoces.")).toBeInTheDocument()
    expect(composer()).toBeDisabled()

    // The resumed call streams only its result: no new tool_use_start
    invoke.mockImplementationOnce(async (_m: string, _s: string, _t: string, onEvent: OnEvent) => {
      onEvent({ type: "tool_result", toolUseId: "tu2", result: '{"claims":[{"claim_id":"CLM-1"}]}' })
      onEvent({ type: "text", content: "Abrí el reclamo CLM-1." })
    })
    await user.click(within(card).getByRole("button", { name: "Sí" }))

    expect(invoke).toHaveBeenLastCalledWith("Sí", expect.any(String), "token", expect.any(Function), {
      confirmations: [{ interruptId: "int-1", approved: true }],
    })
    expect(await screen.findByText("Abrí el reclamo CLM-1.")).toBeInTheDocument()
    expect(within(card).queryByRole("button")).toBeNull()
    await waitFor(() => expect(composer()).toBeEnabled())
  })

  it("asks to block the card by its last 4 digits and shows the resumed block on Yes", async () => {
    paused("gateway_block-target___block_credit_card", "tu7", "int-3", { card_last4: "4497", reason: "lost" })
    const user = await ask("perdí mi tarjeta")

    const card = await screen.findByRole("group", { name: "¿Bloqueamos tu tarjeta •••• 4497?" })
    expect(composer()).toBeDisabled()

    invoke.mockImplementationOnce(async (_m: string, _s: string, _t: string, onEvent: OnEvent) => {
      onEvent({ type: "tool_result", toolUseId: "tu7", result: '{"card_last4":"4497","status":"BLOCKED"}' })
      onEvent({ type: "text", content: "Listo: tu tarjeta 4497 quedó bloqueada." })
    })
    await user.click(within(card).getByRole("button", { name: "Sí" }))

    expect(await screen.findByText("Bloqueando la tarjeta")).toBeInTheDocument()
    expect(await screen.findByText("Listo: tu tarjeta 4497 quedó bloqueada.")).toBeInTheDocument()
  })

  it("sends approved false on No", async () => {
    paused(CLAIM, "tu2", "int-1", { transaction_ids: ["TRX-1"], claim_type: "fraud" })
    const user = await ask("quiero disputar el cargo")

    invoke.mockImplementationOnce(async () => {})
    await user.click(await screen.findByRole("button", { name: "No" }))

    expect(invoke).toHaveBeenLastCalledWith("No", expect.any(String), "token", expect.any(Function), {
      confirmations: [{ interruptId: "int-1", approved: false }],
    })
  })

  it("on Yes to a hand-off, the resumed result brings the ticket and the split to the desk", async () => {
    paused(HAND_OFF_TOOL, "tu5", "int-9", { reason: "CUSTOMER_REQUEST", priority: "normal" })
    const user = await ask("quiero hablar con una persona")

    invoke.mockImplementationOnce(async (_m: string, _s: string, _t: string, onEvent: OnEvent) => {
      onEvent({ type: "tool_result", toolUseId: "tu5", result: JSON.stringify(HAND_OFF) })
      onEvent({ type: "text", content: "Una persona sigue contigo desde aquí." })
    })
    await user.click(await screen.findByRole("button", { name: "Sí" }))

    expect(await screen.findByRole("region", { name: "Escritorio del agente" }, { timeout: 2000 })).toBeInTheDocument()
  })
})

describe("retry", () => {
  it("sends a failed message again without repeating it in the thread", async () => {
    invoke.mockRejectedValueOnce(new Error("HTTP 502"))
    const user = await ask("hola")

    invoke.mockImplementationOnce(async (_m: string, _s: string, _t: string, onEvent: OnEvent) => {
      onEvent({ type: "text", content: "Hola Carlos" })
    })
    await user.click(await screen.findByRole("button", { name: /Reintentar/ }))

    expect(invoke).toHaveBeenCalledTimes(2)
    expect(invoke).toHaveBeenLastCalledWith("hola", expect.any(String), "token", expect.any(Function), {})
    expect(await screen.findByText("Hola Carlos")).toBeInTheDocument()
    expect(screen.getAllByText("hola")).toHaveLength(1)
    expect(screen.queryByRole("alert")).toBeNull()
  })
})
