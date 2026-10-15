# Edict 0013: Dreaming
Status: accepted
Depends on: Edict 0010 (digests, what is due, runners, the models, aspirations); Edict 0011 (the
source seam and its proposals); Edict 0006 (confidence labels)

*Drafted by Daedalus at Kohl's request in conversation on 2026-10-15 and accepted by Kohl the same day, after the first dream
(`docs/dreams/2026-10-15.md`) and a read of Cass's Dreaming system in cass-vessel
(`backend/dreaming/`).*

## Intent
Make dreaming a first-class part of Daedalus: a protected, scheduled phase where Daedalus generates
widely about where the project and its own work could go, judged only afterwards and only by the
owner.

Two findings from 2026-10-15 lead here:
- **The first dream worked, but it was one run.** It came from one session, under an explicit
  quota (thirty or more ideas) and a two-pass instruction. It produced 39 ideas and five picks
  that Kohl liked. Kohl has seen the dream framing work with Cass (in conversation, 2026-10-15).
  Whether the frame itself matters, apart from the quota, the label and a fresh context, is
  **untested**. So this edict builds dreaming as an experiment that includes a no-dream arm (see
  Experiment).
- **Evidence-only reflection converges.** Edict 0010 says so itself, and answers with
  aspirations. Dreaming is the larger answer: a second phase of the same sleep, which works on the
  same material in a different way.

**Sleep has two phases.**
- *Reflection* (0010) is consolidation: it replays the record, and updates the models and the
  fixes from evidence.
- *Dreaming* (this edict) is recombination: it takes the same material and the open questions,
  and makes something that isn't in the record yet.

Reflection runs first. The night's dream runs on what it found.

From Cass's system this keeps:
- seeds chosen by readiness;
- a narrative dream between a narrator and the dreamer ("transmute, don't transcribe");
- generating hot and extracting cold.

It deliberately does not keep the parts that let dream content become fact without anyone
deciding: Cass's dream insights are written straight into her self model.

## Constraints

### What a dream is
- **One night's dream is three steps:** seeds, the dream, and a waking pass. Each has its own
  output. A dream is a file under `.daedalus/dreams/<date>[-n]/` holding `seeds.json`,
  `dream.md` and `waking.md`.
- **Every dream file opens with a speculative label.** It says this is not a proposal, not
  evidence, and not reviewed. Nothing reads a dream as a fact (see Guardrails).
- **Dreams stay local by default.** `.daedalus/dreams/` is gitignored by `init` and `hydrate`, like
  `.daedalus/reflection/`. `daedalus dream keep <id>` copies a dream to `docs/dreams/<date>.md`, to
  be committed if the owner chooses; that is how `docs/dreams/2026-10-15.md` would have been made.

### Seeds (deterministic, no model calls)
- `daedalus dream seeds` ranks candidate seeds from what Daedalus already keeps:
  - open questions in `docs/status.md`;
  - tasks in progress past `doctor.stale_task_days`;
  - open dissents;
  - roadmap items in `backlog` for a long time, and intake dropped more than once;
  - gaps marked `○` in `docs/design/tui/coverage.md`, where the project has one;
  - unresolved contradictions and unmoved aspirations from the latest monthly report;
  - the latest reflection report's findings.
- **Readiness** is scored from four things, as in Cass's `seed_selection`:
  - age;
  - how often the thing recurs across digests and reports;
  - recent activity;
  - whether several sources point at the same thing (convergence).
- A dream takes at most `dream.seeds` seeds (default 5), drawn from at least two kinds where it can.
- **The owner may give a theme** (`/dream about the TUI`). It becomes the first seed and the others
  are ranked around it.
- The seeds and their scores are written to `seeds.json`, so the seeds a dream came from can always
  be read back.

### The dream (model-written, hot)
- `dream.mode` in the global config is `list`, `narrative` or `ab` (default `ab`).
  - **`list`** is the shape of the first dream. The dreamer writes at least 30 ideas, from small to
    absurd, one or two lines each. It doesn't check feasibility or hedge, and it doesn't stop to
    rank.
  - **`narrative`** is Cass's shape. A narrator, "the Labyrinth", speaks the seeds as a place, in
    present tense and second person, and transmutes them rather than transcribing them. It never
    explains or advises. The dreamer answers knowing it is dreaming. It runs a fixed number of
    turns (`dream.turns`, default 4). The dream never ends early on a keyword; Cass's
    "wake"/"leave" check was found to fire by accident.
  - **`ab`** picks `list` or `narrative` at random in code, logs the seed and records the mode,
    as 0010's `reflect arm` does. The skill text never chooses.
