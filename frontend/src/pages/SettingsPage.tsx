import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Bot, Sparkles } from "lucide-react"
import { type ReactNode, useState } from "react"

import {
  settingsChangeAiSettingsMutation,
  settingsChangeBudgetsMutation,
  settingsReadAiSettingsOptions,
  settingsReadBudgetsOptions,
} from "@/client/@tanstack/react-query.gen"
import type { AiSettings, AiSettingsView, BudgetsOutput } from "@/client/types.gen"
import { PageHeader } from "@/components/layout/AppLayout"
import { Button } from "@/components/ui/button"
import { Card, Spinner } from "@/components/ui/card"
import { Field, Select } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { apiErrorMessage } from "@/lib/api"
import { useToast } from "@/lib/toast"
import { cn } from "@/lib/utils"

type EffortLevel = AiSettings["copilot_effort"]

/** Admin settings. AI models for now; users, pipelines and lost reasons come in 3f. */
export function SettingsPage() {
  const view = useQuery(settingsReadAiSettingsOptions())
  return (
    <>
      <PageHeader title="Settings" />
      <div className="max-w-4xl px-4 pb-8 md:px-6">
        {view.isPending ? (
          <Spinner />
        ) : view.isError ? (
          <p className="text-sm text-red-600">Couldn't load settings.</p>
        ) : (
          <AiModels view={view.data} key={JSON.stringify(view.data.settings)} />
        )}
        <BudgetsSection />
      </div>
    </>
  )
}

function AiModels({ view }: { view: AiSettingsView }) {
  const queryClient = useQueryClient()
  const toast = useToast()
  const [draft, setDraft] = useState<AiSettings>(view.settings)
  const save = useMutation({
    ...settingsChangeAiSettingsMutation(),
    onSuccess: (next) => {
      queryClient.setQueryData(settingsReadAiSettingsOptions().queryKey, next)
      toast("AI settings saved")
    },
    onError: (e) => toast(apiErrorMessage(e), "error"),
  })
  const dirty = JSON.stringify(draft) !== JSON.stringify(view.settings)

  return (
    <section aria-labelledby="ai-models" className="space-y-4">
      <div>
        <h2 id="ai-models" className="text-base font-semibold">
          AI models
        </h2>
        <p className="mt-1 text-sm text-ink-soft">
          Choose the Claude model and effort for each agent. Higher effort means more thorough
          answers and more tokens; effort levels aren't equivalent across models, so recheck quality
          and cost on the AI usage page after switching.
        </p>
      </div>
      <AgentCard
        icon={<Sparkles className="size-4 text-brand-600" />}
        title="Copilot"
        hint="Applies to new chats. Chats already under way keep the model they started with."
        view={view}
        model={draft.copilot_model}
        effort={draft.copilot_effort}
        onChange={(model, effort) =>
          setDraft({ ...draft, copilot_model: model, copilot_effort: effort })
        }
      />
      <AgentCard
        icon={<Bot className="size-4 text-brand-600" />}
        title="Pipeline agent"
        hint="Applies from the next morning review (or the next one you start from the inbox)."
        view={view}
        model={draft.pipeline_model}
        effort={draft.pipeline_effort}
        onChange={(model, effort) =>
          setDraft({ ...draft, pipeline_model: model, pipeline_effort: effort })
        }
      />
      <div className="flex justify-end gap-2">
        <Button
          variant="outline"
          disabled={!dirty || save.isPending}
          onClick={() => setDraft(view.settings)}
        >
          Reset
        </Button>
        <Button disabled={!dirty || save.isPending} onClick={() => save.mutate({ body: draft })}>
          {save.isPending ? "Saving…" : "Save"}
        </Button>
      </div>
    </section>
  )
}

