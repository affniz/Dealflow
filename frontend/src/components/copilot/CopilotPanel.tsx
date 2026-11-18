import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { ArrowUp, History, Plus, Search, Sparkles, X } from "lucide-react"
import { type FormEvent, type KeyboardEvent, useEffect, useRef, useState } from "react"
import { useMatch } from "react-router-dom"

import {
  copilotCopilotStatusOptions,
  copilotListConversationsOptions,
  copilotReadConversationOptions,
  copilotSendMessageMutation,
  dealsReadDealOptions,
  usageMyUsageOptions,
} from "@/client/@tanstack/react-query.gen"
import type { AgentProposalPublic, ConversationView } from "@/client/types.gen"
import { RichText } from "@/components/copilot/RichText"
import { ProposalCard } from "@/components/copilot/ProposalCard"
import { Button } from "@/components/ui/button"
import { Spinner } from "@/components/ui/card"
import { apiErrorMessage, invalidate } from "@/lib/api"
import { permissions, useAuth } from "@/lib/auth"
import { formatUsd } from "@/lib/money"
import { readStorage, writeStorage } from "@/lib/storage"
import { cn } from "@/lib/utils"

const SUGGESTIONS = [
  "What needs my attention today?",
  "Which deals are stalled, and what should I do about them?",
  "Why have we been losing deals lately?",
]
const DEAL_SUGGESTIONS = [
  "Summarise this deal and suggest the next step",
  "Draft a follow-up task for this deal",
]