- **A `morpheus` agent ships with the plugin.** Morpheus is the shaper of dreams. It is the dreamer
  in both modes, and the narrator in `narrative` mode as a second instance.
  - It reads only the seeds bundle (`daedalus dream bundle`), plus the identity files for its
    voice.
  - It never reads earlier dreams, the gameplan's next task, or Momus's verdicts. Seeing them first
    would mostly restate them.
- **While dreaming, nothing judges.** Momus doesn't review dream content, and the dreamer isn't
  asked for citations, confidence labels or feasibility.
- **Where the runner allows, the dream runs at a high temperature** (`dream.temperature`, default
  0.9). Under the `inhale` runner the temperature can't be set, so the prompt carries the whole
  frame. The dream log records which case applied.

### The waking pass (model-written, cold)
- A separate agent instance that did not dream reads `seeds.json` and `dream.md`, and writes
  `waking.md`:
  - for a `narrative` dream, the ideas it holds, stated plainly as a list;
  - the three to five it would most want built, each with the seed it grew from and what would
    make it real.
- **Each pick gets a stable ID** (`<dream-id>#<n>`) and the label `speculative`. Picks aren't
  claims about the record, so they need no citation, and Momus doesn't review them.
- **Where the runner allows, the waking pass runs at a low temperature** (`dream.waking_temperature`,
  default 0.3).

### The way into the plan: the `dream` source
- A first-party source named `dream` registers on 0011's seam. `daedalus source sync dream` brings
  each waking pick in as a `roadmap-new` proposal:
  - `origin: {source: "dream", external_id: "<dream-id>#<n>"}`;
  - `item_type: "idea"`;
  - `status: "backlog"`;
  - the pick's text, with a link to its dream file.

  The owner applies or drops it like any intake. Drops are remembered (0011).
- **The `dream` source has no write-back.** A dream can't be closed from the plan. A built idea
  is a done roadmap item whose origin is a dream, and that is what the monthly count reads (see
  Experiment).
- **Nothing else carries a dream into the plan.** No hook, skill or reflection step turns dream
  content into a gameplan task, an edict, a model entry or a memory note.

### Recurring ideas: the dream review
The dreamer never reads earlier dreams, so an idea that comes back has been reached again
independently, not repeated from memory. That makes recurrence a signal worth acting on.
- **When it runs.** A dream review runs monthly, alongside the monthly reflection, and on request
  (`daedalus dream review`). It is due only when there have been at least `dream.review_min`
  dreams (default 4) since the last review. It uses the same runners and guardrail as dreams.
- **The bundle is deterministic.** `daedalus dream bundle review` gathers:
  - every idea and waking pick since the last review, with its dream ID;
  - the earlier reviews' recurring themes, so one can keep growing across reviews;
  - the roadmap items and gameplan phases and tasks, by ID and title;
  - which dream-origin items were applied, dropped or built.
- **The review is model-written.** A cold agent (not the dreamer, not delphi) groups ideas that
  are the same idea in different words into **themes**. It writes `.daedalus/dreams/reviews/<month>.md`
  with each theme that appeared in at least `dream.recur_min` dreams (default 3). For each theme it
  gives:
  - the idea IDs it was built from;
  - how many dreams it appeared in;
  - whether it is **integrated**: a roadmap item, phase or task already covers it. The review names
    that item's ID, or says none does.
- **Elevation.** A recurring theme that nothing integrates is elevated. The `dream` source brings it
  in as a `roadmap-new` proposal with:
  - `origin: {source: "dream", external_id: "theme:<theme-id>"}`;
  - `item_type: "idea"`, `priority: "P1"`;
  - the label `recurring (<n> dreams)`;
  - links to the dreams it came from.

  A theme already integrated is listed in the review and not proposed.
