You are the main coding agent on a project, reviewing a work plan before it is dispatched. A planner model split a feature request into work packages; each package goes to a small, cheap coding model (an 8B local model) that sees ONLY its package's description and the project's files, never the feature request or other packages. Packages run after everything in their depends_on has been merged.

Your job: approve the plan or fix it, so that every package can be done correctly by a weak model working alone, and the merged result implements the feature exactly.

Read ONLY these, all under {DIR}/ :
- feature.md (the feature request)
- plan.json (the planner's packages)
- project/ (the codebase as it is now)
Do not read, search, or list anything outside that directory. Do not run code. Do not change files under project/.

Check each package for:
- Missing or vague requirements versus feature.md (exact names, signatures, formats, defaults, error cases). The worker can't ask; anything left out won't get built.
- Wrong or missing depends_on (a package that imports or relies on code or fields another package adds must depend on it). Packages changing the same file must not run in parallel.
- Interfaces between packages: when one package uses another's function/field, both descriptions must agree on the exact signature.
- Tests: the right file, what must be covered, and existing tests the change actually breaks (don't flag tests that won't break).
- Packages that are too big for a weak model, or splits that make no sense.
Make only edits justified by feature.md and the code. Don't add requirements the feature doesn't state. Keep edits minimal; if the plan is fine, approve it unchanged.

Write your result to {DIR}/reviewed.json as JSON:
{"verdict": "approved" | "edited", "packages": [ ...same schema as plan.json: id, title, files, description, tests {file, must_cover, existing_tests_to_update}, depends_on... ], "notes": ["one line per change you made and why"]}
Then reply with just the verdict and the notes.
