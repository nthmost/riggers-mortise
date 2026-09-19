# Rigger's Mortise

Jack into whatever LLMs are alive nearby and drive them from the CLI.

A *rigger* jacks into the fleet and drives whatever's on the network; a *mortise*
is the socket half of a joint you slot things into. So: a socket you jack into
that drives whatever machine-spirits are in range.

Unlike a fixed-endpoint chat client, `mortise` treats nearby compute as a **live,
changing thing you probe** — it finds what's awake right now (across raw Ollama
hosts, LiteLLM routers, or a live LAN sweep), shows you the fleet, and lets you
drive any of it. It speaks each backend's **native** API, so it doesn't depend on
any router being up.

## Install

`mortise` is a CLI you want on your PATH everywhere, so install it with
[pipx](https://pipx.pypa.io/) (isolated venv, `mortise` on your PATH):

```bash
pipx install git+https://github.com/nthmost/riggers-mortise.git
```

Or from a local checkout, editable (so edits take effect without reinstalling):

```bash
pipx install --editable ~/projects/git/riggers-mortise
```

Either way you get the `mortise` command globally (`which mortise` →
`~/.local/bin/mortise`). To upgrade later: `pipx upgrade riggers-mortise`.

The routing server (`mortise serve`) needs two extra deps:

```bash
pipx inject riggers-mortise fastapi uvicorn      # for a pipx install
pip install 'riggers-mortise[serve]'             # for a pip/venv install
```

<details>
<summary>Plain venv (no pipx)</summary>

```bash
cd ~/projects/git/riggers-mortise
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
```

Note: this only exposes `mortise` while that venv is activated.
</details>

## Usage

```bash
mortise                     # scan: what's alive nearby, best default first
mortise ask "explain zfs"   # one-shot; auto-picks the best rig, streams the reply
mortise ask -m loki.local/qwen2.5-coder:14b "refactor this"   # force a rig
echo "summarize this" | mortise ask                           # stdin works too
mortise chat                # interactive REPL; suggests a rig, you confirm
mortise chat -m sonnet      # REPL against a specific model
mortise fanout "prompt"     # run one prompt across several rigs, show all answers
mortise judge  "prompt"     # fan out, then a capable rig picks the best
mortise brain  "task"       # a local model orchestrates the fleet, delegating subtasks
mortise stoke fast          # keep the fastest rig hot so it never cold-starts
mortise stoke qwen3:8b --off  # let a rig go cold again, releasing its memory
```

The scan view:

```
                             nearby rigs
 #  MODEL               HOST          SIZE   WARM  SPEED      CONV  SRC    API
 0  qwen2.5-coder:14b   loki.local    14B    🔥    62 tok/s   💬3   known  ollama
 1  mistral-small:24b   styx.local    24B    ·     18 tok/s   ·     known  ollama
 2  llama3.1:70b        styx.local    70B⚠   ·     —          ·     known  ollama
```

`WARM` = currently loaded in memory (no cold-start). `SPEED` = observed
throughput on that host, measured from real generations (`—` until you've run
it there). `CONV` = stored conversations you've had with that model. A `⚠` on
the size means the model is too big to run well on that host's RAM.

### How auto-pick ranks rigs

When you don't name a model, mortise picks with a **balanced score** — a good
rigger doesn't treat every vehicle the same just because it has the same
mortises. The score blends:

- **warmth** (already loaded → no cold-start),
- **measured throughput** (tokens/sec, learned per host+model as you use them),
- **capability** (larger models score higher),
- minus a **fit penalty** for models too big for the host's RAM.

So the same model on a fast GPU box outranks it on a laptop, and a 70B won't be
the silent default on a 24 GB machine. The machine you run mortise on has its
RAM auto-detected; give remote hosts a hint under `[resources]` in the config.

## Discovery

Three composable modes — enable any subset:

| Mode | What it does | Cost / risk |
|---|---|---|
| `known` | Probe an explicit list of Ollama endpoints via `/api/tags` | Fast, safe. The default. |
| `routers` | Query LiteLLM `/v1/models` on configured routers | Fast; only sees what the router curates |
| `scan` | Bounded TCP sweep of a subnet, then fingerprint responders | **Slow, can trip network defenses** — opt-in |

> **On `scan`:** Ollama does not advertise over mDNS/Bonjour, so this is a real
> TCP port sweep across the subnet you name. It's capped (concurrency-limited,
> short per-host timeout, refuses sweeps over 4096 hosts) but it is the noisy
> option. Leave it out of your default `discovery` and enable it per-run.

