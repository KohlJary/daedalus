# Momus review: gameplan-reconstruction.json (2026-10-13)

Reviewed: ~/wonderland-ai/.daedalus/reconstruction/gameplan-reconstruction.json (not modified).
Method: git show/log on every cited hash, release-notes, analyses 046-048, index.json (HEAD and working copy), mvp-demo run events, one pre-fix test replay.

## 1. T-a1 (headline inference) first

CLAIM (as stated): "Probable root cause found and fixed 2026-06-19 in 5abfd9c ... _delete_artifact_file has existed since 0.6.0 (c0c3d1e, 2026-05-14), so the path was live during the mvp-demo M1 deletion. ... UNVERIFIED LINK: no run log ties the original M1 deletion to this path."
CLAIM (plainly): The decision-filter's file deletion is the likely cause of the May mvp-demo M1 loss, and its fix closes T-a1.
FALSIFIER: Pre-05-18 code did not delete milestone files on that path, or no milestone_plan speech_act appeared in a tdd-design run before M1 vanished.

Checks run:
- The filter existed. `git log -S_delete_artifact_file` gives only c0c3d1e (2026-05-14). At ccaf3f7, agent.py:960-1056 has `_apply_allowed_decisions_filter` calling `_delete_artifact_file(art)` with no milestone exemption. SHOWN.
- tdd-design disallowed milestone_plan back then. `git show ccaf3f7:.../tdd-design.yaml:76-79`: `disallowed_decisions: - milestone_plan - interview_questions - interview_review`. Added in c0c3d1e. SHOWN.
- The deletion really happens on pre-fix code. I extracted ccaf3f7 into the scratchpad and ran e795040's test against it. `test_filter_strips_when_speech_act_in_workflow_disallowed` FAILED at `assert file_path.exists()` (1 failed, 20 passed). SHOWN at code level.
- Milestone artifacts carry a file path. In projects/mvp-demo/.wonderland/runs/20260518T013341/events.jsonl the milestone_plan artifacts have payload keys `slug, order, name, deferred, confidence, path`. SHOWN.
- mvp-demo run evidence. This is the strongest item, and the reconstruction did not find it.
  - Run 20260518T030733 (workflow tdd-design, aborted) has abort_reason "operator-killed; M2 design got stuck on stale M1 milestone reference (M1 milestone file missing from disk)".
  - At 03:08:02-03:08:41Z Rabbit, Alice and Caterpillar all quote M1's consumes_requirements, so M1 was on disk then.
  - At 03:08:49Z white_rabbit published a speech_act=milestone_plan on thread "composition" with artifacts=0 and body "M1 milestone revised to strip post-launch infrastructure requirement...".
  - In the legitimate planning run (013341) every milestone_plan utterance carries 4-5 milestone artifacts. The filter runs before bus.publish (agent.py:943-955), so a milestone_plan with 0 artifacts is the filter's signature.
  - The first Dodo coverage-gap report after that (03:09:22) names only m2.
  - The M1 file's mtime is 03:32Z, after the aborts. M2-M4 files are untouched.
  - This fits a single-milestone restatement deleting exactly one file.
- No unlink log exists for mvp-demo (the wrapper shipped in ccaf3f7, after the run). The pre-filter artifact list was not recorded and no ArtifactSuppressed event is in events.jsonl. So the link is circumstantial, not recorded.

RIVAL EXPLANATION (omitted by the reconstruction): agent file tools.
- Roadmap item ccf5fdfe (created 2026-05-20, backlog) records a second M1 loss on mvp-demo-rerun-A "after an M2 design pass that 'tried to fix a requirement'", unlogged, with "Likely cause: an agent used the write_file or delete_file tool".
- 0.9.0 (d41d3c0, 2026-05-20, inside the window) shipped "Tools delete-guard on substrate-of-record paths" for exactly that hypothesis (release-notes/0.9.0.md:158-162).
- Neither ccf5fdfe nor the 0.9.0 delete-guard appears anywhere in the reconstruction. So the unlogged mvp-demo-rerun-A loss has two candidate paths, each with its own fix.
- 08e60dd0 and the 0.8.0 notes say M1 was lost "twice" on mvp-demo. I could locate one occurrence (030733). The second is unaccounted for.

