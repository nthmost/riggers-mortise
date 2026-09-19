# NOTES — Rigger's Mortise (developer / resume doc)

Pick-it-up-later notes for hacking on mortise. User-facing usage is in
[README.md](README.md); this file is the "where were we / why is it like this"
doc. Current version: **0.7.0**.

## What it is

`mortise` is a CLI + library that discovers whatever LLMs are alive nearby and
lets you drive, route, and orchestrate them. Named for the Shadowrun *rigger*
(jacks in, pilots a fleet) + the *mortise* woodworking joint (the socket you
slot into).

The arc it grew along (each is a shipped layer, not a rewrite):

1. **Discover** what's awake (Ollama hosts / LiteLLM routers / LAN scan)
2. **Chat** with it — one-shot `ask`, REPL `chat`, persistent history, `--resume`, named `--session`
3. **Rank** rigs resource-awarely (warmth + measured tok/s + capability − oversized penalty)
4. **Backend** — a UI-free library (`client.py`) and an OpenAI-compatible routing server (`serve`)
5. **Orchestrate** multiple models — `fanout` + `judge`
6. **Local brain** — `brain`: a tool-capable local model that delegates to the fleet (agentic loop)

## Install / dev loop

Installed as an **editable pipx** app, so edits under `mortise/` are live with no
reinstall:

```bash
pipx install --editable ~/projects/git/riggers-mortise
pipx inject riggers-mortise fastapi uvicorn      # for `serve`
```

- `mortise` is on PATH (`~/.local/bin/mortise`).
- To import modules in a REPL / run ad-hoc checks, use the **pipx venv's python**
  (base `python3`/`python` on styx lacks typer/fastapi):
  `/Users/nthmost/Library/Application Support/pipx/venvs/riggers-mortise/bin/python`
- Fast, deterministic test invocation (avoids waiting on unreachable LAN hosts):
  `mortise --hosts http://localhost:11434 -d known <cmd>`
- **zsh gotcha:** unquoted vars don't word-split — inline flags rather than
  `H="--hosts ..."; mortise $H`.
- No test suite yet. Verification has been manual against live Ollama on styx.

## Commands

| Command | What |
|---|---|
| `mortise` / `mortise scan` | fleet table (default) — warmth 🔥, SPEED, CONV 💬, oversized ⚠ |
| `mortise ask "..."` | one-shot; stateless unless `-r`/`-s`; stdin-friendly |
| `mortise chat` | REPL; suggest-and-confirm picker; live `[turn N · ~X tok]` counter |
| `mortise log [id|last]` | list / replay stored conversations |
| `mortise fanout "..."` | run one prompt across several rigs |
| `mortise judge "..."` | fanout then a capable rig picks the best |
| `mortise brain "..."` | local model orchestrates the fleet via tool-calling |
| `mortise serve` | OpenAI-compatible routing endpoint (needs `[serve]` extra) |

Common flags: `-d/--discovery known,routers,scan`, `--hosts`, `--routers`,
`--scan-subnet`, `-m/--model`, `-r/--resume`, `-s/--session`, `--to` (policies),
`--models`, `-n`, `--judge`.

## Architecture

```
cli.py         typer commands; thin — parses args, calls the rest
config.py      layered config: defaults < ~/.config/mortise/config.toml < MORTISE_* env < flags
rig.py         the Rig record (one model at one endpoint) + its computed fields
discovery/     known.py routers.py scan.py + __init__ orchestrator → list[Rig]
  __init__.py    runs modes concurrently, dedupes (identity.py), annotates tok_s + oversized
backends/      ollama.py (native /api/tags,/api/ps,/api/chat,/api/show, chat_tools)
               openai.py (/v1/models,/v1/chat/completions) — LiteLLM & OpenAI-compatible
identity.py    canonical host id; folds localhost + this box's own name → "@local"
select.py      balanced-score ranking (constants: WARM/SPEED/CAPABILITY weights, OVERSIZED_PENALTY)
resources.py   local RAM auto-detect + [resources] config; flags oversized models
stats.py       observed tok/s per (canonical-host, model) → ~/.local/state/mortise/throughput.json
history.py     per-model JSONL transcripts → ~/.local/state/mortise/sessions/
client.py      UI-FREE core: complete/stream, pick/order (policies), fanout, judge
session.py     terminal chat: one-shot + REPL, resume/sessions (wraps client + ui)
ui.py          rich rendering: fleet table, streaming, log viewer, brain trace
tools.py       brain tool registry (Tool = schema + async handler + Context)
brain.py       orchestrator loop: reason → tool_calls → run tools → feed back → answer
serve.py       FastAPI app: policy routing over the live fleet + failover (lazy-imports fastapi)
```

Data flow: `discover()` → `list[Rig]` (deduped, annotated) → `select`/`client.pick`
choose → `backends` stream → `session`/`serve`/`brain` consume.

## Key concepts

- **Rig** = one model at one endpoint. Fields: model, host, endpoint, backend
  (`ollama`|`openai`), size_b, size_bytes, quant, warm, latency_ms, tok_s,
  oversized, tools, source, api_key.