function AgentCard({
  icon,
  title,
  hint,
  view,
  model,
  effort,
  onChange,
}: {
  icon: ReactNode
  title: string
  hint: string
  view: AiSettingsView
  model: string
  effort: EffortLevel
  onChange: (model: string, effort: EffortLevel) => void
}) {
  const id = title.toLowerCase().replace(/\W+/g, "-")
  const known = view.models.some((m) => m.id === model)
  return (
    <Card className="p-4">
      <div className="flex items-center gap-2">
        {icon}
        <h3 className="text-sm font-semibold">{title}</h3>
      </div>
      <p className="mt-1 text-xs text-ink-faint">{hint}</p>
      <fieldset className="mt-3 grid gap-2 sm:grid-cols-3">
        <legend className="sr-only">{title} model</legend>
        {view.models.map((m) => (
          <label
            key={m.id}
            className={cn(
              "flex cursor-pointer flex-col rounded-md border p-3 text-sm transition-colors",
              model === m.id ? "border-brand-600 bg-brand-50" : "border-line hover:bg-muted",
            )}
          >
            <span className="flex items-center gap-2 font-medium">
              <input
                type="radio"
                name={`${id}-model`}
                className="accent-brand-600"
                checked={model === m.id}
                onChange={() => onChange(m.id, effort)}
              />
              {m.name}
            </span>
            <span className="mt-1 text-xs text-ink-soft">{m.note}</span>
            <span className="mt-2 text-xs text-ink-faint tabular-nums">
              ${Number(m.input_usd_per_mtok)} in · ${Number(m.output_usd_per_mtok)} out per million
              tokens
            </span>
          </label>
        ))}
      </fieldset>
      {!known && (
        <p className="mt-2 text-xs text-ink-soft">
          Currently {model} (set on the server); choose one above to change it.
        </p>
      )}
      <label className="mt-3 flex items-center gap-3 text-sm" htmlFor={`${id}-effort`}>
        <span className="text-ink-soft">Effort</span>
        <Select
          id={`${id}-effort`}
          className="w-36"
          value={effort}
          onChange={(e) => onChange(model, e.target.value as EffortLevel)}
        >
          {view.efforts.map((e) => (
            <option key={e} value={e}>
              {e}
            </option>
          ))}
        </Select>
      </label>
    </Card>
  )
}

function BudgetsSection() {
  const budgets = useQuery(settingsReadBudgetsOptions())
  return (
    <section aria-labelledby="ai-budgets" className="mt-10 space-y-4">
      <div>
        <h2 id="ai-budgets" className="text-base font-semibold">
          AI budgets
        </h2>
        <p className="mt-1 text-sm text-ink-soft">
          Monthly limits in US dollars, as Anthropic bills. They're checked before every model call,
          so a question or review can go over by at most one call. Leave a limit empty for no limit.
          Spend so far is on the AI usage page.
        </p>
      </div>
      {budgets.isPending ? (
        <Spinner />
      ) : budgets.isError ? (
        <p className="text-sm text-red-600">Couldn't load budgets.</p>
      ) : (
        <BudgetsForm budgets={budgets.data} key={JSON.stringify(budgets.data)} />
      )}
    </section>
  )
}

const toInput = (v: string | number | null | undefined) => (v == null ? "" : String(Number(v)))
const toLimit = (v: string) => (v.trim() === "" ? null : v.trim())

function BudgetsForm({ budgets }: { budgets: BudgetsOutput }) {
  const queryClient = useQueryClient()
  const toast = useToast()
  const [copilot, setCopilot] = useState(toInput(budgets.copilot_per_person_usd))
  const [pipeline, setPipeline] = useState(toInput(budgets.pipeline_team_usd))
  const save = useMutation({
    ...settingsChangeBudgetsMutation(),
    onSuccess: (next) => {
      queryClient.setQueryData(settingsReadBudgetsOptions().queryKey, next)
      toast("Budgets saved")
    },
    onError: (e) => toast(apiErrorMessage(e), "error"),
  })
  const dirty =
    copilot !== toInput(budgets.copilot_per_person_usd) ||
    pipeline !== toInput(budgets.pipeline_team_usd)

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault()
        save.mutate({
          body: { copilot_per_person_usd: toLimit(copilot), pipeline_team_usd: toLimit(pipeline) },
        })
      }}
    >
      <Card className="grid gap-4 p-4 sm:grid-cols-2">
        <Field label="Copilot, per person per month ($)" htmlFor="budget-copilot">
          <Input
            id="budget-copilot"
            type="number"
            min={0}
            step="0.01"
            inputMode="decimal"
            placeholder="No limit"
            value={copilot}
            onChange={(e) => setCopilot(e.target.value)}
          />
        </Field>
        <Field label="Pipeline agent, whole team per month ($)" htmlFor="budget-pipeline">
          <Input
            id="budget-pipeline"
            type="number"
            min={0}
            step="0.01"
            inputMode="decimal"
            placeholder="No limit"
            value={pipeline}
            onChange={(e) => setPipeline(e.target.value)}
          />
        </Field>
      </Card>
      <div className="mt-4 flex justify-end">
        <Button type="submit" disabled={!dirty || save.isPending}>
          {save.isPending ? "Saving…" : "Save budgets"}
        </Button>
      </div>
    </form>
  )
}