- **A drop is respected, but not forever.** A dropped theme isn't proposed again until it has
  recurred in at least `dream.recur_min` more dreams since the drop. Then the proposal says it was
  dropped before, and when. Dropping it a second time retires it, and it is only listed in later
  reviews. This is the "remember why things died" half: an idea the owner keeps turning down
  but the dreams keep finding is itself worth seeing.
- **Recurrence isn't evidence of value.** The review says how often an idea came back, not
  whether it's right. Nothing in the review is cited by reflection, and Momus doesn't review it,
  like the dreams.
- **Built themes are counted.** The experiment log records, per review:
  - the number of themes, recurring themes and elevated themes;
  - for each elevated theme, whether it was applied, dropped or built.

  That shows whether elevation finds ideas worth building that a single waking pass missed.

### Guardrails: a dream is never evidence
- **Reflection doesn't cite dreams.**
  - `reflect check` rejects any citation to a dream file or a dream-origin roadmap item used as
    evidence.
  - `delphi`'s bundles leave dreams out, except that the monthly bundle carries one fact: the
    count of dream-origin items applied and built.
- **The user and self models never take an entry from a dream.** There is no dream path into the
  models, unlike Cass's `integrate_dream_insights`. Aspirations stay as 0010 defines them: written
  by `delphi`, asked cold.
- **The inhale brief shows at most one line about dreams:** "a dream from <date> is waiting
  (`daedalus dream show`)". It never shows dream content, so a session can't mistake it for
  instruction.
- **A dream can't bind anything.** For an idea from a dream to bind, it goes through the `dream`
  source into the roadmap, and from there into the plan the usual way. For something to become an
  edict, the owner writes it.

### When it runs
- **A dream is due after a reflection run**, at most one scheduled dream a day. Days without a
  reflection have no scheduled dream, and missed dreams don't pile up. `daedalus dream due` prints
  whether one is due and why. Its state lives in `.daedalus/dreams/due.json`.
- **Runners are 0010's, with the same guardrail.**
  - `inhale`: the default. Inhale says a dream is due after offering the reflection, and asks
    whether to run it now or defer. A dream runs as subagents, so only `waking.md` reaches the main
    context.
  - `local` or `headless`: run only where `machine.employer` is explicitly `false`.
- **On request.** `/dream [theme]` runs one at any time, whether or not one is due. That is how the
  first dream happened.
- **It never runs from a hook.** Hooks make no model calls (0007).

### Experiment
Whether dreaming earns its slot is an open question, so it is recorded like 0010's:
- `.daedalus/dreams/log.jsonl` is append-only, written only by deterministic commands. Each record
  holds:
  - the date, mode and runner, and whether the temperature was set;
  - the seed count and kinds, the idea count and pick count;
  - the agents' model IDs and the tokens spent;
  - for each pick: whether it was synced, applied or dropped, and whether its item reached `done`.
- No free text goes in it: no seeds, ideas or picks. So it can be shared, like 0010's log.
- `daedalus dream log` summarizes per mode:
  - the share of picks applied;
  - the share of applied picks built;
  - the median days from dream to `done`.
  That comparison is the A/B. The minimum number of dreams per mode before drawing any conclusion
  is left to the benchmark 0010 already defers to.
- **The monthly reflection report gains one deterministic line:** how many dream-origin items were
  built that month. It doesn't judge the dreams themselves.

## Acceptance criteria
- **The commands exist:** `daedalus dream seeds`, `bundle`, `due`, `show [id]`, `keep <id>`,
  `review` and `log`. So do the `/dream` skill and the `morpheus` agent.
- **Seeds are deterministic.**
  - The same project state gives the same seeds and scores, and a test checks this.
  - A fixture project with each seed kind produces each kind.
  - A given theme is the first seed.
- **Modes.**
  - `ab` assigns the mode in code and records it, and a test checks that the skill text has no
    path to choose it.
  - `narrative` runs exactly `dream.turns` turns, and a test checks that a reply containing "wake"
    doesn't end it.
- **Dreams are files with the label.** Each dream's three files exist and open with the speculative
  label. `.daedalus/dreams/` is ignored by git after `init` and `hydrate`. `keep` writes
  `docs/dreams/<date>.md`.
- **The `dream` source.**
  - It registers through the `daedalus.sources` entry point.
  - It syncs each waking pick as a `roadmap-new` proposal with `item_type: "idea"`.
  - Re-syncing adds nothing, and a dropped pick isn't proposed again.
  - It declares no write-back.
