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
- One diagram per `@variant` line (`@desktop`, `@narrow`, `@empty`). The diagram is the run of lines that start
  with a box character; a `note:` line after it is a note, not content.
- `◆Name` refers to a component: a `## ◆Name` section in the same directory's `.oph` files, a file whose title
  is the name, or a class in code (`--components`, or the `oph.components` setting).
- Shared dividers are fine (`┬ ┼ ├ ┤ ┴`), and so are rounded corners. One box family per diagram: light (with
  rounded), heavy or double.
- Every row of a diagram has the same width, at most 100 columns. Maps come out at 100, 60 or 34.

## Relationship conventions
- **Slugs** name things inside a diagram: `█` + a letter + a number. The number is assigned per diagram, in
  ascending ID order per kind; an edict keeps its own number (`█E13`).

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
  - Every other edge is *listed* under the diagram (`█E13 ─▶ █E07`).
  - An edge between two boxes may also be drawn as a line that attaches to their sides: `│─█R11─▶│`.
- **No colour.** States are text marks: `[done]`, `[>]`, `[ ]`.

## Example: part of this repository's edict map

```oph
┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
│ Edicts (a slice)                                                                                 │
│                                                                                                  │
│ ┌─────────────────────────────────────────────┐                                                  │
│ │ █E07 Memory backbone                        │                                                  │
│ │ [done]                                      │                                                  │
│ └─────────────────────────────────────────────┘                                                  │
│                                                                                                  │
│ ┌─────────────────────────────────────────────┐  ┌─────────────────────────────────────────────┐ │
│ │ █E06 Reconstruction                         │  │ █E10 Reflection                             │ │
│ │ [done]                                      │  │ [done]                                      │ │
│ │ ─▶ █E07                                     │  │ ─▶ █E07                                     │ │
│ └─────────────────────────────────────────────┘  └─────────────────────────────────────────────┘ │
│ ┌─────────────────────────────────────────────┐                                                  │
│ │ █E11 Sources                                │                                                  │
│ │ [done]                                      │                                                  │
│ │ ─▶ █E07                                     │                                                  │
│ └─────────────────────────────────────────────┘                                                  │
│                                                                                                  │
│ ┌─────────────────────────────────────────────┐                                                  │
│ │ █E13 Dreaming                               │                                                  │
│ │ [done]                                      │                                                  │
│ │ ─▶ █E06 █E10 █E11                           │                                                  │
│ └─────────────────────────────────────────────┘                                                  │
└──────────────────────────────────────────────────────────────────────────────────────────────────┘
█E13 ─▶ █E07
█E06: 0006 Reconstruction
█E07: 0007 Memory backbone
█E10: 0010 Reflection
█E11: 0011 Sources
█E13: 0013 Dreaming```

## Why Daedalus doesn't use Ophanic's parser
The `ophanic` package's parser is not ready for Daedalus's diagrams. These were found on 2026-10-15, for Kohl to
file or fix upstream:

1. **Shared-divider grids collapse.** Boxes are found only from `┌`, and tracing stops at the first `┬`/`┤` or
   `├` (`ophanic/box_detector.py`). Every variant of every `docs/design/tui/*.oph` file parses to a single label
   node. A minimal case:

   ```
   ┌─────┬─────┐
   │ ◆A  │ ◆B  │
   └─────┴─────┘
   ```
   This should be a row of A and B; it parses as one label.
2. **Direction inference:** with stacked rows also present, side-by-side boxes come back as a column
   (`hierarchy.py`, `infer_direction`).
3. **Silent failure:** the error classes exist, but nothing raises them.
4. **Notes:** there is no `note:` construct, so notes under a diagram become content.
5. **Box styles:** rounded and double-line boxes aren't recognised.

## For Momus
*A paragraph for Kohl to add to Momus's constitution if they want it (it's Kohl's to amend):*

> When a document under review includes a diagram, check it against what it claims: every edge it draws exists,
> every nesting is true, every slug resolves in its legend. Run `daedalus oph check` on it. A diagram that passes
> the lint can still be wrong about the world; that part is yours.
