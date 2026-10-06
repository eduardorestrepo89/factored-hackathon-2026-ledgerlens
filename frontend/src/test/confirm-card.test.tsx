import { describe, it, expect, vi } from "vitest"
import { fireEvent, render, screen } from "@testing-library/react"
import { ConfirmCard, ConfirmContext } from "@/components/chat/ConfirmCard"
import type { Confirmation } from "@/components/chat/types"

const CLAIM: Confirmation = {
  id: "int-1",
  tool: "gateway_open-claim-target___open_claim",
  toolUseId: "tooluse_2",
  details: { transaction_ids: ["TRX-1", "TRX-2"], claim_type: "fraud" },
}

describe("ConfirmCard", () => {
  it("asks about the claim and sends the customer's answer", () => {
    const answer = vi.fn()
    render(
      <ConfirmContext.Provider value={answer}>
        <ConfirmCard confirm={CLAIM} />
      </ConfirmContext.Provider>
    )

    expect(screen.getByText("¿Abrimos el reclamo?")).toBeInTheDocument()
    expect(screen.getByText("Reclamo por 2 cargos que no reconoces.")).toBeInTheDocument()
    // The safe choice has the focus while the composer is locked
    expect(screen.getByRole("button", { name: "No" })).toHaveFocus()
    fireEvent.click(screen.getByRole("button", { name: "No" }))

    expect(answer).toHaveBeenCalledWith(CLAIM, false, "No")
  })

  it("shows no buttons once answered, or where no chat can answer it", () => {
    render(<ConfirmCard confirm={{ ...CLAIM, answer: "yes" }} />)
    render(<ConfirmCard confirm={{ ...CLAIM, id: "int-2" }} />)

    expect(screen.queryByRole("button")).toBeNull()
    expect(screen.getByText("Sí")).toBeInTheDocument()
  })
})