- **The dream review.**
  - `dream review` is due only after `dream.review_min` dreams since the last review.
  - Its bundle lists every idea and pick since then, with the roadmap and plan IDs.
  - A fixture with one theme in three dreams and no matching roadmap item gives a `roadmap-new`
    proposal labelled `recurring (3 dreams)`. With a matching item, it gives no proposal and the
    review names the item.
  - A dropped theme isn't proposed again until it recurs `dream.recur_min` more times, and a second
    drop retires it.
  - Each of these has a test with a stubbed review agent.
- **Guardrails, each with a test:**
  - `reflect check` rejects a report citing a dream file;
  - `delphi`'s bundles contain no dream content;
  - no code path writes a model entry with a dream as its source;
  - the inhale brief carries at most the one line, and never dream text.
- **Scheduling.**
  - `dream due` is true after a recorded reflection run, and false again once a dream runs that day.
  - It refuses `local` and `headless` unless `machine.employer` is `false`, as 0010 does.
  - Nothing in hooks imports the dream modules or makes a model call, and a test checks this.
- **The log.** It holds counts, IDs, labels, modes and dates only, and a test greps a log made
  from a fixture dream for its idea text and finds none. `dream log` reports the per-mode shares.
- **The first dream.** `docs/dreams/2026-10-15.md` is kept as the record of the first dream, in
  the `list` shape, and the docs point to it as an example.

## Non-goals
- **No port of `genesis_dream.py`.** Daemon birth isn't dreaming.
- **No integration of dream content into the models,** and no Momus review of dreams.
- **No dream visualizations,** and no dream symbol library in v1. Cass has one; it can come later
  if picks keep reusing symbols.
- **No dreams from hooks,** and no network access beyond the model runner.
- **No changes to Cass's system.** Two bugs found while reading it go to the cass-vessel side,
  separately:
  - the prompt names `get_dream`/`discuss_dream`, but the tools are `recall_dream` and
    `add_dream_reflection`;
  - the 00:05 cron may never trigger integration.

