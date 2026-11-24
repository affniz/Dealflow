import { describe, expect, it } from "vitest"

import type { Board, BoardColumn, DealPublic } from "@/client/types.gen"
import { moveDealOnBoard } from "@/lib/board"

const deal = (id: number, stage: number, value: string, rotting = false) =>
  ({
    id,
    stage_id: stage,
    value,
    is_rotting: rotting,
    rotting_since: rotting ? "x" : null,
  }) as DealPublic

function column(id: number, probability: number, deals: DealPublic[]): BoardColumn {
  const total = deals.reduce((s, d) => s + Number(d.value), 0)
  return {
    stage: { id, probability },
    deals,
    deal_count: deals.length,
    total_value: total.toFixed(2),
    weighted_value: ((total * probability) / 100).toFixed(2),
    rotting_count: deals.filter((d) => d.is_rotting).length,
  } as BoardColumn
}

const board = (): Board =>
  ({
    columns: [
      column(1, 10, [deal(1, 1, "1000", true), deal(2, 1, "500")]),
      column(2, 50, [deal(3, 2, "2000")]),
    ],
    weighted_value: "1150.00",
  }) as Board

describe("moveDealOnBoard", () => {
  it("moves the card and keeps every total right", () => {
    const next = moveDealOnBoard(board(), 1, 2)
    const [lead, qualified] = next.columns
    expect(lead!.deals.map((d) => d.id)).toEqual([2])
    expect(lead).toMatchObject({ deal_count: 1, total_value: "500.00", weighted_value: "50.00" })
    expect(lead!.rotting_count).toBe(0)
    expect(qualified!.deals.map((d) => d.id)).toEqual([1, 3]) // on top
    expect(qualified).toMatchObject({
      deal_count: 2,
      total_value: "3000.00",
      weighted_value: "1500.00",
    })
    expect(next.weighted_value).toBe("1550.00")
  })

  it("clears the stalled flag: moving resets the stage clock", () => {
    const moved = moveDealOnBoard(board(), 1, 2).columns[1]!.deals[0]!
    expect(moved).toMatchObject({ stage_id: 2, is_rotting: false, rotting_since: null })
  })

  it("leaves the board alone for a drop on the same stage or an unknown deal", () => {
    const before = board()
    expect(moveDealOnBoard(before, 2, 1)).toBe(before)
    expect(moveDealOnBoard(before, 99, 2)).toBe(before)
  })
})
