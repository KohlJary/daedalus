The project in {DIR}/project/ was built from the spec in {DIR}/spec.md by a pipeline of small local models. It is a first draft: some of the spec may be missing or wrong, and the code and tests may need cleanup.

Polish it into something you'd be happy to ship: make it implement the spec exactly, fix bugs, and improve the code and tests where that's worth doing. Keep what already works rather than rewriting it from scratch.

Work only inside {DIR}/ : do not read, list, or search anything outside it. Run tests with `python3 -m pytest -q -p no:cacheprovider` from the project directory. Do not commit. Reply with a two-line summary of what you changed.
