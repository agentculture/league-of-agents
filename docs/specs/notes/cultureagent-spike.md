# Cultureagent resident-session spike (cycle 2, task t3)

**Goal.** Probe cultureagent's resident-session surface so the resident driver
(a later task) can hold ONE persistent session per game seat for a whole match:
start a session with a chosen backend+model, send a message, get the reply,
send a follow-up into the SAME session, and get a reply that provably remembers
the first exchange — for both a claude-backed seat and a colleague-backed seat
(colleague = the local vLLM Qwen at `http://localhost:8001/v1`, model
`sakamakismile/Qwen3.6-27B-Text-NVFP4-MTP`).

**Probed versions** (2026-07-07): cultureagent 0.12.0 + claude-agent-sdk
0.2.110 + colleague 1.34.0 (all inside the `culture` uv-tool venv — uv's
per-tool install directory, `$HOME/.local/share/uv/tools/culture/` by
default), standalone colleague CLI 1.38.0, claude CLI 2.1.202. File paths
below cite the installed packages relative to that venv.

## The surface map — what cultureagent actually ships

cultureagent (installed under the `culture` uv-tool venv's site-packages,
e.g. `$HOME/.local/share/uv/tools/culture/lib/python3.12/site-packages/cultureagent/`)
wraps five backends under `clients/`: `claude`, `codex`, `copilot`, `acp`,
`colleague`. The session mechanics differ per backend, and the difference is
the whole story of this spike.

### claude backend: a real persistent session, and it is headless-drivable

`cultureagent/clients/claude/agent_runner.py` — class `AgentRunner` — is the
per-nick session holder. Mechanics:

- One `AgentRunner` = one conversation. It runs a prompt queue; each turn calls
  the Claude Agent SDK's `query()` async generator.
- Continuity is SDK session resume: the first turn's `ResultMessage` carries a
  `session_id`; `_make_options()` sets `opts.resume = self._session_id` on
  every later turn. Same class instance → same conversation, indefinitely.
- Crucially, `AgentRunner` takes **no transport**: its constructor is
  `(model, directory, system_prompt, on_exit, on_message, metrics, nick,
  turn_timeout_seconds)`. The IRC daemon/supervisor wires it to the mesh, but
  nothing stops a harness from constructing it directly and calling
  `send_prompt()` — which is exactly what the proof below does. **This is the
  resident-session surface the spec's "through cultureagent" anchor needs, and
  it works without an IRC server, nick registration, or daemon lifecycle.**

Dependency note: `claude_agent_sdk` is an *extra*
(`cultureagent[backend-claude]`). The bare `cultureagent` uv-tool venv cannot
import `AgentRunner`; the `culture` tool venv can (it installs the full set).

### colleague backend: NO cross-message memory as shipped — this is the honest finding

`cultureagent/clients/colleague/agent_runner.py` says it outright: *"there is
NO subprocess coding-agent for colleague… its brain IS colleague's own
`colleague.resident.harness.ColleagueHarness`, which runs each inbound message
as one bounded `engine.work` turn."*

`ColleagueHarness.feed_message()` (installed under the `colleague` uv-tool
venv's site-packages, e.g.
`$HOME/.local/share/uv/tools/colleague/lib/python3.12/site-packages/colleague/resident/harness.py`)
does this per message:

```python
task = Task.new(self._repo_path, body, engine=self._engine_name)
result = await loop.run_in_executor(None, engine.work, task, self._config)
```

`Task.new` mints a **fresh task from only the message body** — no prior
exchange is threaded in (the `context=` parameter exists on `Task.new` but the
harness never passes it). The "session" that "outlives any single turn" in the
harness docstring is the *reply-queue lifecycle*, not conversational memory.
`engine.work`'s history windowing is within one turn's tool loop; `colleague`'s
eidetic `memory.py` is an optional tool the loop may call, not a transcript.

**Consequence: one-session-per-seat with provable memory is impossible through
cultureagent's colleague backend as currently shipped.** A codeword planted in
message 1 is simply absent from message 2's model input. The same applies to
`colleague session` (the interactive cockpit): each free-text line becomes an
independent work item through the identical `Task`/loop path.

### The IRC-mesh path: rejected for seats regardless

