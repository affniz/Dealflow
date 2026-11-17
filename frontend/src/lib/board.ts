import type { Board, BoardColumn, DealPublic } from "@/client/types.gen"

const money = (n: number) => n.toFixed(2)

function withTotals(
  col: BoardColumn,
  deals: DealPublic[],
  deltaCount: number,
  deltaValue: number,
  deltaRotting: number,
): BoardColumn {
  const total = Number(col.total_value) + deltaValue
  return {
    ...col,
    deals,
    deal_count: col.deal_count + deltaCount,
    total_value: money(total),
    weighted_value: money((total * col.stage.probability) / 100),
    rotting_count: col.rotting_count + deltaRotting,
  }
}

/**
 * What the board looks like after moving a deal, computed locally so the card moves the instant
 * it's dropped. The server's answer replaces it a moment later.
 */
export function moveDealOnBoard(board: Board, dealId: number, toStageId: number): Board {
  const from = board.columns.find((c) => c.deals.some((d) => d.id === dealId))
  const deal = from?.deals.find((d) => d.id === dealId)
  if (!from || !deal || from.stage.id === toStageId) return board

  const value = Number(deal.value ?? 0)
  // moving resets the stage clock, so the deal is no longer stalled
  const moved: DealPublic = { ...deal, stage_id: toStageId, rotting_since: null, is_rotting: false }
  const columns = board.columns.map((col) => {
    if (col.stage.id === from.stage.id) {
      return withTotals(
        col,
        col.deals.filter((d) => d.id !== dealId),
        -1,
        -value,
        deal.is_rotting ? -1 : 0,
      )
    }
    if (col.stage.id === toStageId) return withTotals(col, [moved, ...col.deals], 1, value, 0)
    return col
  })
  return {
    ...board,
    columns,
    weighted_value: money(columns.reduce((sum, c) => sum + Number(c.weighted_value), 0)),
  }
}
