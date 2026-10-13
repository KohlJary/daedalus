# Mature-codebase run: Claude steps (for 2026-10-23 or later)

Local conditions (single, ariadne, ariadne+req, ariadne+llmplan) run without Claude and are queued
behind the toy batch. These steps spend Claude tokens, so they wait for Kohl. Expect ~50k tokens per
subagent (measured on the toy runs), so about 6 subagents ≈ 300k tokens.

All paths are relative to this directory (`mature/`).

## 0. Prerequisites
- `results/mature.jsonl` has the local runs, and `results/plans/<task>.json` exists for all three tasks
  (written by the ariadne+llmplan condition).
- Run `python3 stage_claude.py`. It (re)builds `claude/solo/<task>/` and `claude/review/<task>/` and
  checks that no oracle text leaked into them.

## 1. Claude solo, one subagent per task (pycache, judge_intent, model_casting)
From a Claude Code session, launch a general-purpose subagent per task with the prompt in
`claude/SOLO_PROMPT.md`, replacing `{DIR}` with the absolute path of `claude/solo/<task>`.

When each one finishes, record its usage from the completion notice:
`python3 score_claude.py solo <task> <subagent_tokens> <tool_uses> <secs>`

## 2. Plan review, one subagent per task
Launch a general-purpose subagent per task with `claude/REVIEW_PROMPT.md`, replacing `{DIR}` with the
absolute path of `claude/review/<task>`. Then run: `python3 score_claude.py review <task> <subagent_tokens> <tool_uses> <secs>`

## 3. Condition E (local, after step 2)
`python3 mature_exp.py --conditions ariadne+llmplan+review --reps 3`

## 4. Modelled main-context cost
For the write-up, also compute the main-agent-inline review cost: plan size + edits, plus one cache-read
of the session context per turn, against the solo agent's tool calls × session context. Label it modelled.