## Configuration

Precedence, low to high: **built-in defaults → config file → `MORTISE_*` env vars → CLI flags.**

- **File:** `~/.config/mortise/config.toml` (override path with `$MORTISE_CONFIG`).
  Copy [`config.example.toml`](config.example.toml) to get started.
- **Env:** `MORTISE_DISCOVERY`, `MORTISE_HOSTS`, `MORTISE_ROUTERS`, `MORTISE_SCAN_SUBNETS`
  (all comma-separated).
- **Flags:** `-d/--discovery`, `--hosts`, `--routers`, `--scan-subnet`.

Examples:

```bash
mortise -d known,routers                                   # this run only
MORTISE_DISCOVERY=known,scan MORTISE_SCAN_SUBNETS=192.168.0.0/24 mortise
mortise -d scan --scan-subnet 192.168.0.0/24               # commit to the bit
```

## History & resume

Conversations are saved as JSONL transcripts under
`~/.local/state/mortise/sessions/`, **keyed by model, not by host** — a
conversation is with the model, so you can resume it on whichever machine has
that model awake (start on loki, finish on styx). One-shot `ask` is
**stateless by default** — it never loads prior context.

Continue the latest default conversation with `--resume` / `-r`, which only
applies to a model you've actually talked to already:

```bash
mortise chat -r -m qwen2.5-coder:14b   # reload the latest thread and keep going
mortise ask  -r -m qwen2.5-coder:14b "and in Python?"   # one-shot that remembers
mortise chat -r                        # pick from only the rigs you have history with
```

### Named sessions

For several distinct threads with the same model, name them with
`--session` / `-s`. A named conversation auto-continues whenever you address it
by name (no `-r` needed) — the name *is* the handle:

```bash
mortise chat -s worldbuilding -m qwen3:8b     # open/continue the "worldbuilding" thread
mortise ask  -s coding "and the async version?"   # continue "coding", one-shot
```

Watch a thread compound over time:

```bash
mortise log                # list stored conversations (model, turns, when)
mortise log last           # replay the most recent one
mortise log <id>           # replay a specific session
```

The `CONV` column in the scan view (`💬N`) shows which nearby rigs you already
have conversations with, and the REPL prints a `[turn N · ~X ctx tokens]` line
after each turn so you can see the context growing.

## As a backend

mortise isn't only a human-driven tool — it's a coordination layer for other
software.

### Routing server (`mortise serve`)

An OpenAI-compatible endpoint where the `model` field is a **routing policy**
over the live, ranked fleet — point any OpenAI client at it and it drives your
whole fleet with automatic selection and failover:

```bash
mortise serve --port 8080     # discovers, caches (30s TTL), routes, fails over
```

```bash
curl localhost:8080/v1/chat/completions -H 'content-type: application/json' \
  -d '{"model":"auto","messages":[{"role":"user","content":"hi"}]}'
```

| `model` | routes to |
|---|---|
| `auto` | best by the balanced score (warm → fast → capable) |
| `fast` | highest measured tokens/sec |
| `capable` | biggest model that still fits the host |
| `cheap` | smallest model |
| `<exact name>` | that specific model, e.g. `qwen2.5-coder:14b` |

Streaming (`"stream": true`) is supported. Unlike a static LiteLLM config, this
is **live and performance-aware**: it routes on what's actually awake and how
fast it is right now, with no config to regenerate.

### Library

The chat path is UI-free and importable:

```python
import asyncio
from mortise import client
from mortise.config import load
from mortise.discovery import discover

async def main():
    rigs = await discover(load())
    rig = client.pick(rigs, "fast")            # or "auto"/"capable"/"cheap"/exact name
    print(await client.complete(rig, "explain zfs"))   # returns a string
    async for tok in client.stream(rig, "and btrfs?"): ...

asyncio.run(main())
```

`client.pick` / `client.order` accept filters (`min_size`, `backend`, `host`),
so you can build your own coordinators over whatever hardware is awake.

**Stoking** keeps a rig hot so the next call never cold-starts — tend the
firebox once on startup and the model stays loaded:

