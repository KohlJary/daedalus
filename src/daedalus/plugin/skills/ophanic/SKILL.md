---
name: ophanic
description: "Draw structure as an Ophanic diagram (box-drawing text) instead of describing it. Use before building any layout or UI (draw it first; the drawing is the spec), when explaining anything with more than a couple of related parts (dependencies, containment, flows), and whenever a reader would otherwise get a list of relationships. For Daedalus's own state use `daedalus oph map`; for anything else write graph JSON and use `daedalus oph draw`, or draw by hand and lint with `daedalus oph check`."
allowed-tools: Bash, Read, Write
---

# Ophanic

A diagram shows nesting, adjacency and flow at once; a list makes the reader rebuild them. Conventions are in
`docs/ophanic.md` (in Daedalus's repository) or `daedalus oph --help`.

## When
- **Before building a layout or UI:** draw every variant (`@desktop`, `@narrow`, empty and error states) as
  `◆Component` boxes first, agree it with the user, then build from it.
- **Explaining structure:** dependencies, what contains what, what flows where. Three or more related parts is the
  threshold.
- **Not for:** a single fact, a sequence of steps (a numbered list is clearer), or prose arguments.

## How
1. **Daedalus's own state:** don't draw it by hand. `daedalus oph map edicts`, `plan`, `workstreams` or `intake`
   (`--width 60` for narrow output).
2. **Any other graph:** write `{"title", "nodes": [{"id", "label", "kind", "mark"?, "parent"?}], "edges": [{"from",
   "to"}]}` to a scratch file and run `daedalus oph draw <file>`. It lays it out, assigns slugs and writes the legend.
3. **By hand** (layouts, or when the renderer's layered layout doesn't fit the idea):
   - equal-width rows, at most 100 columns, one box family;
   - `◆Name` for components;
   - slugs and a legend for edges.
   Then run `daedalus oph check <file>` before showing it. Fix every problem it reports.
4. Put a diagram in Markdown inside a fence marked `oph` so it's linted.

A diagram that passes the lint can still be wrong: say what it shows in a sentence, and check its edges against
the source.