- **Discovery modes** (composable): `known` (probe host list), `routers` (LiteLLM
  `/v1/models`), `scan` (bounded TCP subnet sweep — opt-in; Ollama has no mDNS so
  it's a real port sweep, capped at 4096 hosts).
- **Routing policies** (client.pick/order, and the `serve` model field):
  `auto` (balanced rank), `fast` (tok/s), `capable` (biggest that fits),
  `cheap` (smallest), or an exact model name.
- **Balanced score** (select.py): `warm(2.0) + speed(1.5, unmeasured=0.5 neutral)
  + capability/size(1.0) − oversized(3.0)`. Tune the constants there.

## Design decisions (and why)

- **History keyed by model tag, not host** — a conversation is with the *model*,
  so you can resume on whichever host has it awake (failover is a feature). Host
  differences are a *ranking/display* concern, handled separately.
- **Named sessions** (`-s`) handle "multiple threads with one model" — that's an
  intent axis, not an infrastructure (host) axis.
- **Alias dedup** — `localhost` and the machine's own `.local` name resolve to
  different IPs but are the same daemon; identity.py folds anything pointing at
  this machine to `@local` so the fleet doesn't double-list.
- **Resource-aware ranking** — "a good rigger can't treat every vehicle the same
  just because it has the same mortises." Measured tok/s + a fit penalty so a
  70B isn't the silent default on a 24 GB laptop.
- **serve is live, not static** — the pitch vs the existing LiteLLM routers: it
  routes on what's actually awake and how fast it is now, no config to regen.
- **Brain tool-calling: native + fallback** — use Ollama's `tool_calls`, but parse
  a JSON-in-content fallback for models that fake it.
- **Warmth is observed, never created — except by `stoke`** — `select.rank`
  *prefers* warm rigs but discovery stays a read-only probe of the fleet's real
  state. **Stoking** (`client.stoke` / `mortise stoke`) is the one deliberate,
  opt-in way to keep a rig loaded: an empty Ollama generate with `keep_alive`
  (`-1` pins, seconds stays, `0` releases via `unstoke`). Named for the metaphor
  — tend the firebox so the engine never cold-starts. (Consumer: Saga
  `pick("fast")` + `stoke` its opener on service boot.)

## Verified facts / gotchas

- All local models on styx report `tools` in `/api/tags` `capabilities` (captured
  on `Rig.tools`).
- Proper `tool_calls`: **llama3.1:8b, qwen3:8b, mistral-small:24b**. **qwen2.5-coder:14b
  fakes it** (dumps the call into `content`) — the fallback parser in brain.py handles it.
- On styx, `localhost` and `styx.local` are the same Ollama daemon.
- Ollama stream's final message carries `eval_count`/`eval_duration` → exact tok/s.
- `mortise serve` needs `fastapi`+`uvicorn` (optional `[serve]` extra).

## State on disk

`~/.local/state/mortise/` (XDG; override base with `$XDG_STATE_HOME`):
- `sessions/*.jsonl` — conversation transcripts (`<ms>-<model>-<name>.jsonl`, meta on line 1)
- `throughput.json` — rolling mean tok/s per `host\x00model`

Config: `~/.config/mortise/config.toml` (see `config.example.toml`).

## Open questions

- **History identity: model tag vs digest** — undecided. Tag is "good enough" for
  now; digest (`/api/tags` content hash) would merge same-weights and separate
  tag-collisions, but orphans threads on re-pull.

## Next steps / roadmap

Rough priority — the registry is ready for the first two:

1. **Real brain tools** — `web_fetch`, `shell`, `read_file`. Append `Tool` entries
   in `tools.py`; the loop/parser don't change. This makes the brain a true agent.
2. **Brain memory** — persist brain sessions via `history.py` so it accumulates
   context across runs.
3. **`judge` synthesize-mode** — merge the best of all answers, not just pick one.
4. **`--json` output** for scan/ask so it's a clean shell backend.
5. **Anthropic `/v1/messages`** on `serve` so Claude Code itself can drive the fleet.
6. In-REPL `/model` switch mid-`chat`; system-prompt support.

**Done:**

- ✅ **Stoking** (opt-in warm-keeping) — `client.stoke(rig, ttl=None)` /
  `client.unstoke(rig)` and `mortise stoke <spec> [--ttl N | --off]`. Empty
  Ollama generate with `keep_alive`; no-op (`False`) for non-Ollama backends.
  Verified against a live daemon (finite-TTL expiry, indefinite pin, release).
  Driven by Saga (`~/projects/git/saga`), which imports mortise as a library and
  stokes its `fast` opener on service boot — see
  `saga/docs/saga-service-and-routing.md`. Possible follow-up: a config-driven
  auto-stoke list so `mortise serve` tends a set on start.

## Coding standards

Follow `~/projects/git/neon-nerdsnipe/CLAUDE.md`: tiny single-purpose functions
(~5–15 lines), type hints everywhere, docstrings, imports at top ordered
stdlib/third-party/local, minimal focused try/except, guard clauses over nesting.

## Repo / meta

- GitHub: `nthmost/riggers-mortise` (public). Commit small and focused; update
  README + this file alongside behavior changes.
- Version lives in `mortise/__init__.py` and `pyproject.toml` (keep in sync).
