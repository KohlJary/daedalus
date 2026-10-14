# Greenfield: Claude steps (from 2026-10-23)

Question: does local Ariadne get a greenfield project's rough shape down for free, so a frontier model
only has to polish? Specs and hidden oracles are in specs.py (validated: validate.py). The local conditions
(gf_single, gf_llmplan) run without Claude; their final trees are in results/artifacts/.

Run `python3 stage_claude.py` first. Replace `{DIR}` in each prompt with the absolute staging path.
After each subagent finishes, note subagent_tokens, tool_uses and seconds from its completion notice.

1. **Claude solo** (claude/SOLO_PROMPT.md): one subagent per spec, `{DIR}` = claude/solo/<spec>.
2. **Polish** (claude/POLISH_PROMPT.md): one subagent per gf_llmplan artifact, `{DIR}` = claude/polish/<spec>/rep<k>.
3. **Claude plan plus tests** (claude/PLAN_PROMPT.md): one subagent per spec, `{DIR}` = claude/plan/<spec>. Copy its
   claudeplan.json to results/plans/<spec>.claudeplan.json, then run locally:
   `EXP_NUM_PREDICT=8192 python3 greenfield.py --conditions claudeplan --reps 3`
   and polish those artifacts (results/artifacts/<spec>/claudeplan/rep<k>) the same way as step 2.
4. **Score:** each final tree against the hidden oracle (feature.run_oracle(tree, FEATURES[spec]["oracle"])),
   plus Claude tokens per condition. For quality, give a reviewer subagent the final trees with condition
   labels removed and a fixed rubric (structure, readability, tests, spec fidelity).

Compare: Claude solo vs polish(local shape) vs polish(Claude plan + tests -> local build), on oracle pass,
Claude tokens, and blind quality. The bet holds if polish(...) matches Claude solo on quality for clearly
fewer Claude tokens.
