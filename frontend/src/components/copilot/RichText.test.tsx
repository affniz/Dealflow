import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import { RichText } from "@/components/copilot/RichText"

describe("RichText", () => {
  it("renders the Copilot's paragraphs, lists and bold", () => {
    const { container } = render(
      <RichText
        text={"## Stalled\n**3 deals** need you:\n- Kaveri Foods\n- Zenith\n1. Call\n2. Email"}
      />,
    )
    expect(screen.getByText("Stalled")).toHaveClass("font-semibold")
    expect(screen.getByText("3 deals").tagName).toBe("STRONG")
    expect(container.querySelectorAll("ul > li")).toHaveLength(2)
    expect(container.querySelectorAll("ol > li")).toHaveLength(2)
  })

  it("shows markup in a reply as text, never as HTML", () => {
    // a reply can quote a deal title or note, which anyone on the team could have written
    const { container } = render(
      <RichText text={'<img src=x onerror="alert(1)"> and **<script>alert(2)</script>**'} />,
    )
    expect(container.querySelector("img, script")).toBeNull()
    expect(container).toHaveTextContent(
      '<img src=x onerror="alert(1)"> and <script>alert(2)</script>',
    )
  })
})
