# Human review — the memory playtest through the new stack (cycle-6 t10, spec h6)

The human evaluator (Ori) reviewed
[`m-memory-longhorizon`](memory-longhorizon.report.md) using the replay with
its embedded assessor guide, plus the GIF export — the h6 condition: the match
judged through the shipped surfaces, findings recorded verbatim, the cycle-3
h15 pattern.

## What worked

- *"T10 Memory reply looks amazing"* — the redesigned replay passed the eye it
  was built for.
- *"\[The assessor's guide\] is amazing and helps a lot."*
- *"I liked the play."* / *"Both scouts were amazing."* — the reviewer could
  follow and enjoy the match's strategy from the replay alone.

## Findings — presentation (each already commissioned as work)

1. **The GIF shipped in the old visual style.** Direction given: Anthropic
   cream for light mode, Culture black-green for dark, team colors moved off
   red/blue to fit; both modes kept first-class.
2. **Playback wasn't smooth**: *"instead of turn by turn, it should feel 100%
   smooth"* — *"I currently see the step accelerate-decelerate, instead of
   continuous movement."* The per-turn eased transition reads as lurching;
   playback must interpolate linearly and gaplessly across turn waypoints
   (and the GIF gains tween frames).
3. **Guide placement**: *"I need to scroll up and down for the assessor's
   guide… location is hard to work with. Maybe utilize better the screen
   width, and use tabs."* — a tabbed side panel keeping the board in view.

All three land in the `feat/replay-theme-restyle` branch.

## Findings — the game itself

1. **Simultaneous co-occupied delivery**: *"H units both entered the post at
   the same time and delivered — is that by design? Or should they block hand
   over (with a possible lockdown strategy)?"* Confirmed **by design today**:
   sole-occupancy rules apply only to capture streaks; the deliver square is
   non-exclusive, and generated boards share ONE center deliver mission by
   fairness construction. The reviewer's blocking/lockdown proposal would make
   delivery a contestable resource — a genuinely new strategic dimension
   (denial play). → **next-frame candidate**, with the continuous lane's
   duration/race mechanics as its natural home.
2. **The house defender underperformed**: *"Red D unit flopped — either due
   instructions or failure in performance."* (It was `vanguard`'s defender
   under fog — the strategy never adapted to losing the economy race, matching
   the t8 report's finding 3.) The reviewer could see the flop but the system
   offers no per-unit accounting to say *how badly* or *why* —
   which motivates:
3. **Per-unit grading — MVP/LVP**: *"We need 'Best unit (MVP)' and 'Worst
   unit (LVP)' — grades per unit per role (a unit should get more points for
   the designated purpose of its role — a scout not scouting should still get
   points, but less if it's not a scouting task, etc.)"* → **next-frame
   candidate**: role-purpose-weighted per-unit contribution grades derived
   from the log, surfaced in the score payload, the replay, and the guide.
4. **Role constraints make the game better**: *"Scouts should not be able to
   take posts — only be the 'eyes' (like a reviewer). It would make the game
   more interesting to see constraints to units."* The capability machinery
   already exists (cycle 6's explorer cannot gather or capture, enforced by
   engine legality; role tables are scenario-declared data) — adopting
   eyes-only scouts as a default, and generally leaning into per-role
   constraints, is a game-design decision. → **split on review**: the
   constraint half (scout cannot take posts) was applied immediately to the
   in-flight cycle-7 continuous lane by user directive (default role table +
   race-scenario rework, hash regenerated deliberately pre-publish); the
   "eyes" half (scout actively reducing fog) lands with the continuous-fog
   generalization in cycle 8, where MVP/LVP grading makes the eyes-only role
   scoreable. The grid lane's classic scout stays frozen; grid scenarios can
   already declare the constraint via role-capability data.

## Guide sufficiency (the h6 meta-question)

The reviewer judged strategy and unit-level performance from the replay and
guide alone — including a per-unit verdict (game finding 2) the guide itself does
not yet compute. That gap is the strongest sufficiency finding: the guide
teaches team-level coordination well, but the reviewer's eye went one level
deeper than the guide could follow. Game finding 3 (MVP/LVP grades) is the direct
remedy and closes the loop between what a human judges and what the system
scores.