Other errors in the T-a1 wording:
- "the tracing wrapper proposed here could never have caught it" is stale. The wrapper (`_log_milestone_unlink`) already shipped in ccaf3f7 (release-notes/0.8.0.md:11-13; milestone.py:55). The gameplan task text is just out of date. The fact that 5abfd9c's deletion is unlogged is correct (5abfd9c message).
- The 5abfd9c incident was wwu on 2026-06-19 via the P21 diagram meeting. The mvp-demo mechanism is tdd-design, so "the diagram meeting" is not what happened in May.

VERDICT: CONSISTENT, strongly (not shown). The mechanism existed and ran in tdd-design before 05-18, and the mvp-demo timeline fits it closely. The proposed `done` also leaves the 0.9.0 delete-guard path unmentioned and ccf5fdfe open.
CHEAPEST TEST to settle it: replay the mvp-demo 030733 pre-filter utterance. Look in projects/mvp-demo/.wonderland/memory (episodic store) or telemetry for white_rabbit's 03:08:49 utterance artifacts. If it holds a milestone artifact with path = the m1 file, that is shown. Otherwise, run the old ccaf3f7 code with that utterance. Cost: minutes, no LLM calls.
WHAT WOULD CHANGE MY MIND: the raw 03:08:49 utterance had no milestone artifact, or M1 was already absent before 03:08:49.
Recommendation: mark T-a1 `done (probable cause, fix e795040-tested)` and keep ccf5fdfe / 08e60dd0 linked rather than closing them as proven.

## 2. Per-task verdicts

| ID | Verdict | Reason |
|---|---|---|
| T-a1 | consistent | See section 1. Mechanism and timeline fit; no raw pre-filter record; rival path (agent delete_file, fixed d41d3c0) omitted; stale "wrapper proposed" wording. |
| T-a6 | shown | Still pending. grep of src/tests for `milestone_satisfaction` finds nothing. 20cb7af, 1554e4b, de3f192 exist and say what is claimed. |
| p20 phase note | consistent | T-a7 resolved in gameplan (committed 05-18) and ae959d3 says "Phase p20-autonomous-pilot". But "done once T-a1 closes" ignores that T-a6 stays pending, which the same note admits. |
| R-1 | shown | 458ee6f feat(substrate): cost-reduction pass - FindingKind + Lever A/C; c2cf326 release 0.8.1. |
| R-2 | shown | c8bf599 -> 60b534f (0.8.2); 51b3f88 -> c45981e (0.8.3). |
| R-3 | shown | All six hashes match subjects (f49254c exec_smoke_probe, 93306e6/6597a1f/34f37c9, bd882be, 37527f8). |
| R-4 | shown | d41d3c0 message: RequirementAxis, MilestoneKind validator, cross-milestone rejection, "$18.91 ... 33% reduction vs ~$28", "494 passing". Omits the delete-guard it also shipped. |
| R-5 | shown | 0.10.0.md:5 "zero output, 16 reruns"; T-ab35/46/34/45/51/52/53 all in notes. |
| R-6 | contradicted (partial) | "saving 52% of tool-result bytes on obol-260522-1": the TOTAL row in 0.10.1.md:62-68 is 53%; 52% is only tweedledum/tweedledee. Also this is a projected saving from stored results ("Estimated savings"), not a measured outcome. |
| R-7 | shown, one misattribution | $30.58/$83.78/63%/15.59/10.91/3.72/"~10x" all in analyses/046:5,30,43,50-52,158. "(~$2-3)" is NOT in 046; it is in paper/drink-me.md:76. Also redux ran on 0.10.1 + branch (046:4), released as 0.10.2. |
| R-8 | shown | 1f4a3f5, 3bb5d28, 5d4144b, 8f7e048 match. |
| R-9 | shown | 2ec94db subject matches. |
| R-10 | consistent | All eight hashes and the revert exist. The stated cause conflicts with the sources: e4e1f4a (the reverted commit) says the 42-minute loop was observed first and e4e1f4a was the attempt to fix it. ffad1cb gives no reason. analyses/047:99-101 ties the loop to "in-the-retry-path scope enforcement". The reconstruction repeats 047 without noting the conflict. |
| R-11 | shown | 0.11.0.md:43-44 "3/3 leaks flagged, 3/3 legit ... cleared. 9 new tests." |
| R-12 | shown | ae959d3 message: opt-in resolver, jsonl, "forcing function - answering questions isn't composing". `git log -S` first adds question_resolver at ae959d3. |
| R-13 | shown | 0.11.0.md:12-20 (T-ab76/78/79, surface agreement guard). Follow-up 966d76a5 shows T-ab78 over-matches (see drift). |
| R-14 | shown | All 11 hashes match P21 subjects. 85b07ca is actually "T-ab78 surface-gating + milestone-scoped diagram seed", so it is half R-13 work. |
| R-15 | shown | 20cb7af, 1554e4b, 9cdefff, de0ae22 match. |
| R-16 | shown | 91d3655, ac5f9f2, d4337f6, 0b3c78f, 87a8bf3 match. analyses/048:33 root cause confirmed. Grouping issue in section 4. |
| R-17 | shown | 35ae713, 543ad29, 0cae098, 77bbac8 match. |
| R-18 | shown | 1471045 is the 0.12.0 release. analyses/048:60-63 and demo/ldr-ophanic/README.md:68 confirm the unpatched staleness bug and the sibling copy. |
| R-19 | shown | 5abfd9c, 8095965, e795040 match. The test fails on pre-fix code (section 1). |
| R-20 | shown | eff2068, de3f192, ffc01a2, cecfc02, 807c233, 2d58776 match. |
| R-21 | shown | 03a1836 matches. |
| R-22 | shown | 3a6f408, 06b0d7d, 82fb702 (merge) match. |
| R-23 | shown | 73c0800 body: "11 genuine M3 tickets auto-aborted", wrestlers, title/championship. Last commit is HEAD. |
| R-24 | contradicted | "No release, analysis, or demo ... Whether the pilot finished is not in the record." True for git, but projects/wwu (gitignored) holds 53 runs, ~$188 cumulative, runs through 20260625T012514, its own git log to 2026-06-24. Phase dates "to 06-23 (last activity)" are wrong for the project. |

