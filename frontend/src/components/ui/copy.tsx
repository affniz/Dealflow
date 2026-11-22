import { Check, Copy } from "lucide-react"
import { useState } from "react"

import { Button } from "@/components/ui/button"

/** A value to copy (a token, a command, a link), with a copy button. */
export function CopyBlock({ label, value }: { label: string; value: string }) {
  const [copied, setCopied] = useState(false)
  const id = `copy-${label.replace(/\W+/g, "-").toLowerCase()}`
  return (
    <div>
      <div className="mb-1 flex items-center justify-between">
        <span id={id} className="text-sm font-medium">
          {label}
        </span>
        <Button
          variant="ghost"
          size="sm"
          aria-label={`Copy ${label.toLowerCase()}`}
          onClick={async () => {
            await navigator.clipboard.writeText(value)
            setCopied(true)
            setTimeout(() => setCopied(false), 2000)
          }}
        >
          {copied ? <Check /> : <Copy />} {copied ? "Copied" : "Copy"}
        </Button>
      </div>
      <pre
        aria-labelledby={id}
        className="overflow-x-auto rounded-md border border-line bg-muted px-3 py-2 font-mono text-xs break-all whitespace-pre-wrap select-all"
      >
        {value}
      </pre>
    </div>
  )
}
