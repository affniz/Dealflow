import { PageHeader } from "@/components/layout/AppLayout"
import { Card } from "@/components/ui/card"

export function PlaceholderPage({ title, milestone }: { title: string; milestone: string }) {
  return (
    <>
      <PageHeader title={title} />
      <div className="px-4 md:px-6">
        <Card className="p-8 text-center text-sm text-ink-soft">Coming in {milestone}.</Card>
      </div>
    </>
  )
}