Counts (27 entries: T-a1, T-a6, phase note, R-1..R-24): shown 22 (T-a6, R-1..R-5, R-7*, R-8, R-9, R-11..R-23), consistent 3 (T-a1, phase note, R-10), contradicted 2 (R-6 partial, R-24), untested 0.
(* R-7 counted shown with one misattributed number.)

## 3. Numeric and hash audit

- Every cited hash exists and its subject matches the claim. No hash is misattributed to the wrong task. The only cross-task overlap is 85b07ca (T-ab78 and P21, section 2).
- Totals: 95 commits (`git rev-list --count ccaf3f7..HEAD`), 5 phases, 24 tasks: all correct.
- Numbers that do not match their cited source: R-6 "52%" (source 53%), R-7 "(~$2-3)" (not in analysis 046).
- All other numbers match: $18.91, 33%, 494, 16 reruns, $30.58, $83.78, 63%, $15.59, $10.91, $3.72, 3/3, 9 tests, 11 tickets, 42-minute.
- Description says "see REPORT.md for the critic's verdicts". No REPORT.md exists in .daedalus/reconstruction/.

## 4. Roadmap drift

Confirmed: d16bfb33 (T-ab74), 0facd1e4 (T-ab76), 85bd06c2 (T-ab77), c80b4979 (T-ab78) are `backlog` in both HEAD and the working copy, and all four are named in 0.11.0.md:15-18, shipped in ae959d3.
- The note "follow-up 966d76a5 is a separate bug" is correct, but 966d76a5 exists only in the uncommitted working copy.
- 4d257120 is also uncommitted. The reconstruction lists it among "open" items without saying so.
- The index.json diff is +30 lines, adds exactly 3 items (4d257120, 966d76a5, 89a9a3a7 done). Last commit of the file is 2026-06-16, and its mtime is 2026-06-19 11:57. "uncommitted since 2026-06-19" is only roughly supported: the edits are from 06-16/17 timestamps, saved 06-19.

