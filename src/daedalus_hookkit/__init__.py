"""
The hook kit (edict 0016): every Claude Code hook Daedalus registers runs through here.

It's a top-level package, not part of `daedalus`, because `import daedalus` alone costs 60-90 ms (its
`__init__` re-exports the labyrinth) and a PostToolUse hook runs on every tool call. Nothing here
imports `daedalus`, click or platformdirs at module level. A feature imports what it needs inside its
own function, and only once its condition is met.

One dispatcher per event (`daedalus-hook <Event>`) reads the hook's JSON from stdin once, runs each
enabled feature, applies the noise budget, and prints in the form the docs give that event. Stop,
PreCompact and SessionEnd never print: any Stop output continues the turn, and the other two never
reach the model. A dispatcher always exits 0.
"""
