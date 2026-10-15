---
name: dream
description: "Run a dream: open-ended speculation about where the project and its work could go, generated before it is judged and kept out of the plan. Use when inhale says a dream is due and the user says to run it, or when the user asks you to dream (optionally about a theme). Seeds, the dream, a cold waking pass; picks reach the roadmap only through `daedalus source sync dream`."
allowed-tools: Bash, Agent
---

# Dream

A dream is generated first and judged after, by someone else. While dreaming, nothing judges: no
feasibility, no hedging, no Momus. Afterwards, an agent that didn't dream picks the few ideas worth
building, and those reach the plan only as proposals the user applies or drops. A dream is never
evidence for anything.

The commands do the deciding: which seeds, which mode (drawn in code; never choose or ask), which
agent each step goes to. You relay. Don't add a frame of your own to any prompt, and don't read
the dream into your own judgement of the project.

## Steps

1. **Start.** `daedalus dream start` (or `--theme "<what the user asked to dream about>"`). It
   prints the dream ID.

2. **Each step, until it says done.** `daedalus dream prompt <id> next` prints `AGENT: <agent>
   (<role>)`, a `---` line, and the prompt. Hand the prompt, unchanged, to that agent (subagent
   type as named: `morpheus` or `general-purpose`). Then write back exactly what it returned:
   - role `dreamer` in a list or plain dream, or `waking`: save the reply to a file in the scratchpad
     and run `daedalus dream write <id> dream|waking --file <path>`;
   - role `narrator` or `dreamer` in a narrative dream: `daedalus dream turn <id> narrator|dreamer
     --file <path>`. The turns alternate; the command says what's next and stops the dream at its
     turn count or token cap. There is no early waking.

   In a narrative dream each turn passes through your context: don't comment on it, and don't
   summarise it for the user.

3. **Done.** `daedalus dream done <id> --tokens <N> --dreamer-model <id> --waking-model <id>`,
   with the tokens from the agents' completion notices added up and the models they ran as.
   It counts the ideas and picks itself and logs the run.

4. **Tell the user** in a line or two that the dream is ready (`daedalus dream show <id>`), how
   many picks the waking pass made, and that `daedalus source sync dream` brings them in as
   proposals. Don't summarise the dream itself, and never say which mode it was.

## A dream review (monthly, or when `daedalus dream due` says one is due)

`daedalus dream review bundle` prints a bundle path and a prompt for a `general-purpose` agent.
Hand it over unchanged; save its JSON answer to a scratchpad file; then
`daedalus dream review record <answer> --bundle <bundle path>`. Code counts and elevates; the
elevated themes come in with `daedalus source sync dream`.