export function CopilotPanel({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { user } = useAuth()
  const { canWrite, isAdmin } = permissions(user)
  const queryClient = useQueryClient()
  const storageKey = `dealflow.copilot.${user?.id}`
  const [conversationId, setConversationId] = useState<number | null>(() => {
    const saved = Number(readStorage(storageKey))
    return Number.isFinite(saved) && saved > 0 ? saved : null
  })
  const [draft, setDraft] = useState("")
  const [pendingText, setPendingText] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [showHistory, setShowHistory] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)

  const dealMatch = useMatch("/deals/:dealId")
  const dealId = dealMatch ? Number(dealMatch.params.dealId) : null
  const deal = useQuery({
    ...dealsReadDealOptions({ path: { deal_id: dealId ?? 0 } }),
    enabled: open && dealId !== null,
  })

  const status = useQuery({ ...copilotCopilotStatusOptions(), enabled: open })
  const usage = useQuery({ ...usageMyUsageOptions(), enabled: open })
  const conversations = useQuery({
    ...copilotListConversationsOptions(),
    enabled: open && showHistory,
  })
  const conversationOptions = copilotReadConversationOptions({
    path: { conversation_id: conversationId ?? 0 },
  })
  const conversation = useQuery({
    ...conversationOptions,
    enabled: open && conversationId !== null,
  })

  function selectConversation(id: number | null) {
    setConversationId(id)
    writeStorage(storageKey, id === null ? null : String(id))
    setShowHistory(false)
    setError(null)
  }

  const send = useMutation({
    ...copilotSendMessageMutation(),
    onSuccess: (view: ConversationView) => {
      queryClient.setQueryData(
        copilotReadConversationOptions({ path: { conversation_id: view.id } }).queryKey,
        view,
      )
      selectConversation(view.id)
      invalidate(queryClient, "copilotListConversations", "copilotListProposals", "usageMyUsage")
    },
    onError: (e, vars) => {
      setError(apiErrorMessage(e, "Copilot couldn't answer. Try again."))
      setDraft(vars.body.text)
    },
    onSettled: () => setPendingText(null),
  })

  // Conversation lookups that fail (deleted, someone else's) start a fresh chat.
  useEffect(() => {
    if (conversation.isError) selectConversation(null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [conversation.isError])

  useEffect(() => {
    if (!open) return
    const onKey = (e: globalThis.KeyboardEvent) => e.key === "Escape" && onClose()
    window.addEventListener("keydown", onKey)
    inputRef.current?.focus()
    return () => window.removeEventListener("keydown", onKey)
  }, [open, onClose])

  const items = conversation.data?.items ?? []
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" })
  }, [items.length, pendingText])

  function submit(text: string) {
    const clean = text.trim()
    if (!clean || send.isPending) return
    setError(null)
    setDraft("")
    setPendingText(clean)
    send.mutate({ body: { text: clean, conversation_id: conversationId, deal_id: dealId } })
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault()
      submit(draft)
    }
  }

  if (!open) return null
  const proposals = new Map<number, AgentProposalPublic>(
    (conversation.data?.proposals ?? []).map((p) => [p.id, p]),
  )
  const empty = items.length === 0 && !pendingText
  const enabled = status.data?.enabled !== false

  return (
    <aside
      aria-label="Copilot"
      className="fixed inset-y-0 right-0 z-40 flex w-full flex-col border-l border-line bg-canvas shadow-2xl sm:w-[440px]"
    >
      <header className="flex items-center gap-2 border-b border-line bg-surface px-3 py-2">
        <Sparkles className="size-4 text-brand-600" aria-hidden />
        <h2 className="flex-1 truncate text-sm font-semibold">
          {conversation.data?.title ?? "Copilot"}
        </h2>
        <Button
          variant="ghost"
          size="icon"
          aria-label="Recent chats"
          title="Recent chats"
          aria-expanded={showHistory}
          onClick={() => setShowHistory(!showHistory)}
        >
          <History />
        </Button>
        <Button
          variant="ghost"
          size="icon"
          aria-label="New chat"
          title="New chat"
          onClick={() => selectConversation(null)}
        >
          <Plus />
        </Button>
        <Button variant="ghost" size="icon" aria-label="Close Copilot" onClick={onClose}>
          <X />
        </Button>
      </header>

      {showHistory && (
        <div className="max-h-64 overflow-y-auto border-b border-line bg-surface p-2">
          {conversations.isPending ? (
            <Spinner className="m-2" />
          ) : conversations.data?.length ? (
            conversations.data.map((c) => (
              <button
                key={c.id}
                type="button"
                onClick={() => selectConversation(c.id)}
                className={cn(
                  "block w-full truncate rounded-md px-3 py-2 text-left text-sm hover:bg-muted",
                  c.id === conversationId && "bg-brand-50 text-brand-700",
                )}
              >
                {c.title}
              </button>
            ))
          ) : (
            <p className="p-2 text-sm text-ink-faint">No chats yet.</p>
          )}
        </div>
      )}

      <div ref={scrollRef} className="flex-1 space-y-4 overflow-y-auto p-4">
        {!enabled ? (
          <div className="rounded-lg border border-line bg-surface p-4 text-sm text-ink-soft">
            <p className="font-medium text-ink">Copilot isn't set up yet</p>
            <p className="mt-1">
              {isAdmin
                ? "Add ANTHROPIC_API_KEY to backend/.env and restart the API to turn it on."
                : "Ask an admin to connect it."}
            </p>
          </div>
        ) : empty ? (
          <div className="pt-6">
            <p className="text-sm font-medium">Ask about your pipeline</p>
            <p className="mt-1 text-sm text-ink-soft">
              {canWrite
                ? "Copilot can look things up and prepare changes. Nothing changes until you approve it."
                : "Copilot can look things up for you. As a viewer you can't make changes."}
            </p>
            <div className="mt-4 flex flex-col gap-2">
              {[...(dealId ? DEAL_SUGGESTIONS : []), ...SUGGESTIONS].map((s) => (
                <button
                  key={s}
                  type="button"
                  onClick={() => submit(s)}
                  className="rounded-lg border border-line bg-surface px-3 py-2 text-left text-sm hover:border-brand-600/40 hover:bg-brand-50"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <>
            {items.map((item, i) => {
              if (item.kind === "user") {
                return (
                  <div key={i} className="flex justify-end">
                    <p className="max-w-[85%] rounded-2xl rounded-br-sm bg-brand-600 px-3 py-2 text-sm whitespace-pre-line text-white">
                      {item.text}
                    </p>
                  </div>
                )
              }
              if (item.kind === "assistant") {
                return (
                  <div key={i} className="text-sm leading-relaxed">
                    <RichText text={item.text} />
                  </div>
                )
              }
              const proposal = item.proposal_id ? proposals.get(item.proposal_id) : undefined
              return proposal ? (
                <ProposalCard key={i} proposal={proposal} canDecide={canWrite} showDeal />
              ) : (
                <p key={i} className="flex items-center gap-1.5 text-xs text-ink-faint">
                  <Search className="size-3" aria-hidden /> {item.text}
                </p>
              )
            })}
            {pendingText && (
              <>
                <div className="flex justify-end">
                  <p className="max-w-[85%] rounded-2xl rounded-br-sm bg-brand-600 px-3 py-2 text-sm whitespace-pre-line text-white">
                    {pendingText}
                  </p>
                </div>
                <p className="flex items-center gap-2 text-sm text-ink-soft" role="status">
                  <Spinner className="size-4" /> Working on it…
                </p>
              </>
            )}
          </>
        )}
        {error && (
          <p role="alert" className="text-sm text-red-600">
            {error}
          </p>
        )}
      </div>

      <form
        onSubmit={(e: FormEvent) => {
          e.preventDefault()
          submit(draft)
        }}
        className="border-t border-line bg-surface p-3"
      >
        {usage.data && Number(usage.data.cost_usd) > 0 && (
          <p className="mb-2 text-right text-[11px] text-ink-faint">
            Your Copilot use this month: {formatUsd(usage.data.cost_usd)} · {usage.data.questions}{" "}
            {usage.data.questions === 1 ? "question" : "questions"}
          </p>
        )}
        {dealId !== null && deal.data && (
          <p className="mb-2 truncate text-xs text-ink-soft">
            Looking at: <span className="font-medium text-ink">{deal.data.title}</span>
          </p>
        )}
        <div className="flex items-end gap-2">
          <textarea
            ref={inputRef}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={onKeyDown}
            rows={2}
            maxLength={4000}
            disabled={!enabled}
            placeholder="Ask Copilot…"
            aria-label="Message Copilot"
            className="max-h-40 min-h-10 flex-1 resize-none rounded-md border border-line bg-surface px-3 py-2 text-sm placeholder:text-ink-faint focus-visible:border-brand-600 focus-visible:outline-2 focus-visible:outline-brand-600/30 disabled:opacity-50"
          />
          <Button
            type="submit"
            size="icon"
            aria-label="Send"
            disabled={!enabled || !draft.trim() || send.isPending}
          >
            <ArrowUp />
          </Button>
        </div>
      </form>
    </aside>
  )
}
