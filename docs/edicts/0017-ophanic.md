# Edict 0017: Ophanic, Daedalus's spatial language
Status: accepted
Depends on: Edict 0012 (the TUI and its .oph designs); Edicts 0008, 0011, 0013 for the structures it maps

*Numbered 0017 after a collision with the toolbox-hooks edict (0016, another session's). Drafted by Daedalus at Kohl's request ("first class Ophanic understanding, for both the obvious frontend design
stuff and just generally the concept of using spatial diagrams to represent compound relationships between things")
on the night of 2026-10-15, from a survey of the Ophanic repository (`~/ophanic`: SPEC.md, the parser, the plugin,
doc/ophanic-implications.md, doc/text-is-all-you-need.md, doc/ophanic-social-memory-SPEC.md, the A/B test).*

## Intent
Make Ophanic (fixed-width box-drawing diagrams with `◆Component` references) a language Daedalus thinks and
works in, for two jobs.

1. **Design.** Layout and UI work is drawn before it's built, and the drawing is the spec. This already happened:
   edict 0012's TUI was designed as 48 `.oph` diagrams, and `◆` composition turned shell changes into two-line
   edits. Ophanic's own A/B test (one run each, graded by its author) found the diagram-spec attempt implemented all
   three breakpoints where the prose-spec attempt implemented none; at N=1 effort or chance is a live rival, which
   is why an experiment comes with this edict (`experiments/ophanic-perception/`).
2. **Compound relationships.** Daedalus keeps a lot of structure, and today it shows it only as lists:
   - edicts that depend on each other;
   - phases that hold tasks that point at roadmap items that came from sources;
   - workstreams with claims that collide;
   - modules that call each other.

   A spatial diagram shows nesting, adjacency and flow at once. The working thesis (Kohl's "Text Is All You Need") is
   that text grids are what a language model reads best, for people and for Claude alike.

Ophanic's notation is ready to adopt; its parser isn't. The survey found it:
- collapses shared-divider grids, the style every Daedalus diagram uses;
- infers side-by-side boxes as a column when stacked rows are also present;
- returns bare labels for `docs/design/tui/gameplan.oph`;
- fails silently.

So Daedalus owns its tooling: a lint that understands the notation as drawn, and renderers that produce diagrams
from Daedalus's own state. It doesn't depend on the parser. Fixes found along the way go upstream as issues,
separately.

## Constraints

### The notation, documented here
- **`docs/ophanic.md`** is Daedalus's reference. It covers two things:
  - the layout conventions: boxes, `◆Name`, `@variant`, `## ◆Name` sections, and `note:` lines below a diagram,
    which the lint treats as notes, not content;
  - the relationship conventions, from the social-memory spec:
    - an **edge** is a line ending in an arrow (`─▶`, `◀─`, `▼`, `▲`), optionally labelled with a slug;
    - a **slug** is `█<letter><nn>`, and resolves in a **legend**, one line per slug, under the diagram;
    - **containment** is nesting: an edict box inside a phase box means the phase implements it;
    - **adjacency** is relatedness without direction.
- **Slug letters are fixed:**

  | Letter | Kind |
  |--------|------|
  | `E` | edict |
  | `P` | phase |
  | `T` | task |
  | `R` | roadmap item |
  | `W` | workstream |
  | `S` | source |
  | `M` | module |
  | `C` | a collision or conflict |

  Each legend line names the real ID (`█E07: edict 0007 Memory backbone (done)`), so a reader can leave the diagram
  and find the thing.
- Widths are 100 columns for full diagrams, 60 for narrow and 34 for in-column panels, as in docs/design/tui/.

### `daedalus oph check` (deterministic, no model)
It lints `.oph` files and Ophanic blocks in Markdown (fenced ```oph). It reports, each with a line number:
- a diagram whose rows differ in width;
- a box whose corners or junctions don't join (a `┬` with nothing below it, a `├` with no matching `┤` or
  border);
- a `◆Name` with no `## ◆Name` section in the same file and no component it's told about (`--components` takes a
  list or a Python package to scan for classes, as scripts/check_oph_widgets.py does today);
- an edge slug with no legend line, and a legend line no edge uses;
- mixed box styles in one diagram.

It exits 1 on findings, and `--json` gives them as data. It replaces scripts/check_oph_widgets.py: the TUI's check
calls it. `daedalus doctor` runs it on `docs/design/**/*.oph` when the folder exists, as findings.

### `daedalus oph map <subject>` (deterministic, no model)
Each map renders a diagram of Daedalus's own state, from the same library functions the CLI uses, within the
widths above:
- **`plan`:** the active workstream's phases as boxes, each holding its task slugs with status marks (`[x]`, `[>]`,
  `[ ]`). Edicts are drawn as the box's tag, with a legend.
- **`edicts`:** each edict as a box with its status, and `─▶` edges from each edict to the edicts its `Depends on:`
  line names. Done edicts are drawn grey with a text mark, not colour alone.
- **`workstreams`:** each workstream as a box containing its claims. Collisions (`doctor.check_collisions`) are `█C`
  edges between the colliding claims.
- **`intake`:** sources, then roadmap items by origin, then the phases that pull them in, left to right with
  `─▶`. Items no phase references are drawn in a separate "waiting" box.
- **`palace [module]`:** a module's submodules as nested boxes, with the busiest call edges between them, at most
  `--edges` (default 12). It needs the palace's index; without one, it says so.

Every map passes `oph check`. Every map has `--width` and `--json`; the JSON is the graph the diagram was drawn
from (nodes, containment, edges), so a test can check the drawing against the data.

### The skill and the agents
- **A shipped `ophanic` skill** says when to draw:
  - before building any layout or UI;
  - when explaining something with more than a couple of related parts;
  - when a reader would otherwise get a list of relationships.

  It also says how: the conventions above, `daedalus oph check` before showing a diagram, and
  `daedalus oph map` rather than drawing Daedalus's own state by hand.
- **The labyrinth and docs agents** mention `oph map palace` and `oph map plan` as ways to show structure.
- **Momus** checks any hand-drawn diagram in a document he reviews against what it claims: edges that exist, nesting
  that's true.

### Using it with Claude
- **The TUI's Send to Claude** gains a choice of form for a panel: prose (the default) or Ophanic, where the panel is
  sent as its `oph map` equivalent.
- **This is the first of the dream's picks** (dream-2026-10-15.p2), and it's built as an experiment, as 0010 and 0013
  are: a setting `tui.send_form` takes `prose`, `ophanic` or `ab`. Under `ab` the form is drawn in code and logged
  with the session, so whether Claude does better with diagrams can later be measured. The benchmark that measures
  it isn't this edict.
- **No session-start prompt carries a map.** The cache rule from 0014's draft applies: maps go in when someone asks
  for them.

### Upstream
- Daedalus doesn't import the `ophanic` package in v1.
- Problems found in Ophanic's parser are written up in `docs/ophanic.md` with a minimal failing diagram each, for
  Kohl to file or fix upstream. Daedalus doesn't file them itself.

## Acceptance criteria
- **The reference.** `docs/ophanic.md` exists, with both sets of conventions and a worked example of each map.
- **`oph check`.**
  - Each lint has a fixture that triggers it and a clean fixture that doesn't.
  - Every file in docs/design/tui/ passes.
  - scripts/check_oph_widgets.py is replaced, and the TUI's ◆ test still passes through `oph check --components`.
- **`oph map`.**
  - Each map renders from a fixture project.
  - Its output passes `oph check`.
  - Its `--json` lists every node and edge drawn.
  - A test checks that each edge in the drawing is in the data and the other way round.
  - `oph map edicts` on this repository draws 0013's dependency edges to 0010, 0011 and 0006.
- **Doctor.** `daedalus doctor` reports a malformed design diagram.
- **The skill.** The `ophanic` skill ships, the TUI's README links it, and the labyrinth and docs agents mention it.
- **The TUI.** Send to Claude with `tui.send_form: ophanic` pastes a diagram for the Gameplan panel, and under `ab`
  the form is drawn in code and recorded in the session's reflection digest.
- **Upstream notes.** `docs/ophanic.md` lists the parser problems found, each with its failing diagram.

## Non-goals
- No dependency on the `ophanic` package's parser, no React generation, no Figma import.
- No drawing by a model inside `oph map`: maps are deterministic.
- No colour-only meaning in any diagram.
- No change to Ophanic's own repository from here.

## Amendments
- **2026-10-15: readiness fixes from Momus** (`.daedalus/momus/trials/2026-10-15-edict-0016-readiness.md`). Where
  these differ from the text above, these govern. Made by Daedalus under Kohl's overnight grant. The edict stays
  `proposed` until Kohl accepts it.
  1. **`◆` resolution.** A `◆Name` resolves against:
     - every `## ◆Name` section in the same directory's `.oph` files;
     - every file title in that directory (a screen's title defines it);
     - `--components` (or the `oph.components` setting), when given. A class `Name` or `NameScreen` counts.

     `doctor` uses the directory rule plus `oph.components` when set.
  2. **Slugs.**
     - Numbers are assigned per diagram, per kind, in ascending ID order, from 01. An edict uses its own number
       (`█E13`). There are at most 99 per kind; more than that goes legend-only.
     - The letters are Daedalus's own, and differ from the social-memory spec's (there R is a relationship and E an
       event). `docs/ophanic.md` says so.
  3. **Layout and fit.**
     - Maps use a layered layout (a node's depth is its longest path from a source), with ties broken by ID.
     - Only edges between adjacent layers are drawn. Edges that skip a layer, and edges that would cross, are listed
       under the diagram as `█E13 ─▶ █E06`.
     - Labels are cut with `…` to fit. When even that doesn't fit the width, the map is legend-only and exits 0.
     - `--json` marks each edge `drawn` or `listed`.
  4. **The edge test isn't circular.** `oph check --json` reads drawn and listed edges from the diagram text by
     itself. The test compares that set with `oph map --json`, in both directions, and two mutation tests must fail
     it: reversing one arrow, and deleting one edge.
  5. **Data.**
     - `edicts.depends_on(edict)` reads the `Depends on:` block up to the first blank line. Each four-digit number is
       an edge; anything else (branches, task IDs, `none`) is listed as external.
     - `map plan` draws the phases, and the active phase's tasks. Phases with no tasks show their status only. The
       roadmap link is drawn only where it exists.
     - `map intake` is tested on a fixture. It may be empty on a real repository, and says so.
     - `doctor` gains a structured `collisions()` that returns `(kind, a, b)`, separating edict collisions from path
       claims.
     - `map palace` builds from source through the query graph (no saved palace is needed): submodules are grouped by
       subdirectory, each edge is labelled with its count of resolved cross-group calls, and the top `--edges` are
       drawn, with the palace's static-analysis note under the map.
     - No colour anywhere: a done edict is marked `[done]`.
  6. **The send-form A/B** is assigned per send, not per session, and recorded as its own `send_form` record:
     form, seed, panel, and whether the owner edited the text before sending. The prose form is the panel's own text
     (`panel_text()`). v1 covers only the Gameplan panel. `tui.send_form` is registered in the config schema. It is
     built last and may be deferred without failing the other criteria.
  7. **Widths.**
     - `oph map` produces 100, 60 or 34 columns.
     - `oph check` requires every row of a diagram to have the same length (in display columns), and at most 100.
       Hand-drawn diagrams may use any width up to that.
  8. **Lint definitions.**
     - The box families are light (including rounded `╭╮╰╯`), heavy and double. A diagram uses one.
     - Edge runs (lines with an arrow at one end, slugs inside) may attach to a box's side.
     - Only fences marked ```` ```oph ```` are linted; other fences, like the README's screen map, are not.
     - A legend belongs to the diagram directly above it: each `@variant` has its own.
     - The social-memory spec's sample is not a clean fixture.
  9. **The general concept.** `daedalus oph draw <graph.json>` renders any graph: nodes with optional parents, and
     edges with labels. Each `oph map` is a producer of that format, so the renderer is general and Daedalus's own maps
     are uses of it. Reading a layout back into a box tree (`oph outline`, for the frontend half) is the first
     deferred follow-up, not v1.
  10. **Momus's agent file** is Kohl's to amend. This edict supplies the paragraph (`docs/ophanic.md`, "For Momus"),
      and Kohl adds it.
  11. **Build order:** `oph check`, `depends_on`, `map edicts`, `map plan`, `draw`, `map workstreams`, `map intake`,
      the skill and doctor, `map palace`, then the send-form A/B. The skill's criterion becomes behavioural: given the
      skill, a session asked to explain a project's structure produces a diagram that passes `oph check`, checked in a
      pilot transcript.
  12. **Deferred from v1** (recorded 2026-10-15, after Momus's trial of the build): `map palace`, the send-form A/B,
      and `oph outline` are not in v1, as items 6, 9 and 11 allow. `docs/ophanic.md` lists them under "Deferred in
      v1". The skill's pilot transcript (item 11) has not been run.
