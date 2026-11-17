import { Fragment, type ReactNode } from "react"

/** Bold (**x**) inside a line, rendered as React elements: no HTML injection possible. */
function inline(text: string): ReactNode[] {
  return text.split(/(\*\*[^*]+\*\*)/g).map((part, i) =>
    part.startsWith("**") && part.endsWith("**") ? (
      <strong key={i} className="font-semibold">
        {part.slice(2, -2)}
      </strong>
    ) : (
      <Fragment key={i}>{part}</Fragment>
    ),
  )
}

/** The small subset of Markdown the Copilot uses: paragraphs, bullet and numbered lists, bold. */
export function RichText({ text }: { text: string }) {
  const blocks: ReactNode[] = []
  let list: { ordered: boolean; items: string[] } | null = null
  const flush = () => {
    if (!list) return
    const Tag = list.ordered ? "ol" : "ul"
    blocks.push(
      <Tag
        key={blocks.length}
        className={list.ordered ? "list-decimal space-y-1 pl-5" : "list-disc space-y-1 pl-5"}
      >
        {list.items.map((item, i) => (
          <li key={i}>{inline(item)}</li>
        ))}
      </Tag>,
    )
    list = null
  }
  for (const raw of text.split("\n")) {
    const line = raw.trimEnd()
    const bullet = /^\s*[-*•]\s+(.*)$/.exec(line)
    const numbered = /^\s*\d+[.)]\s+(.*)$/.exec(line)
    if (bullet || numbered) {
      const ordered = Boolean(numbered)
      if (list && list.ordered !== ordered) flush()
      list ??= { ordered, items: [] }
      list.items.push((bullet ?? numbered)![1]!)
      continue
    }
    flush()
    if (!line.trim()) continue
    const heading = /^#{1,6}\s+(.*)$/.exec(line)
    blocks.push(
      <p key={blocks.length} className={heading ? "font-semibold" : undefined}>
        {inline(heading ? heading[1]! : line)}
      </p>,
    )
  }
  flush()
  return <div className="space-y-2">{blocks}</div>
}
