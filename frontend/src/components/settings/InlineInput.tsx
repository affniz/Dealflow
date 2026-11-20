import { type InputHTMLAttributes, useState } from "react"

import { Input } from "@/components/ui/input"
import { cn } from "@/lib/utils"

/**
 * A text or number field in a settings list that saves itself: on Enter or when focus leaves,
 * if the value changed and isn't empty. Escape puts the saved value back.
 * Give it `key={value}` so it picks up the saved value after a save or refetch.
 */
export function InlineInput({
  value,
  onSave,
  className,
  ...props
}: Omit<InputHTMLAttributes<HTMLInputElement>, "value" | "onChange" | "defaultValue"> & {
  value: string
  onSave: (value: string) => void
}) {
  const [text, setText] = useState(value)

  function commit() {
    const next = text.trim()
    if (!next) return setText(value) // required: an empty field goes back to what was saved
    if (next !== value) onSave(next)
  }

  return (
    <Input
      {...props}
      value={text}
      onChange={(e) => setText(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === "Enter") {
          e.preventDefault()
          e.currentTarget.blur()
        } else if (e.key === "Escape") {
          e.preventDefault()
          setText(value)
        }
      }}
      className={cn("h-8", className)}
    />
  )
}
