import { describe, it, expect } from "vitest"
import { render, screen } from "@testing-library/react"
import { HandOffTicket } from "@/components/chat/HandOffTicket"

const NAME = "human-agent-hand-off-target___human_agent_hand_off"
const RESULT = JSON.stringify({
  hand_off_id: "HO-7Q3KX2MA",
  status: "queued",
  priority: "high",
  reason: "FRAUD_CONFIRMED",
  customer_id: "CLI-F2DZJYU0POJ9",
  summary: "No reconoce 2 cargos.",
  related_ids: ["TX-88", "TX-89"],
})

describe("HandOffTicket", () => {
  it("shows the case, its priority, reason and ids for a valid result", () => {
    render(<HandOffTicket name={NAME} args="{}" status="complete" result={RESULT} tagged />)

    expect(screen.getByText("Caso HO-7Q3KX2MA")).toBeInTheDocument()
    expect(screen.getByText("ALTA")).toBeInTheDocument()
    expect(screen.getByText("Cargo no reconocido")).toBeInTheDocument()
    expect(screen.queryByText(/Fraude confirmado/)).toBeNull()
    expect(screen.getByText("TX-89")).toBeInTheDocument()
    expect(screen.getByText("Enviado a una persona")).toBeInTheDocument()
  })

  it("shows that it is sending while the call runs", () => {
    render(<HandOffTicket name={NAME} args="{}" status="executing" tagged={false} />)

    expect(screen.getByText("Enviando a una persona…")).toBeInTheDocument()
  })

  it("falls back to the plain tool row for an error result", () => {
    render(<HandOffTicket name={NAME} args="{}" status="complete" result='{"error":"down"}' tagged={false} />)

    expect(screen.queryByText(/Caso/)).toBeNull()
    expect(screen.getByText(NAME)).toBeInTheDocument()
  })
})
