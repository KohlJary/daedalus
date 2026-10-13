"""Reference implementations, used only to validate that each oracle passes on a correct change.
Each is a list of (file, old, new) exact replacements against base/."""

PYCACHE = [
    ("src/daedalus/worker/harness.py",
     '            self._git("add", "-A")\n',
     '            # Never stage build artifacts, even when the project has no .gitignore covering them\n'
     '            self._git("add", "-A", "--", ".", ":(exclude,glob)**/__pycache__/**", ":(exclude,glob)**/*.pyc",\n'
     '                      ":(exclude,glob)**/.pytest_cache/**")\n'),
]

JUDGE_INTENT = [
    ("src/daedalus/worker/harness.py",
     "    def submit_diff_to_ariadne(self, description: str) -> Optional[str]:",
     "    def submit_diff_to_ariadne(self, description: str, intent: Optional[str] = None) -> Optional[str]:"),
    ("src/daedalus/worker/harness.py",
     "                description=description,\n            )\n",
     "                description=description,\n            )\n            if intent:\n                diff.metadata[\"intent\"] = intent\n"),
    ("src/daedalus/worker/harness.py",
     '                result["diff_id"] = self.submit_diff_to_ariadne(description=title.lstrip("# "))',
     '                intent = work.description\n'
     '                if work.constraints:\n'
     '                    intent += "\\n\\nConstraints:\\n" + "\\n".join(f"- {c}" for c in work.constraints)\n'
     '                result["diff_id"] = self.submit_diff_to_ariadne(description=title.lstrip("# "), intent=intent)'),
]

MODEL_CASTING = [
    ("src/daedalus/config.py",
     "    theseus_analysis: bool = True  # Run Theseus before planning\n",
     "    theseus_analysis: bool = True  # Run Theseus before planning\n"
     "    worker_model: Optional[str] = None  # None: SDK default\n"
     "    judge_model: Optional[str] = None\n"),
    ("src/daedalus/ariadne/orchestrator.py",
     "        self.semantic_reviewer = semantic_reviewer or LLMJudge()",
     "        if semantic_reviewer is None:\n"
     "            from ..config import load_config\n"
     "            semantic_reviewer = LLMJudge(model=load_config().ariadne.judge_model)\n"
     "        self.semantic_reviewer = semantic_reviewer"),
    ("src/daedalus/ariadne/semantic_review.py",
     '    reviewer: str  # "llm-judge" or a human identifier\n',
     '    reviewer: str  # "llm-judge" or a human identifier\n    model: Optional[str] = None\n'),
    ("src/daedalus/ariadne/semantic_review.py",
     '            "reviewer": self.reviewer,\n',
     '            "reviewer": self.reviewer,\n            "model": self.model,\n'),
    ("src/daedalus/ariadne/semantic_review.py",
     '            reasoning=response_text.strip(),\n            reviewer="llm-judge",\n',
     '            reasoning=response_text.strip(),\n            reviewer="llm-judge",\n            model=self.model,\n'),
    ("src/daedalus/ariadne/orchestrator.py",
     '                print(f"description: {diff.description}")\n',
     '                print(f"description: {diff.description}")\n'
     '                print(f"worker model: {diff.metadata.get(\'worker_model\') or \'(SDK default)\'}")\n'
     '                if diff.semantic_review:\n'
     '                    print(f"judge model: {diff.semantic_review.get(\'model\') or \'(SDK default)\'}")\n'),
    ("src/daedalus/worker/harness.py",
     "        isolate: Optional[bool] = None,\n    ):",
     "        isolate: Optional[bool] = None,\n        model: Optional[str] = None,\n    ):"),
    ("src/daedalus/worker/harness.py",
     "        self.isolate = use_ariadne if isolate is None else isolate\n",
     "        self.isolate = use_ariadne if isolate is None else isolate\n        self.model = model\n"),
    ("src/daedalus/worker/harness.py",
     "            options = ClaudeAgentOptions(**option_args)",
     "            if self.model:\n                option_args[\"model\"] = self.model\n            options = ClaudeAgentOptions(**option_args)"),
    ("src/daedalus/worker/harness.py",
     "                description=description,\n            )\n",
     "                description=description,\n            )\n            diff.metadata[\"worker_model\"] = self.model\n"),
    ("src/daedalus/worker/harness.py",
     "    worker = IcarusWorker(\n        work_id=work_id,\n        project_root=project_root,\n        bus=bus,\n        use_ariadne=use_ariadne,\n    )",
     "    from ..config import load_config\n\n"
     "    worker = IcarusWorker(\n        work_id=work_id,\n        project_root=project_root,\n        bus=bus,\n        use_ariadne=use_ariadne,\n"
     "        model=load_config().ariadne.worker_model,\n    )"),
]

REFS = {"pycache": PYCACHE, "judge_intent": JUDGE_INTENT, "model_casting": MODEL_CASTING}