Driving seats as registered mesh agents (one nick per seat, messages over IRC)
was considered and rejected: it needs a running culture server, per-seat
`culture.yaml` registration, daemon lifecycle management, and asynchronous
reply collection — and it would *still* be amnesiac for colleague seats, since
the daemon feeds the same `ColleagueHarness`. All cost, no continuity gain.

## Continuity proofs

### Proof 1 — claude seat through cultureagent's `AgentRunner` (headless)

Runner script (`claude_runner_proof.py`, run with the `culture` uv-tool
venv's own interpreter, e.g. `$HOME/.local/share/uv/tools/culture/bin/python`):
construct one `AgentRunner`, plant a codeword, follow up in the same
instance.

```python
from cultureagent.clients.claude.agent_runner import AgentRunner

runner = AgentRunner(model="haiku", directory=".", nick="probe-seat-red-1",
                     on_message=on_message)          # queue text blocks
await runner.start(initial_prompt="You are seat red-1 in a game. "
                   "Remember this codeword: ONYX-HERON-12. Reply with exactly: ACK")
reply1 = await replies.get()
await runner.send_prompt("What codeword did I give you? "
                         "Reply with only the codeword.")
reply2 = await replies.get()
await runner.stop()
```

Captured transcript:

```text
turn1 (9.02s) session=None: 'I appreciate the message, but I should clarify a
  few things: … **No persistent memory**: I don't retain information between
  conversation sessions. …'
turn2 (4.42s) session=6b415dcb-c936-42f5-9f63-017d88729c2d: 'ONYX-HERON-12'
CONTINUITY PROVEN (one AgentRunner, one SDK session)
```

The seat lectured about having no persistent memory in turn 1 and then recalled
the codeword in turn 2 — continuity is a property of the session plumbing, not
the model's self-image. (`session=None` on the turn-1 line is a print-timing
artifact: `on_message` fires before the `ResultMessage` that carries the id.)

### Proof 2 — colleague seat via a driver-held transcript over the vLLM OpenAI API

Since cultureagent's colleague path has no memory, the seat session for the
colleague mind is the transcript the driver itself holds — which is what an
OpenAI-style chat session *is*. Stdlib-only (`urllib`), matching league's
dependency-free runtime; two short completions against the live server:

```python
BASE = "http://localhost:8001/v1"
MODEL = "sakamakismile/Qwen3.6-27B-Text-NVFP4-MTP"
payload = {"model": MODEL, "messages": history, "temperature": 0,
           "max_tokens": 128,
           "chat_template_kwargs": {"enable_thinking": False}}
# POST {BASE}/chat/completions; append the assistant reply to history;
# append the follow-up user message; POST again.
```

Captured transcript:

```text
turn1 (0.60s): 'ACK'            # planted: EMBER-KITE-9
turn2 (0.75s): 'EMBER-KITE-9'
CONTINUITY PROVEN
```

**Qwen3.6 gotcha:** it is a hybrid-thinking model. Without
`chat_template_kwargs: {"enable_thinking": false}` it spends the whole
`max_tokens` budget in the `reasoning` field and `content` comes back `None`
(observed: 128-token calls returned `content=None` twice). Either disable
thinking for short tactical replies or budget generously and read
`message.reasoning` too. With thinking disabled the reply was 2 tokens in
0.6 s — while a live playtest was hammering the same server.

### Also proven — `claude -p` CLI resume (the zero-dependency fallback)

```bash
SID=$(python3 -c "import uuid; print(uuid.uuid4())")   # driver-minted seat id
claude -p --model haiku --session-id "$SID" \
  "Remember this codeword: TIDAL-WREN-8. Reply with exactly: ACK"
# → ACK
claude -p --model haiku --resume "$SID" \
  "What codeword did I give you? Reply with only the codeword."
# → TIDAL-WREN-8
```

Driver-minted UUIDs mean no JSON parsing on turn 1 (plain-text output works
throughout); `--output-format json` additionally returns `session_id`,
`duration_ms`, and usage. Sessions persist on disk in the Claude CLI's
per-project session store (its own dotfile directory under the user's home,
keyed by cwd), so a crashed harness can resume a seat mid-match. Mechanically
this is the *same thing* `AgentRunner` does internally (the SDK spawns the
CLI with resume per turn) — the difference is only whose code owns the
session loop.

## Latency notes

