# Ophanic in Daedalus

Ophanic is Kohl's notation for drawing structure in plain text: fixed-width box-drawing characters, where nesting
means containment, side by side means a row, and `◆Name` refers to a component defined elsewhere
([Ophanic](https://github.com/KohlJary/ophanic)). Daedalus uses it two ways (edict 0017):

- **Design:** layout and UI are drawn before they're built, and the drawing is the spec. The TUI was designed this
  way (`docs/design/tui/*.oph`).
- **Relationships:** anything with more than a couple of related parts (edicts that depend on each other, phases
  holding tasks, workstreams whose claims collide) is shown as a diagram, not a list.

Two commands do the work. Neither calls a model.

```bash
daedalus oph check [paths]          # lint diagrams as drawn (default: docs/design)
daedalus oph map edicts|plan|workstreams|intake [--width 100|60|34] [--json]
daedalus oph draw graph.json        # any graph, same renderer
```

## Layout conventions
- One diagram per `@variant` line (`@desktop`, `@narrow`, `@empty`). In Markdown, a diagram lives in a fence
  marked ```` ```oph ````, closed by a ```` ``` ```` on its own line; other fences aren't linted.
- A diagram is a run of rows. A row starts with a box character (`┌ │ ├ └`) or an arrow (`▼ ▲ ▶ ◀`), or holds only
  line characters and arrows (a connector: `    │`), or is text with a box on its right (`Header ┌───┐`). A
  `note:` line after the diagram is a note, not content.
- `◆Name` refers to a component: a `## ◆Name` section in the same directory's `.oph` files, a file whose title
  is the name, or a class in code (`--components`, or the `oph.components` setting).
- Shared dividers are fine (`┬ ┼ ├ ┤ ┴`), and so are rounded corners and dashed lines (`┄ ┈ ╌`, `┆ ┊ ╎`). One box
  family per diagram: light (with rounded and dashed), heavy or double.
- **Width.** No row is wider than 100 columns (display columns: a wide character counts two). *Box rows*, those
  that start at the diagram's left edge with a box side or corner and end with one, agree within a band: a run of
  consecutive box rows. A framed layout is one band, so every row matches. A connector row ends a band, so boxes
  stacked under it may be narrower. Connector rows, arrow rows and rows with a label on the left aren't measured,
  and trailing spaces never count. Maps come out at 100, 60 or 34.
- **What counts as text.** Text between two runs of a border is a title (`┌─ Title ────┐`). An arrow with no line
  coming into it is text (`│ Sort by ▼ │`, `│ ▶ Section │`). A run of `─` that joins nothing is a divider
  (`─ done (3) ─`). An arrow that *does* have a line coming into it must point at something.

## Relationship conventions
- **Slugs** name things inside a diagram: `█` + a letter + a number (up to four digits). The number is assigned
  per diagram, in ascending ID order per kind, with two digits, or three when a kind has more than 99 (`█T001`); an
  edict keeps its own number (`█E13`).

  | Letter | Kind |
  |---|---|
  | E | edict |
  | P | phase |
  | T | task |
  | R | roadmap item |
  | W | workstream |
  | S | source |
  | M | module |
  | C | claim or collision |
  | N | anything else |

  These letters are Daedalus's own: in Ophanic's social-memory spec, R is a relationship and E an event.
- **Legend:** one line per slug under the diagram, `█E13: 0013 Dreaming`, so a reader can leave the diagram and
  find the real thing. Every slug used has a legend line, and every legend line is used.
- **Containment** is nesting: a line inside a box belongs to it (`· [>] T-e5 local backends`).
- **Edges:** `a ─▶ b` means a depends on, or points at, b.
  - An edge between adjacent layers is *drawn* as an arrow line inside the source's box (`─▶ █E10 █E11`).
  - Every other edge is *listed* under the diagram (`█E13 ─▶ █E06`).
  - By hand, an edge between two boxes may also be a line attached to their sides: `│──────▶│`, `│◀──────│`,
    or dashed `│┄┄┄┄▶│`. A slug inside it names the edge (`│─█R11─▶│`, with its own legend line). `oph check
    --json` reads these as edges between the two boxes' first slugs (or `null` for a box with no slug), with the
    edge's slug as `via`, per file and per diagram.
  - An edge to something that isn't in the graph is listed as `missing: 0011 ─▶ 0008 (no node 0008)`, and so is a
    child whose parent is missing: a map never drops what it can't draw.
- **Collisions** (`map workstreams`) are boxes of their own (`█C01 alpha collides with beta`), pointing at the two
  workstreams they involve. A collision is never drawn as one workstream's arrow to another, which would read as a
  dependency.
- **Duplicates.** Two nodes with one ID, or two edicts with one number, get different slugs, and a `note:` under
  the map says so.
- **No colour.** States are text marks: `[done]`, `[>]`, `[ ]`.

## Example: `oph map edicts`
The output of `daedalus oph map edicts` on a project holding six of this repository's edicts (0004, 0006, 0007,
0010, 0011, 0013). 0011 depends on 0008, which this project doesn't have, so it's listed as missing.

```oph
┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
│ Edicts: each box points at the edicts it depends on                                              │
│                                                                                                  │
│ ┌─────────────────────────────────────────────┐                                                  │
│ │ █E04 Exhale and inhale as plugin skills     │                                                  │
│ │ [done]                                      │                                                  │
│ └─────────────────────────────────────────────┘                                                  │
│                                                                                                  │
│ ┌─────────────────────────────────────────────┐                                                  │
│ │ █E07 Memory backbone                        │                                                  │
│ │ [done]                                      │                                                  │
│ │ ─▶ █E04                                     │                                                  │
│ └─────────────────────────────────────────────┘                                                  │
│                                                                                                  │
│ ┌─────────────────────────────────────────────┐  ┌─────────────────────────────────────────────┐ │
│ │ █E06 Memory reconstruction                  │  │ █E11 Sources and roadmap intake             │ │
│ │ [done]                                      │  │ [done]                                      │ │
│ │ ─▶ █E07                                     │  │ ─▶ █E07                                     │ │
│ └─────────────────────────────────────────────┘  └─────────────────────────────────────────────┘ │
│                                                                                                  │
│ ┌─────────────────────────────────────────────┐                                                  │
│ │ █E10 Reflection over session logs           │                                                  │
│ │ [accepted]                                  │                                                  │
│ │ also: the `local` runner depends on T-e5    │                                                  │
│ │ ─▶ █E06                                     │                                                  │
│ └─────────────────────────────────────────────┘                                                  │
│                                                                                                  │
│ ┌─────────────────────────────────────────────┐                                                  │
│ │ █E13 Dreaming                               │                                                  │
│ │ [done]                                      │                                                  │
│ │ ─▶ █E10                                     │                                                  │
│ └─────────────────────────────────────────────┘                                                  │
└──────────────────────────────────────────────────────────────────────────────────────────────────┘
█E10 ─▶ █E04
█E10 ─▶ █E07
█E13 ─▶ █E06
█E13 ─▶ █E11
missing: 0011 ─▶ 0008 (no node 0008)
█E04: 0004 Exhale and inhale as plugin skills
█E06: 0006 Memory reconstruction
█E07: 0007 Memory backbone
█E10: 0010 Reflection over session logs
█E11: 0011 Sources and roadmap intake
█E13: 0013 Dreaming
```

## Example: a flow drawn by hand
Hand-drawn diagrams use the same lint. Side edges, vertical connectors and stacked boxes of different widths all
pass:

```oph
┌───────────────────┐       ┌───────────────────┐
│ █E13 Dreaming     │─█R01─▶│ █E10 Reflection   │
└─────────┬─────────┘       └───────────────────┘
          │
          ▼
┌───────────────────┐
│ █E06 Reconstruct  │
│ ▶ confidence      │
└───────────────────┘
█E13: 0013 Dreaming
█E10: 0010 Reflection over session logs
█E06: 0006 Memory reconstruction
█R01: reads digests from
```

## Why Daedalus doesn't use Ophanic's parser
The `ophanic` package's parser (`ophanic.parser.parse`) is not ready for Daedalus's diagrams. These were found on
2026-10-15 and checked by running the parser on each diagram below, for Kohl to file or fix upstream. The diagrams
here are plain fences, not ```` ```oph ````, because they are the parser's failures, not Daedalus's.

1. **Shared-divider grids collapse.** Boxes are found only from `┌`, and tracing stops at the first `┬`/`┤` or
   `├` (`ophanic/box_detector.py`). Every variant of every `docs/design/tui/*.oph` file parses to a single node.

   ```
   ┌─────┬─────┐
   │ ◆A  │ ◆B  │
   └─────┴─────┘
   ```
   This should be a row of A and B; it parses as the single component A.
2. **Direction inference.** With stacked rows also present, side-by-side boxes come back as a column
   (`hierarchy.py`, `infer_direction`: any pair of children without vertical overlap makes the whole set a column).

   ```
   ┌───────────────┐
   │ ┌────┐ ┌────┐ │
   │ │ ◆A │ │ ◆B │ │
   │ └────┘ └────┘ │
   │ ┌───────────┐ │
   │ │ ◆C        │ │
   │ └───────────┘ │
   └───────────────┘
   ```
   This should be a column holding a row (A, B) and C; it parses as one column of A, B, C.
3. **Silent failure.** The error classes exist (`errors.py`), but nothing raises them: a broken box yields an
   empty document.

   ```
   ┌──────┐
   │ ◆A
   └──────┘
   ```
   This should raise `UnclosedBoxError`; it parses to a document with no breakpoints and no error.
4. **Notes.** There is no `note:` construct. This is an absence, with no failing diagram: in the cases tried, a
   `note:` line under a diagram is dropped silently rather than read as content, so a note is lost, not misread.
5. **Box styles.** Rounded and double-line boxes aren't recognised.

   ```
   ╭──────╮
   │ ◆A   │
   ╰──────╯
   ```
   This should be the component A; it parses to a document with no breakpoints (the same for `╔═╗ ║ ╚═╝`).

## Deferred in v1
Edict 0017 allows these to follow later without failing the rest; v1 doesn't have them:
- **`oph map palace`**: the codebase's module groups and their cross-group calls, from the Mind Palace query graph.
- **The send-form A/B** in the TUI (Gameplan panel sent to Claude as a diagram or as prose, assigned per send).
  Now built on its own branch, for five panels: `tui.send_form` (`prose`, `text`, `ophanic`, `ab`). Under `ab`, the
  arms are `text` and `ophanic`, which carry the same facts, so they differ in form alone. Each send is logged
  without its content. See [Send form](design/tui/README.md#send-form) in the TUI's design README. Judging whether Claude did
  better with the diagram, through reflection's digests, is still to come.
- **`oph outline`**: reading a layout back into a box tree, for the frontend half.

## For Momus
*A paragraph for Kohl to add to Momus's constitution if they want it (it's Kohl's to amend):*

> When a document under review includes a diagram, check it against what it claims: every edge it draws exists,
> every nesting is true, every slug resolves in its legend. Run `daedalus oph check` on it. A diagram that passes
> the lint can still be wrong about the world; that part is yours.
