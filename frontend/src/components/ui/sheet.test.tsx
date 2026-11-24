import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { useState } from "react"
import { describe, expect, it, vi } from "vitest"

import { Sheet } from "@/components/ui/sheet"
import { useUnsavedChanges } from "@/lib/sheet"

function NoteForm() {
  const [text, setText] = useState("")
  useUnsavedChanges(text !== "")
  return <input aria-label="Note" value={text} onChange={(e) => setText(e.target.value)} />
}

function setup() {
  const onClose = vi.fn()
  render(
    <Sheet open onClose={onClose} title="Edit contact">
      <NoteForm />
    </Sheet>,
  )
  return { onClose, user: userEvent.setup() }
}

describe("Sheet", () => {
  it("closes straight away when nothing has been typed", async () => {
    const { onClose, user } = setup()
    await user.click(screen.getByRole("button", { name: "Close" }))
    expect(onClose).toHaveBeenCalledOnce()
  })

  it("asks before throwing away unsaved changes", async () => {
    const { onClose, user } = setup()
    await user.type(screen.getByLabelText("Note"), "Call back Monday")
    await user.click(screen.getByRole("button", { name: "Close" }))
    expect(onClose).not.toHaveBeenCalled()
    expect(screen.getByRole("alertdialog", { name: "Unsaved changes" })).toBeInTheDocument()

    await user.click(screen.getByRole("button", { name: "Keep editing" }))
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument()
    expect(screen.getByLabelText("Note")).toHaveValue("Call back Monday")

    await user.click(screen.getByRole("button", { name: "Close" }))
    await user.click(screen.getByRole("button", { name: "Discard" }))
    expect(onClose).toHaveBeenCalledOnce()
  })

  it("treats Escape like the close button", async () => {
    const { onClose, user } = setup()
    await user.type(screen.getByLabelText("Note"), "x")
    screen
      .getByRole("dialog", { hidden: true })
      .dispatchEvent(new Event("cancel", { cancelable: true }))
    expect(await screen.findByRole("alertdialog")).toBeInTheDocument()
    expect(onClose).not.toHaveBeenCalled()
  })
})
