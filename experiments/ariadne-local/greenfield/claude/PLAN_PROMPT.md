You are planning a greenfield build for a team of small, cheap coding models (8B local models). Each worker gets ONE package and sees only that package's description and the project's files, never the spec or the other packages. A package runs only after everything in its depends_on has been merged.

Read {DIR}/spec.md. Read nothing else.

Produce two things:
1. Acceptance tests for the whole spec: these are committed before any worker starts, and Ariadne's verifier runs them against every package. Write them as pytest files under tests/, named tests/test_<module>.py after the module they mainly cover. Test only what the spec states.
2. A work plan: small packages (usually one module), each with a complete, self-contained description (exact names, signatures, formats, errors, and the interfaces it uses from other packages), depends_on, and which acceptance test file covers it.

Write {DIR}/claudeplan.json as:
{"packages": [{"id": "p1", "title": "...", "files": ["..."], "description": "...", "tests": {"file": "...", "must_cover": ["..."], "existing_tests_to_update": []}, "depends_on": []}, ...],
 "seed_files": {"tests/test_<module>.py": "<file content>", ...}}
Then reply with a one-paragraph summary of the plan.
