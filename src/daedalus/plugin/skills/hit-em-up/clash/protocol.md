# Clash

Two MCs, one task, one crowd. Each MC writes a plan of attack on its own, then they battle over it in rounds:
every verse has to answer the one before it, and every bar carries a receipt and a counter-proposal. The crowd
checks every receipt, reacts, and keeps the ledger. What comes out is a plan of record in which every step
traces to an opening plan or a bar that landed, plus the battle transcript: the verses, annotated with what
checked out.

A clash plans; it does not build. It is read-only like a dry run: it reads the board, the code, the palace
and read-only data, and it writes nothing outside the report folder. Hand the plan to a normal run (or
Daedalus) to execute it.

## Arguments and configuration

`clash <task>`: the task is a board item id, an edict number, a file path, or free text in quotes.

Defaults come from `hitEmUp.clash` in '.daedalus/config.json':

```json
"clash": { "red": "full-bore", "blue": "edge-case", "rounds": 3, "frame": "battle", "solo": false,
           "maxBars": 5, "budget": { "verseTools": 30, "checkTools": 6 } }
```

- 'red', 'blue': persona files from 'personas/'. Any two different personas work; the default pair is built
  to disagree (cut against cover).
- 'rounds': the most rounds to run (each round is one verse from each MC). The battle can end sooner.
- 'frame': a file from 'frames/', given to both MCs.
- 'maxBars': the most bars in one verse, answers included. Long verses cost the most to check and their
  extra bars mostly rule FLAT, so the cap makes each MC spend its bars where they will land. When more of
  the opponent's bars need answers than the cap allows, answers come first and the verse carries no new
  attacks.
- 'budget': tool calls per MC verse ('verseTools') and per receipt check ('checkTools'). An agent that hits
  its budget stops and submits what it has; a check that runs out before it can confirm a receipt rules it
  unverified. The host reports the clash's total subagent tokens and wall time at the end.
- 'solo': also produce solo plans for comparison (see Solo comparison). The 'solo' argument sets it for one
  run.

Arguments override config for one run: two persona names (red then blue), a number of rounds, a frame name,
'bars N' (overrides 'maxBars'), 'solo', 'no-verse' (the transcript keeps the bars' claims and rulings in plain
prose; nothing is rhymed).

## Steps

1. **Snapshot.** Record the commit hash of main and the time. Read the task and everything it points at, the
   same way hit-em-up step 2 reads an item. If the task is a board item, the policy's Eligibility still
   applies: an item that belongs to someone else gets a plan for its owner, never a claim on it. Write the
   snapshot (task text, hash, the files and items it touches) to the report folder; every role reads from
   it. Note in the snapshot anything that limits checking, such as a package that will not import, so every
   role knows receipts must be checked by reading rather than running.

2. **Openings, blind.** Spawn one fresh subagent per MC. Each gets its persona file, the frame file, the
   snapshot, and this instruction: read what you need, then write an opening plan of attack (numbered
   steps; for each, what it touches, what it produces, how it is checked, effort small/medium/large) and an
   opening verse of at most 'maxBars' bars. Neither sees the other's opening. Blind openings stop the
   second MC from anchoring on the first.

3. **Seed the ledger.** A fresh crowd subagent (with 'clash/crowd.md') reads both openings and seeds the
   plan of record:
   - steps both openings share (same intent, even if worded differently) enter as **agreed**;
   - steps only one MC proposed enter as **proposed by red** or **proposed by blue**;
   - each opening verse's receipts are checked, but opening bars are not scored for LANDED: with no
     opponent plan yet, an opening bar can only defend a step its own opening already put in the plan, so it
     can never change the plan. A false opening receipt is still BOOED, and a CONTESTED opening bar still
     has to be answered in round 1.
   A proposed step that the other MC never knocks out stays in the plan: silence is assent, so each MC has
   every reason to go after the other's steps.