## Amendments
- **2026-10-15: readiness fixes from Momus**
  (`.daedalus/momus/trials/2026-10-15-edict-0013-readiness.md`). Where these differ from the text
  above, these govern. Daedalus made them under Kohl's grant of autonomy for that night (see
  `docs/status.md`).
  1. **Runners and temperature (F1).**
     - No runner today can set a temperature. `dream.temperature` and `dream.waking_temperature`
       are logged as `unset` until a runner supports them, and no acceptance criterion depends on
       them.
     - In v1, dreams run under `inhale` or on request only. `reflect tick` never runs a dream, and
       `local` and `headless` dreams are out of scope until T-e5 lands and a later amendment
       specifies them.
  2. **Context and cost (F2).**
     - Only `list` mode runs entirely inside subagents. In `narrative` mode the main session relays
       each turn, so the dream text enters its context.
     - `dream.max_tokens` (default 60000) caps a dream. One that would exceed it stops at the end of
       the current turn and is recorded as `truncated`.
     - Morpheus has no file tools. The session passes the bundle inline and writes output through
       `daedalus dream` commands.
  3. **Log writers and outcomes (F3).**
     - `daedalus dream start` draws the mode in code, logs the draw's seed, and creates the dream's
       directory.
     - `daedalus dream done <id>` takes the model IDs, tokens, temperature case, and idea and pick
       counts, and appends one `run` record.
     - Sync, apply and drop of `dream` items append `resolution` records, as in 0010.
     - `dream log` joins the records with the roadmap's current state when it is read.
     - Pick IDs are `<dream-id>.p<n>`, and idea IDs `<dream-id>.i<n>`, assigned by code parsing
       `dream.md` and `waking.md`. No `#`.
     - "Built" means the item's status is `done`, timed by `status_changed_at`. The roadmap writes
       that on every status change (core, not only the two sites that write it today).
     - The monthly "dream-origin items built" line is added to the report by code (`reflect
       render`), not written by delphi.
  4. **A no-dream arm (F4).**
     - `dream.mode` gains `plain`: the same seeds, asked for "ideas worth building", with no dream
       frame and no speculative label in the prompt. The output is still stored and labelled as
       speculative.
     - `ab` draws among `list`, `narrative` and `plain`.
     - `dream show`, the waking pass and the proposal text never reveal the mode.
     - `dream log` also reports the built-rate of non-dream roadmap intake as a baseline.
     - Whether dreaming beats its baseline is `untested` until each arm has the number of dreams the
       benchmark sets.
  5. **The `dream` source on the 0011 seam (F5).**
     - `Source` gains `priority(remote)` (default `P2`). `idea` becomes a valid roadmap `item_type`.
       The `recurring (<n> dreams)` label is the first line of the item's description.
     - Drops are recorded as `{key: {count, last_dropped_at, recurrences_at_drop}}`. Core skips a
       dropped key unless the source returns it with `reproposable: true`.
     - The `dream` source sets that only when the drop count is 1 and the theme has recurred
       `dream.recur_min` times since the drop. At a count of 2 the key is retired.
     - A pick's link is the command `daedalus dream show <id>`, never a path. Applying a pick
       publishes its text into the committed roadmap, and `dream show` says so.
     - The `dream` source is not implicit. `init` enables it only when dreaming is on.
  6. **Seeds, v1 (F6).** The seed kinds are:
     - stale tasks;
     - open dissents;
     - backlog items, aged by `created_at`;
     - `○` rows in `coverage.md`'s detail tables;
     - the latest reflection report's `findings`;
     - bullets under a `## Open questions` heading in `docs/status.md`, aged by the file's last
       commit.

     Drop counts, contradictions and unmoved aspirations become seeds once their sources exist.

     Readiness is `0.4·age + 0.3·recurrence + 0.2·activity + 0.1·convergence`. Each term is
     normalised to 0..1 within the candidate set. Convergence counts the other seed kinds that share
     a roadmap item ID, task ID or path with the seed. Ties break by seed ID. A theme seed always
     ranks first. The clock is injectable.
  7. **Recurrence (F7).**
     - The review agent groups idea IDs into themes. It is not told `recur_min`.
     - Code counts the distinct dreams per theme, and checks that every idea ID and roadmap ID it
       names exists. A theme naming an unknown ID is dropped from the review.
     - A theme is elevated only if it appears in at least `recur_min` dreams that don't share a top
       seed. The review reports both the dream count and the distinct-top-seed count.
     - Theme IDs are assigned by `daedalus dream review record`. It matches a new theme to an
       earlier one only by shared idea IDs.
     - Only an *applied* dream-origin item counts as integrating a theme; a pending one doesn't.
     - Reviews are written to `reviews/<date>.md`.
  8. **Testable guardrails (F8).**
     - The model-write API in `reflection/models.py` rejects evidence whose source isn't a session
       digest, an identity file or a memory note. A static test asserts that `reflection/models.py`
       and `reflection/pending.py` import nothing from the dream package.
     - `reflect check` scans a report's text and proposals for `.daedalus/dreams/`, `docs/dreams/`,
       dream, idea and pick IDs, and the IDs of `dream`-origin items. It rejects any it finds.
     - The inhale brief reads `.daedalus/dreams/due.json` as raw JSON and imports no dream module.
       It shows one combined line, covering both "due" and "waiting".
  9. **Minor points.**
     - "After a reflection run" means after any `run` record in 0010's experiment log dated after
       the last dream.
     - The `dream.*` keys register in 0011's config registry, with descriptions.
     - `keep` refuses a dream whose seeds include a `private`-scoped item in a `work` project,
       unless `--include-private` is given.
     - The first dream is kept by merging branch `docs/dream-2026-10-15`.
     - Cass's wake check matches four words; the point stands that keyword waking is dropped.
- **2026-10-15: from Momus's build review (`.daedalus/momus/trials/2026-10-15-edict-0013-build.md`).** Recurrence is
  independent when the dreams' seed *sets* differ, not their top seeds: seeds are deterministic, so unchanged state
  gives the same seeds, and the recency penalty that varies the top seed would otherwise make reordered material look
  independent. A recurring theme on unchanged project state is therefore not elevated; it needs new material or an
  owner's theme. `dream keep` refuses to overwrite an existing file unless `--force`. Made under Kohl's overnight grant.
