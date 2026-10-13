# Edict 0002: Model casting for workers and judge
Status: proposed
Depends on: Ariadne semantic review gate (`feat/semantic-review-gate`)

## Intent
Let the human choose which model plays each role in Ariadne. The architectural
bet (see `docs/ariadne-assessment.md`) is that a solid gate lets cheap, fast
models do the work while a stronger model judges it. Right now neither role can
be cast: `LLMJudge()` is constructed with no model and the worker harness's
`ClaudeAgentOptions` sets none.

## Constraints
- Add `worker_model: Optional[str] = None` and
  `judge_model: Optional[str] = None` to `AriadneConfig`.
- `None` means "use the SDK default," so existing behavior is unchanged.
- Settable through the existing config CLI, e.g.
  `daedalus config ariadne.worker_model claude-haiku-5-5`.
- The orchestrator passes `judge_model` to `LLMJudge`; the dispatcher/harness
  passes `worker_model` to the worker's `ClaudeAgentOptions`.
- The model each role used is recorded on the diff
  (`metadata["worker_model"]`, and in the semantic review result for the
  judge), so results can be compared across castings later.

## Acceptance criteria
- With both fields unset, behavior and tests are unchanged.
- With them set, the configured model names reach both `ClaudeAgentOptions`
  constructions (verified by tests that stub the SDK).
- `ariadne review show` displays which models produced and judged the diff.

## Non-goals
- No per-task or per-complexity routing yet. One model per role.
- No non-Anthropic backends.
- No automatic escalation from worker model to judge model.