4. **Rounds.** Verses strictly alternate, red first: red, blue, red, blue. A round is one verse from each MC;
   the order never restarts at a round boundary, so no MC speaks twice in a row and the MC who owes answers is
   always the one who speaks next. Each turn is a fresh subagent with the MC's persona and frame, the
   snapshot, the current plan of record, the full ledger, and the opponent's last verse. Its verse is a set of
   bars. Every bar has three parts (a fourth, hops, when a claim chains facts), written in the transcript as:

   ```
   > the line(s) of the bar
   receipt: file:line, command and its output, failing test, item id, or a quote from the snapshot
   hops: (only for a claim that chains several facts) one checkable file:line or command per line
   move: add | cut | reorder | re-scope | defend <step>, with the exact change
   ```

   A claim that chains facts ("this key comes from there, which is set here, so copied rows replay") lists
   every link under 'hops'. The checker verifies each hop on its own instead of re-deriving the chain, and
   one broken hop BOOs the bar.

   A bar with no receipt or no move is not a bar: the crowd rules it FLAT without checking.

   **Answer the verse first.** A battle is not two people rapping well in the same room; each verse has to
   deal with the one before it. Every verse after an opening starts with an answer to each of the
   opponent's bars from their last verse that was ruled LANDED or CONTESTED, before any new attack. Each
   answer is one of:
   - **concede:** the point stands; say so plainly and build on it (a concession can carry its own move,
     tightening the step the opponent just changed);
   - **rebut:** a new receipt showing the bar's move is wrong, unnecessary or costs more than it saves;
   - **flip:** turn the opponent's own receipt against them (their added step opens a new failure, their
     cut removes the only check on something). The flip is the hardest answer and the crowd's loudest
     reaction, because it uses the opponent's evidence, not new evidence.
   Answers are bars: rebuts and flips need receipts and moves and are ruled like any bar. A concession is
   ruled FLAT unless its own move lands. Bars the opponent got BOOED need no answer; rubbing it in scores
   nothing. New attacks come after the answers.

   After each verse the crowd rules it in two passes:
   - **Checks, in parallel.** Spawn one fresh receipt checker per bar, all at once, on the cheapest capable
     model, each with only that bar, the snapshot and a 'checkTools' budget. A checker opens the receipt and
     every hop and returns confirmed, false or unverified, with the one line of evidence it saw. It does not
     rule; it only says what the receipt shows.
   - **Ruling.** One fresh crowd subagent ('clash/crowd.md') reads the checkers' results, the verse and the
     ledger, rules each bar LANDED, FLAT, BOOED or CONTESTED, and writes one short reaction per bar. It
     re-opens a receipt itself only when a checker's answer is unclear or the ruling would cut real work.
     It writes the round's rulings and score to the ledger first and then applies the LANDED moves to the
     plan of record, so an interrupted ruling never leaves moves in the plan without the rulings behind them.

   The ruling pass also checks the answers: every LANDED or CONTESTED bar from the opponent's last verse that
   the verse did not concede, rebut or flip is ruled **DODGED** (see 'clash/crowd.md'). An MC whose bar was
   BOOED owns it in its next verse, after its answers.

5. **Ending.** Stop after the last round, or earlier when the crowd's quiet rule fires (a round with nothing
   LANDED, a heckle, then another round with nothing LANDED). Say which ended it.

6. **Plan of record.** The host (you, in the plain workplace voice) writes the final plan from the ledger:
   - numbered steps, each with what it touches, what it produces, how it is checked, effort, and its
     **provenance** (agreed, proposed by red/blue and unchallenged, or added/re-scoped by bar N);
   - **contested points** for the owner: the question, both receipts, what each choice costs;
   - **cut along the way**: steps that were knocked out, with the bar that did it;
   - **booed claims**, so nobody builds on them later;
   - the score, and one line on what it says (which MC brought more checked, plan-changing points).
   Then hand the plan to a last fresh crowd subagent to confirm every step's provenance points at a real
   ledger entry. Fix anything it flags.

7. **Write the files** to the policy's report folder (for the Daedalus policy, '.daedalus/reports/'):
   - '<date>-clash-<slug>-plan.md': the plan of record. Plain voice; this is the file that may leave the
     report folder (pasted into a ticket, attached to an edict, handed to a run).
   - '<date>-clash-<slug>-transcript.md': the snapshot pointer, both openings, every verse with its bars,
     receipts, moves and the crowd's rulings and reactions, and the score by round, each verse followed
     directly by its rulings so it reads as a battle. This file stays in the report folder.
   - In the plan, a cost line: subagent tokens and wall time for the openings, each verse and each ruling.

8. **Terminal.** Print the plan's summary (step count, contested points, cuts, score), the paths of both
   files, and the best-landed bar from each MC with its receipt. That is the only verse that reaches the
   terminal; the rest is in the transcript.

## Bar rules

- Diss the opposing MC as a character and the opposing plan: its steps, its gaps, its waste, its cases.
  Never a person, a team, a client, or the authors of the code.
- Original lines only: no quoted or lightly altered lyrics from any real song.
- Specific beats generic: the receipt's file, number or failing case belongs in the bar.
- Answer before you attack. A verse that ignores the opponent's landed bars loses the room, whatever else it
  says.
- A bar may defend as well as attack: a defense needs its own receipt.
- Clean enough to read aloud in a screen share.
- Verses never reach anything another person will see. The plan file is plain prose with no bars in it.

## Solo comparison

For testing whether the battle earns its cost, as the 'compare' mode does for personas.

With 'solo', after the snapshot, also spawn one fresh subagent per persona that plans the task alone (same
snapshot, same instruction as an opening, then one self-review pass with Momus on its own plan). Then hand
the battle's plan of record and both solo plans, with voice, provenance labels and file names stripped and
labelled 'A' to 'C' in random order, to one more fresh subagent. It ranks them on: steps that would fail when
executed (it checks each plan's claims against the snapshot), risks covered that the others miss, steps that
produce nothing a reviewer or a gate will use, and effort. Then unblind and write
'<date>-clash-<slug>-vs-solo.md' with the ranking, the reasons and the token cost of each arm. One task is an
anecdote: say so, and say how many tasks would make it evidence.

## Never

- Never write outside the report folder, take an outward-facing action, or claim work on the board during a
  clash.
- Never put a step in the plan of record that has no ledger entry behind it.
- Never let the score decide the plan.
- Never let a verse reach anything another person will see.
- Never let an MC write to the ledger or the plan of record. MCs write only their own verse file; only the
  crowd rules and applies moves.
