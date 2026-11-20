import { Mail, NotebookPen, Phone, SquareCheck, Users } from "lucide-react"

import type { ActivityType } from "@/client/types.gen"

export const ACTIVITY_ICONS: Record<ActivityType, typeof Phone> = {
  call: Phone,
  meeting: Users,
  task: SquareCheck,
  email: Mail,
  note: NotebookPen,
}

export const ACTIVITY_LABELS: Record<ActivityType, string> = {
  call: "Call",
  meeting: "Meeting",
  task: "Task",
  email: "Email",
  note: "Note",
}
