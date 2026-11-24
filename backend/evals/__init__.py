"""Agent quality evals: does the AI make good suggestions, not just valid ones?

The tests prove the plumbing (tools, approvals, budgets) with a scripted model. These run the
real Copilot and pipeline agent against Claude in realistic CRM situations and grade what they
do: rule checks on the proposals and replies (`evals.checks`), and optionally a model-graded
score of the note or answer (`evals.judge`). Run them with scripts/evals.py; see the README.
"""
