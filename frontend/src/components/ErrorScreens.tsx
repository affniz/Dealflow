import { Component, type ErrorInfo, type ReactNode } from "react"
import { isRouteErrorResponse, useRouteError } from "react-router-dom"

import { AuthShell } from "@/components/AuthShell"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { isStaleBuildError } from "@/lib/errors"

/** What went wrong, in words a person can act on. */
function ErrorMessage({ error, compact }: { error: unknown; compact?: boolean }) {
  const updated = isStaleBuildError(error)
  const notFound = isRouteErrorResponse(error) && error.status === 404
  const title = updated
    ? "Dealflow has been updated"
    : notFound
      ? "This page doesn't exist"
      : "Something went wrong"
  const body = updated
    ? "Reload to get the new version. Nothing you saved is lost."
    : notFound
      ? "Check the address, or go back to the pipeline."
      : "This part of Dealflow hit an error. Reloading usually fixes it; your saved work is safe."
  const detail = !updated && !notFound && error instanceof Error ? error.message : null
  return (
    <div role="alert" className={compact ? "space-y-3" : "space-y-4"}>
      <div>
        <h1 className={compact ? "text-base font-semibold" : "text-lg font-semibold"}>{title}</h1>
        <p className="mt-1 text-sm text-ink-soft">{body}</p>
        {detail && <p className="mt-2 font-mono text-xs break-words text-ink-faint">{detail}</p>}
      </div>
      <div className="flex flex-wrap gap-2">
        <Button onClick={() => window.location.reload()}>Reload</Button>
        {!compact && (
          // a full page load, not a router link: the router itself may be what failed
          <a
            href="/"
            className="inline-flex h-9 items-center rounded-md border border-line bg-surface px-3 text-sm font-medium hover:bg-muted"
          >
            Go to the pipeline
          </a>
        )}
      </div>
    </div>
  )
}

/** A whole-page error: nothing else of the app could be shown. */
export function RootError() {
  const error = useRouteError()
  console.error(error)
  return (
    <AuthShell>
      <Card className="p-6">
        <ErrorMessage error={error} />
      </Card>
    </AuthShell>
  )
}

/** A page's error, shown inside the app's layout so the navigation still works. */
export function PageError() {
  const error = useRouteError()
  console.error(error)
  return (
    <div className="mx-auto max-w-xl px-4 py-10 md:px-6">
      <Card className="p-6">
        <ErrorMessage error={error} />
      </Card>
    </div>
  )
}

/**
 * For parts of the screen outside a route's own page (the Copilot panel, the providers around
 * the router): an error there shows a message in its place instead of a blank screen.
 */
export class ErrorBoundary extends Component<
  { children: ReactNode; compact?: boolean },
  { error: unknown }
> {
  state = { error: null as unknown }

  static getDerivedStateFromError(error: unknown) {
    return { error }
  }

  componentDidCatch(error: unknown, info: ErrorInfo) {
    console.error(error, info.componentStack)
  }

  render() {
    if (this.state.error === null) return this.props.children
    return this.props.compact ? (
      <div className="p-4">
        <ErrorMessage error={this.state.error} compact />
      </div>
    ) : (
      <AuthShell>
        <Card className="p-6">
          <ErrorMessage error={this.state.error} compact />
        </Card>
      </AuthShell>
    )
  }
}