The drift list is far too short. Items in index.json that are still `backlog` but shipped in the window or earlier:
- ccf5fdfe "Milestone unlinking during tdd-design corrupts substrate state" (P1): fixed by 0.9.0 delete-guard (d41d3c0) and/or 5abfd9c. Directly tied to T-a1.
- 98ec46b0 split max_tool_iterations -> 0b3c78f. 884bbad2 empty-response parse errors -> ac5f9f2/91d3655. 0393015e ABORTED misclassification -> 543ad29.
- c10f6d5f P21 diagrams -> 8eacb14..0.12.0. cbed1a0e foundation/capability axis -> d41d3c0. c9a665d0 prime_directive overwrite -> 8f3a69a plus the 0.9.0 prime_directive change.
- 676a4da8 and 5fe6acd1 -> bd882be (its message names both ids).
- Gameplan-done tasks whose roadmap items are still backlog: 24d57b85 (T-a5), 73690727 (T-a3), dc95169a (T-a4), e2d44cac (T-a2), 040f2f3f (T-a7).
The roadmap has 157 backlog / 55 done / 1 in_progress, so the 4-item list implies drift is rare when it is common. I did not verify each candidate beyond title and commit subject.

## 5. Missed or mis-grouped

Unreferenced commits worth a task or a mention (23 of 95 not cited; docs/demo moves omitted):
- Fixes: 5f6db21 (phantom-citation no longer strands operator-queued work), b7d51a7 (surface dedup over-merge), 0dae6b6, 49b0aa1, 5112b29 (M8 processes all blocking reviews), 6d2ecdb, 8f3a69a, e86a550, f6dfdbb (split-don't-straddle; cut M7 cost), a1c81fa (T-ab61), a217027 (P21 c, seed diagrams to Tweedles), e4e1f4a (the reverted commit).
- Pilot directives 0bf0407 (obol), 9582de9 (ldr-dashboard), a279955 (wwu): obol, ldr and wwu pilots are not named as pilots anywhere except obol in R-3.
- Release commits 60b534f and c45981e (0.8.2, 0.8.3) are cited only implicitly via "-> 0.8.2".

Grouping:
- R-16 (tool-loop exhaustion) and R-17 (phantom tickets, tooling) sit in "p21-diagrams" but are not diagram work. They were bundled only by the 0.12.0 release (1471045). The phase name "P21: diagram build-tracker" over-describes them.
- p20b's "R-3 obol pilot fixes" (05-19) and R-4/R-5 are pilot-driven substrate work, not cost reduction per the phase title. Goal text says "cut cost", but R-5 is correctness (cross-milestone bleed).
- R-10 puts T-ab70-73 under "autonomous design layer" though its own resolution says one piece was reverted.

## 6. Wording overclaims

- T-a1 `proposed: "done"` with `confidence: "inferred"`; the resolution opens "Probable root cause found and fixed". The proposed status is stronger than the evidence (consistent, not shown).
- T-a6 and the p20 note carry `confidence: "shown"` for judgments ("still open", "goal was met") that are readings, not tests. Low stakes.
- R-6 reports a projected saving as achieved.
- p22 goal "first relational domain": 73c0800 says the failures were "exposed only by a relational domain", not that wwu is the first one. Unsupported "first".
- R-24 "Whether the pilot finished is not in the record" is false for the working tree (section 2).
- Header "every resolution cites the commits it rests on": R-4, R-5, R-6, R-7 cite releases and analyses, not commits; they are fine, but the claim is loose.

## 7. Verdict

The commit-level work is sound: every hash exists and matches, and 22 of 27 entries are shown. The errors are few: R-6 (52% vs 53%, projection), R-7 (~$2-3 source), R-10 (loop cause conflict), R-24 (wwu has more record than claimed), a missing REPORT.md, and a roadmap-drift list that is incomplete. The T-a1 inference holds up better than the reconstruction itself argued (mvp-demo run 030733), but it is consistent, not shown, and it omits the delete-guard rival and ccf5fdfe.

Outside reader suggested: Kohl, who ran mvp-demo, to say whether M1 vanished in the 030733 window and what the second loss was.