| Path | Turn 1 | Turn 2+ | Notes |
| --- | --- | --- | --- |
| cultureagent `AgentRunner` (haiku) | 9.0 s | 4.4 s | SDK/CLI boot dominates turn 1 |
| `claude -p` resume (haiku) | 3.9 s wall (2.6 s API) | 3.4 s wall (2.0 s API) | ~1.3 s process spin-up per turn |
| vLLM chat completions (Qwen3.6, thinking off) | 0.60 s | 0.75 s | live playtest sharing the server |

A resident claude seat costs seconds per turn either way; the colleague seat is
sub-second. Per-turn wall time is dominated by the claude side — plan match
pacing around it.

## TRANSPORT DECISION

**Recommendation: the resident driver holds one in-process session object per
seat, with a per-mind transport.**

1. **Claude seats — cultureagent `AgentRunner`, headless, one instance per
   seat.** `send_prompt()` per turn, replies via the `on_message` callback,
   session resume handled inside the class. This satisfies the c2 spec's
   honesty condition ("through cultureagent sessions, not raw API, not
   `claude -p`") on its exact letter, with no IRC server and no daemon.
   *Packaging trade-off:* league's runtime is dependency-free, so the driver
   must not `import cultureagent` from league's own venv. Two workable shapes,
   in preference order:
   - Subprocess a small seat-runner script (JSONL request/reply over stdio)
     executed with an operator-configured interpreter that has
     `cultureagent[backend-claude]` — default the `culture` uv-tool venv's own
     interpreter (`$HOME/.local/share/uv/tools/culture/bin/python`). Keeps
     `dependencies = []`, fits the existing `command`-driver philosophy, one
     *process and one session per seat for the whole match* (not per turn).
   - Or add a `league-of-agents[resident]` extra that pulls
     `cultureagent[backend-claude]` and import it lazily. Cleaner code, but it
     changes the install story for resident matches.
2. **Colleague seats — driver-held transcript against the vLLM OpenAI endpoint
   (stdlib `urllib`), one `messages` list per seat.** This is the nearest
   workable fallback, because the clean surface does not exist:
   **cultureagent's colleague backend cannot hold a conversation as shipped**
   (`ColleagueHarness` builds a fresh `Task` per message — see the surface map
   above). Sub-second turns, zero dependencies, trivially auditable transcript.
3. **Rejected: the IRC-mesh channel path** — heavy lifecycle, async reply
   plumbing, and still amnesiac for colleague seats.
4. **Fallback of record for claude seats:** `claude -p --session-id/--resume`
   with driver-minted UUIDs — proven, zero-dep, crash-resumable. Use it only
   if the cultureagent-venv subprocess shape proves too awkward, and then
   label the roster accordingly.

**Spec conflict to surface to the cycle (honesty over optimism):** the c2
spec's anchoring condition — *both* minds through cultureagent sessions — is
not satisfiable for the colleague mind today. Options, pick one explicitly:

- amend the spec so the colleague seat's routing is labeled truthfully as
  `colleague-direct` (driver-held OpenAI transcript) while claude seats are
  `cultureagent`; or
- land an upstream change first (cultureagent/colleague: thread prior
  exchanges into `ColleagueHarness` — e.g. accumulate them and pass
  `Task.new(..., context=…)`) and only then claim the anchor for colleague
  seats.

Either way the match log's roster labels must state what actually routed the
messages — do not label a driver-held transcript as a cultureagent session.

**Per-seat isolation holds in every recommended shape:** one session object
(or subprocess) per seat, seats never share a transcript, and inter-seat
coordination stays exclusively in-game messages — the driver only ever puts
briefings and the seat's own history into a seat's context.

## Shipped (t5 postscript)

The resident driver (`league/harness.py`, driver type `resident`) shipped the
**fallback of record** for claude seats — `claude -p --session-id/--resume`
with driver-minted deterministic UUIDs, transport label `claude-cli` — keeping
league's runtime dependency-free instead of subprocessing the culture venv's
`AgentRunner`. Colleague seats shipped the driver-held transcript against the
vLLM OpenAI endpoint, transport label `colleague-direct`, with the Qwen
`content=None` → `reasoning_content` fallback. Per-seat transcripts are
appended to `.league/matches/<id>/sessions/<agent-id>.jsonl`.

## Artifacts

Probe scripts and raw outputs live in the spike scratchpad (session-local,
not committed): `colleague_proof.py`, `claude_runner_proof.py`, and the
`claude_turn{1,2}.json` CLI captures. The transcripts above are verbatim.