```python
opener = client.pick(rigs, "fast")
await client.stoke(opener)                 # pin in memory (ttl=None); no tokens produced
await client.stoke(opener, ttl=600)        # or stay hot for 600s
await client.unstoke(opener)               # let it go cold, releasing memory
```

`stoke` returns `False` for backends with no warmth to tend (e.g. an openai
router). Warmth is otherwise only *observed* by discovery, never created — so
stoking is the one deliberate way to keep a rig loaded.

### Orchestration verbs

Coordinate *several* models on one task — fan out, then judge:

```python
targets = client.order(rigs, "auto")[:3]                  # top 3 rigs
answers = await client.fanout("draft this", targets)      # concurrent, list[Answer]
verdict = await client.judge("draft this", answers, client.pick(rigs, "capable"))
print(verdict.winner.rig.label, verdict.reason)
```

`fanout` runs the prompt on every rig concurrently (failures captured per-rig,
not raised) and doubles as a way to benchmark throughput across the fleet.
`judge` gives a capable rig the task plus all candidates and returns its pick.
Both are exposed on the CLI:

```bash
mortise fanout --models qwen3:8b,llama3.1:8b "one sentence on X"
mortise judge  --to fast,capable --judge capable "solve this"
mortise fanout -n 4 "prompt"     # top 4 rigs by rank when no set is named
```

## Local brain (orchestrator)

`mortise brain` turns a **tool-capable local model** into an orchestrator: it
reasons on your machine and *delegates* to the fleet, using mortise's verbs as
tools. This is Claude's agentic loop, but the brain stays local and the
"subagents" are your Ollama boxes.

```bash
mortise brain "research X: get a fast model to draft, a capable one to critique, then summarize"
```

The brain (auto-picked as the best tool-capable model on *this* machine, or set
with `-m`) can call:

- `list_rigs()` — see what compute is available,
- `delegate(target, prompt)` — route one subtask (a policy or exact model),
- `fanout_judge(prompt)` — hard subtasks → several rigs, judged best.

It loops — reason → call tools → get results → continue — until it has a final
answer. The delegation trace prints to stderr (so piped stdout stays just the
answer); tool-calling uses Ollama's native support, with a fallback parser for
models that emit a tool call as JSON text.

The tool set lives in a registry (`tools.py`) — real tools (web fetch, shell,
files) are added by appending entries, no loop changes.

## Backends

- **Ollama** (native `/api/tags`, `/api/ps`, `/api/chat`) — direct to each host,
  with warmth detection and parameter-size reporting.
- **OpenAI-compatible** (`/v1/models`, `/v1/chat/completions`) — LiteLLM routers,
  and anything else that speaks the OpenAI wire format.

## Development

Resuming work? See [NOTES.md](NOTES.md) — architecture, design decisions,
verified gotchas, the dev/test loop, open questions, and the roadmap.

## Layout

```
mortise/
  cli.py                       # typer CLI: scan / ask / chat / log / fanout / judge / brain / serve
  config.py                    # layered config resolver
  rig.py                       # the Rig record
  client.py                    # UI-free core: complete/stream + pick/order + fanout/judge
  brain.py                     # local orchestrator loop (tool-calling)
  tools.py                     # extensible tool registry (list_rigs/delegate/fanout_judge)
  serve.py                     # OpenAI-compatible routing server
  select.py                    # balanced-score ranking + lookup
  session.py                   # one-shot + REPL, resume (wraps client for the terminal)
  history.py                   # persistent JSONL conversation transcripts
  stats.py                     # observed tokens/sec per host+model
  resources.py                 # host RAM + model-fit checks
  identity.py                  # canonical host identity (alias de-dup)
  ui.py                        # fleet table + streaming output + log viewer
  discovery/{known,routers,scan}.py   # each returns list[Rig]
  backends/{ollama,openai}.py         # discovery + streaming chat per protocol
```

## Status

Discovery (all three modes), the scan fleet-view with warmth/speed/conversation
markers, one-shot `ask`, an interactive `chat` REPL, persistent per-model
history with `--resume` / named `--session` / `mortise log`, resource-aware
balanced ranking, a routing backend usable as a library or an OpenAI-compatible
server (`mortise serve`), multi-model `fanout`/`judge`, and a local orchestrator
`brain` that delegates to the fleet via tool-calling.
