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
```

The scan view:

```
                       nearby rigs
 #  MODEL               HOST          SIZE  QUANT   WARM  LAT    SRC    API
 0  qwen2.5-coder:14b   loki.local    14B   Q4_K_M  🔥    12ms   known  ollama
 1  mistral-small:24b   styx.local    24B   Q4_K_M  ·     31ms   known  ollama
 2  loki/qwen3-coder    spartacus     —     —       ·     8ms    routers openai
```

`WARM` = currently loaded in memory (no cold-start). The default pick (`ask`
with no `-m`, or the top row in `chat`) prefers warm, then larger, then faster.

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

## Backends

- **Ollama** (native `/api/tags`, `/api/ps`, `/api/chat`) — direct to each host,
  with warmth detection and parameter-size reporting.
- **OpenAI-compatible** (`/v1/models`, `/v1/chat/completions`) — LiteLLM routers,
  and anything else that speaks the OpenAI wire format.

## Layout

```
mortise/
  cli.py                       # typer CLI: scan (default) / ask / chat
  config.py                    # layered config resolver
  rig.py                       # the Rig record
  select.py                    # ranking + lookup
  session.py                   # one-shot + REPL
  ui.py                        # fleet table + streaming output
  discovery/{known,routers,scan}.py   # each returns list[Rig]
  backends/{ollama,openai}.py         # discovery + streaming chat per protocol
```

## Status

Working skeleton: discovery (all three modes), the scan fleet-view, one-shot
`ask`, and an interactive `chat` REPL with suggest-and-confirm selection.
