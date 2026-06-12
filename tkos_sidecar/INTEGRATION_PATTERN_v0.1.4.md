# Belief Stack Integration Pattern v0.1.4

**Date:** 2026-06-06 (v0.1 → v0.1.1 → v0.1.2 → v0.1.3 → v0.1.4, this version)
**Status:** v0.1.4 working draft — harness-focused, not product copy. Iterates as integrations land.

**v0.1.3 → v0.1.4 patch (one addition in this doc):**
- **Action-policy discipline.** New §7 documents a recommended harness pattern: map belief categories to permitted action shapes before planning. Implied by the current architecture, not enforced at the sidecar layer. Older §7–§9 renumbered to §8–§10.

**v0.1.2 → v0.1.3 patch (one fix in this doc):**
- **Fix 5 — Codex `apply_patch` Move grammar correction.** §3.5 — Codex's actual patch tool emits `*** Update File: old/path` followed by `*** Move to: new/path` for renames, not the single-line `*** Move File: from -> to` form v0.1.2 assumed. Regex updated to capture `*** Move to:` as a separate header; the destination path is collected from it while the source path is collected from the preceding `*** Update File:`.

**v0.1.1 → v0.1.2 patch (one fix in this doc):**
- **Fix 5 — Codex file edit / path enrichment.** §3.5 adapter rules previously read paths only from `arguments.path`, `arguments.paths`, or `arguments.file_path`. Codex's `apply_patch` calls carry paths inside the patch text (after `*** Begin Patch` / `*** Add File:` / `*** Update File:` / `*** Delete File:` markers); without parsing patch headers, `paths=[]`, which silently disables `fix_attempted`, `validation_complete weakened`, and `report_ready` rules. v0.1.2 §3.5 documents the patch-header extraction. Also: `tool_result` normalization now explicitly inherits `tool_name` and `command` from its parent `tool_call` (the canonical contract requires both for tool results per RULES_SPEC §4.1).
**Audience:** anyone wiring Belief Stack (via the TKOS sidecar or any compatible implementation) into an agent harness (Claude Code, Codex, custom).

**v0.1 → v0.1.1 amendments:**
- **Finding 5** (Codex source mapping): new §3.5 documents adapter normalization rules for Codex rollout JSONL — how to derive `tool_name`, `command`, `exit_code`, `stderr_first_line`, `paths` from the actual rollout records (which carry `function_call` envelopes, not normalized fields).
- **Finding 11** (scope contradiction): §7.4 reclassifies the Codex v0.2 reference integration as **capture-only**. Live overlay injection at planning moments is not in scope for v0.2 (Codex offers no documented hook).

This document is **not** about why Belief Stack matters. It is about how to slot it into a real agent's context-construction pipeline. For positioning copy, see [`topicspace.ai/research/belief-stack`](https://topicspace.ai/research/belief-stack).

---

## §1 Where Belief Stack sits in the token-cost toolkit

The current industry token-saving toolkit has four widely-discussed families. Belief Stack is a fifth. It does **not** compete with the four.

| Family | What it solves | Belief Stack relationship |
|---|---|---|
| **Prompt caching** (K/V, prefix, semantic) | Stable-prefix cost — system prompts, tool schemas, examples charged repeatedly | Complementary. Cache the stable prefix; project Belief Stack into the variable part. |
| **Lazy-load dormant tokens** (Anthropic Tool Search, layered memory) | Bloated tool/capability lists in context | Peer abstraction at the same layer of the stack. Both keep a compact handle in context with rich content fetched elsewhere; just different content types — capabilities vs world-state. |
| **Routing / cheap models** (RouteLLM, cascades, subagents) | Paying frontier prices for easy tasks | Orthogonal. Belief Stack lifts any model. Pairing with cheaper models is defensible (substrate compensates for reconstruction the cheaper model can't do internally). |
| **Compaction** (autonomous compression, summary buffers) | History bloat once it has already happened | **Upstream alternative, not competitor.** Compaction says: *history got too big; summarize it.* Belief Stack says: *don't make history carry state in the first place.* |

The right mental model for an implementer: **five complementary techniques attacking five different cost axes.** Pick the ones that fit your harness and compose them.

---

## §2 The layer-cake context shape

The recommended prompt/context construction for a harness using Belief Stack:

```
┌─────────────────────────────────────────────────────────┐
│ [ stable system prompt          ]  ← prompt caching     │
│ [ tool definitions / tool search]  ← lazy-loading       │
│ [ layered memory index          ]  ← project memory     │
│ [ BELIEF STACK PROJECTION       ]  ← current state      │
│ [ K=3 recent turns              ]  ← execution detail   │
│ [ current user message          ]                       │
└─────────────────────────────────────────────────────────┘
```

Per-turn changeability (top is most stable, bottom is most variable):

| Layer | Changes per turn? | Cacheable? |
|---|---|---|
| Stable system prompt | No | Yes (frontier providers' prompt-cache API) |
| Tool definitions / search index | No | Yes |
| Layered memory index | Rarely (once per session) | Yes within a session |
| **Belief Stack projection** | **Yes** | No (changes by design); kept small to bound cost |
| K=3 recent turns | Yes | No (changes by design) |
| Current user message | Yes | No |

The Belief Stack projection is the new layer this document introduces. Everything above and below it is what most production agent harnesses already do.

---

## §3 Sidecar integration architecture

Belief Stack runs as a sidecar. It is not part of the agent harness's main process. The interface is four operations.

### §3.1 Diagram

```
                    agent harness
                       │   ▲
                events │   │ projection
                       ▼   │
                 ┌─────────────────┐
                 │  TKOS sidecar    │
                 │  (Belief Stack)  │
                 └─────────────────┘
                          │
                  audit ▼ │
                 ┌─────────────────┐
                 │  human inspection │
                 │  (CLI, future UI) │
                 └─────────────────┘
```

### §3.2 Operations

| Operation | Direction | Purpose |
|---|---|---|
| `observe(event)` | harness → sidecar | Stream session events to the substrate. One event per call. |
| `overlay(session_id, budget_tokens, ...)` | harness → sidecar → harness | Get a sparse, ranked, budget-bounded projection of current belief state for injection into the planner's context. |
| `state(session_id, turn=None)` | human / audit → sidecar | Return the full belief state with warrants and lifecycle — for human inspection, not for the agent. |
| `risk(session_id, action)` | harness → sidecar → harness | Optional advisory check: any blockers for a proposed action? Information only; sidecar never blocks the agent. |

### §3.3 The two consumer surfaces

- **Agent surface:** `overlay()` returns bare `belief_type :: claim` per active belief, ranked and budget-bounded (per v0.4a/v0.4c1 results: ~241 mean tokens). This is what goes in context.
- **Human surface:** `state()` returns the same beliefs with full warrant chains, lifecycle audit trail, and authority signals. This is what a developer/auditor reads via CLI or trace viewer.

Same substrate. Different projections. The substrate-vs-projection split is the architectural commitment.

### §3.5 Adapter normalization rules — Codex (v0.1.1, finding 5 fix)

The Codex rollout JSONL does not carry pre-normalized fields. The adapter is responsible for translating Codex's `function_call` / `function_call_output` envelopes into the canonical event contract that `RULES_SPEC_v0.2.md` §1 expects.

**Source → mapped event_type:**

| Codex source line | Mapped event_type |
|---|---|
| `response_item(payload.type=function_call, name=exec_command)` | `tool_call` |
| `response_item(payload.type=function_call, name≠exec_command)` | `tool_call` |
| `response_item(payload.type=function_call_output)` | `tool_result` |
| `response_item(payload.type=message, role=assistant)` | `assistant_message` |
| `response_item(payload.type=reasoning)` | `assistant_reasoning` |
| `event_msg(payload.type=user_message)` | `user_message` |
| `event_msg(payload.type=task_started)` | `task_start` |
| `event_msg(payload.type=task_complete)` | `task_completion` |

**Field derivation:**

For `tool_call` from `function_call` with `name == "exec_command"`:
- `tool_name` = `arguments.cmd.split()[0]` (the first shell token after parsing arguments JSON)
- `command` = `arguments.cmd` (the full command string)
- `paths` = parsed from `arguments.cmd` per the path-extraction heuristic below
- `call_id` = `payload.call_id`

For `tool_call` from `function_call` with `name != "exec_command"`:
- `tool_name` = `payload.name` (the function name)
- `command` = empty string
- `paths` = parsed from `arguments.path` / `arguments.paths` / `arguments.file_path` if present; **for `name == "apply_patch"`, paths are additionally extracted from the patch text in `arguments.input` per the patch-header rule below (v0.1.2 fix 5)**
- `call_id` = `payload.call_id`

For `tool_result` from `function_call_output` (v0.1.2 — fix 5: inherits tool_name + command):
- `call_id` = `payload.call_id`
- `parent_event_id` = the `source_event_id` of the `function_call` with matching `call_id` (look up in `events`)
- **`tool_name` = inherited from the parent `tool_call`'s `tool_name`** (RULES_SPEC §4.1 requires this for `tool_result`)
- **`command` = inherited from the parent `tool_call`'s `command`** (RULES_SPEC §4.1 requires this for shell `tool_result`)
- `exit_code` = parse from `payload.output` (regex `Process exited with code (\d+)`; default 0 if not present — Codex convention)
- `stderr_first_line` = parse from `payload.output` per the heuristic below
- `output` = `payload.output` (the full output string)
- `paths` = inherit from the parent `tool_call`

For `assistant_message`, `assistant_reasoning`, `user_message`: `content` = the appropriate text field (`content`, `summary`, `message`).

For `task_start`: `task_name` = derived from `turn_id` and `started_at` (e.g., `f"task-{turn_id[:8]}-{started_at}"`).

For `task_completion`: `final_status` = `"ok"` if `last_agent_message` present, else `"incomplete"`.

**Exit code extraction:**

```python
import re
EXIT_RE = re.compile(r"Process exited with code (\d+)", re.MULTILINE)

def exit_code_from_output(output: str) -> int:
    m = EXIT_RE.search(output)
    return int(m.group(1)) if m else 0  # absence = success per Codex convention
```

**Stderr first line extraction (heuristic):**

```python
def stderr_first_line(output: str) -> str | None:
    for line in output.splitlines():
        s = line.strip()
        if not s or s.startswith("Output:") or s.startswith("Chunk ID") or s.startswith("Process exited"):
            continue
        if any(marker in s.lower() for marker in ("error:", "traceback", "exception:", "stderr:")):
            return s
    return None
```

**Path extraction (heuristic, v0.1.2):**

For shell commands extracted from `arguments.cmd`:
1. Recognized file-touching tools: read (`nl`, `cat`, `head`, `tail`, `less`, `grep`); write (`cp`, `mv`, `rm`, `ln`, `chmod`, `chown`, `touch`, `mkdir`, `rmdir`); modify (`git`, `sed -i`, `awk -i inplace`).
2. Extract path-shaped tokens (containing `/` or starting with `.`) from the command, skipping the tool name.
3. Filter out flag-shaped tokens (`--foo`, `-f`).

**Patch-header path extraction (v0.1.2 — fix 5):**

For `function_call` with `name == "apply_patch"`, the patch content lives in `arguments.input` (a multi-line string). Paths must be extracted from patch header lines that follow this format:

```
*** Begin Patch
*** Update File: path/to/file.py
@@ ... @@
... patch hunks ...
*** End Patch
```

Recognized header markers (locked, v0.1.3):
- `*** Add File: <path>` — file being created
- `*** Update File: <path>` — file being modified (may be followed by `*** Move to:` for rename)
- `*** Delete File: <path>` — file being removed
- `*** Move to: <path>` — destination path of a rename; the source is the preceding `*** Update File:` (Codex's actual patch grammar; v0.1.2 incorrectly assumed `*** Move File: from -> to`)

```python
import re
PATCH_FILE_HEADER_RE = re.compile(
    r"^\*\*\* (Add|Update|Delete) File:\s*(\S+)",
    re.MULTILINE
)
PATCH_MOVE_TO_RE = re.compile(
    r"^\*\*\* Move to:\s*(\S+)",
    re.MULTILINE
)

def extract_paths_from_patch(patch_text: str) -> list[str]:
    paths: list[str] = []
    for m in PATCH_FILE_HEADER_RE.finditer(patch_text):
        paths.append(m.group(2))  # Add / Update / Delete target
    for m in PATCH_MOVE_TO_RE.finditer(patch_text):
        paths.append(m.group(1))  # Move destination — source already collected via Update File
    return paths
```

Without this rule, `apply_patch` calls produce `paths=[]`, and the rules that depend on path overlap — `fix_attempted` (mints on edits with a failure context), `validation_complete_weakened_by_edit` (weakens completed validation when paths in scope change), `report_ready` (mints on report path writes) — silently do not fire.

Path extraction is intentionally crude for v0.1.2. Precision is not load-bearing for the v0.2 acceptance tests; conservative path matching (shared prefix) is acceptable for the rules that depend on path overlap.

---

## §4 Pull strategies

How often does the harness call `overlay()`? Three viable patterns, in priority order.

### §4.1 Per-plan (recommended default)

Call `overlay()` immediately before each planning step. Highest precision: the projection reflects every event up to the moment of the decision.

- **When to use:** the harness can intercept the "about to plan" moment cleanly.
- **Cost:** one sidecar call per planning step; with v0.4c1 budgets (~241 tokens) the per-call ingest cost is small.
- **Trade-off:** none for correctness; adds a single sidecar round-trip to the planning latency budget.

### §4.2 On state-change signal

Call `overlay()` when the sidecar emits a state-change webhook (a belief was minted, refreshed, contradicted, or retired). The harness caches the most recent overlay and reuses it until the next signal.

- **When to use:** the harness has a long-running session loop and wants to minimize round-trips.
- **Cost:** fewer sidecar calls; requires a webhook channel (HTTP callback, file watcher, or similar).
- **Trade-off:** the cached overlay may be stale between signals; requires the harness to trust the signal.

### §4.3 TTL refresh

Call `overlay()` every N seconds or every M turns, whichever comes first.

- **When to use:** the harness cannot hook into planning moments and cannot accept webhooks.
- **Cost:** lower than per-plan if N/M is generous; higher than state-change if traffic is bursty.
- **Trade-off:** stale projections between refreshes — a belief contradicted at turn T may not appear in the projection until turn T+M.

**Recommendation:** default to per-plan. Fall back to TTL only if per-plan integration is impossible.

---

## §5 Placement strategies

Where in the prompt does the overlay land?

| Placement | Mechanism | Trade-off |
|---|---|---|
| **Tool result / observation (LOCKED default)** | Inject as the result of a virtual tool call named e.g. `get_current_state()` | Treated by the model as an observation, not an instruction. No authority confusion. |
| User-message inline tag | Wrap in a tag like `<current_state>...</current_state>` inside the user message | Mixes user intent with system observation; some models privilege earlier system content over later user content. |
| System prefix | Concatenate to the system prompt | Authority confusion: the system prompt says *how to behave*; the projection says *what current state is*. These are different categories; mixing them muddles the model's frame. |

**The default placement is tool-result observation.** Other placements are not forbidden but require evidence to choose. The reason for the default:

- System prompt = how to behave (authority).
- Belief Stack projection = what current state is (observation).

Don't confuse the two. The tool-result framing keeps the categories clean: the agent has a tool that returns current state, and the result is treated as ground truth observation, not as an instruction.

---

## §6 Plan/execute split

The v0.3 / v0.4a / v0.4c1 experiments measured at **planning resolution** — single-next-action decisions. Execution-time may not need the overlay at all.

A natural two-mode harness:

```
plan(belief_overlay)  → returns a next action
execute(action, scratchpad) → carries out the action with K=3 raw turns for execution detail
```

The overlay is what `plan()` consumes. The scratchpad is what `execute()` consumes. They are not the same surface.

**Practical implication for integration:**
- Inject the overlay only at planning moments. Don't include it in execution-time tool calls.
- The K=3 scratchpad (recent raw turns) lives separately and persists across both modes — but it's small and bounded.
- This is the architecture v0.3 measured and v0.4c1 replicated across four models.

If the harness doesn't separate plan from execute (single-call architecture), inject the overlay once per turn and accept the small cost of including it in execution-time calls. The data does not say this is harmful.

---

## §7 Action-policy discipline

The Belief Stack sidecar provides maintained state; it does not decide what action the planner should take. Harnesses SHOULD map belief categories to permitted action shapes before planning.

The purpose is to prevent planners from treating all active beliefs as equally actionable. A "validation pending" belief and a "validation complete" belief are both active beliefs in the substrate — but they call for opposite action shapes. The substrate proposes state; the action-policy layer constrains how that state may be used.

### §7.1 Recommended belief-category → action-shape mapping

| Belief category | Examples (RULES_SPEC v0.3.2 types) | Recommended action shape |
|---|---|---|
| **Blocker** | `validation_pending`, `user_approval_pending`, `pipeline_failed`, `pipeline_running` | pause / ask / wait / repair |
| **Permission** | `validation_complete`, `report_ready` (when delivery is the next step) | proceed / close / deploy |
| **Diagnosis** | suspected root cause (rule-engine output beyond v0.3.2; sketched in `failure_signature_active`) | investigate / patch candidate |
| **Weak hypothesis** | low-confidence cause or option (not yet a substrate type — would carry warrant strength signal) | explore / gather evidence |
| **Stale belief** | substrate beliefs in lifecycle state `weakened` (per RULES_SPEC §3.3) | refresh / do not rely |
| **Option** | `workaround_possible`, alternative paths flagged but not committed | candidate action, not truth |

The mapping is intentionally coarse-grained. It operates on belief *categories*, not individual substrate types. The same category covers multiple RULES_SPEC primitives because the action shape is what the planner cares about, not the substrate-level distinction.

### §7.2 What the mapping prevents

Without an action-policy layer, common failure modes:

- The planner sees an active belief and treats every belief as a fact to act on. A `validation_pending` belief becomes "validation has happened" rather than "validation is in flight, do not deploy."
- The planner converts a *strongest-profile* belief into a *primary-anchor* action without considering the appropriate action shape. (This was the Belmont 2026 failure mode dogfooded in the program: all four models had the right substrate signal, all four mapped it to the wrong action shape.)
- The planner treats a weakened or stale belief as equally usable as a fresh one, because the substrate does not enforce ordering or freshness on the consumer side.

The mapping is the harness's discipline to honor what the substrate already records.

### §7.3 What this section does NOT commit to

- **No sidecar enforcement.** The TKOS sidecar's `risk()` operation (sketched in `TKOS_SIDECAR_SKETCH_v0.1.md` §2.4) is advisory only. It returns information; it does not block the action. The action-policy layer is harness-side, not sidecar-side. Enforcement at the sidecar layer is a candidate v0.5+ direction; not in scope here.
- **No locked taxonomy.** The six categories above are a starting point. Harnesses may extend them; future RULES_SPEC versions may add categories. The mapping is a discipline pattern, not a fixed schema.
- **No measurement of efficacy.** The recommendation is implied by the architecture, not proven empirically. Whether typed-action prompting actually improves planner outcomes is a separable experiment (see Belmont 2026 retrospective in project memory).

### §7.4 The two-line summary

> The sidecar proposes state.
> The action-policy layer constrains how that state may be used.

This is the architectural commitment §7 documents. Implementations honor it; the sidecar does not enforce it.

---

## §8 Minimal viable integration

The smallest set of changes to turn an existing agent harness into a Belief-Stack-using harness:

### §8.1 Pre-integration assumptions

- The harness already has a notion of "session" (each user-task interaction).
- The harness emits identifiable events: user messages, assistant messages, tool calls, tool results, file edits.
- The harness can intercept context construction before sending to the model.

### §8.2 What to add

1. **Sidecar:** run `tkos serve` in a separate process. Local HTTP. SQLite-backed. No auth required for v0.1.
2. **Event emitter:** in the harness's main event loop, POST each event to the sidecar as it happens. Don't wait for batches.
3. **Overlay fetch:** at planning time, GET `/overlay?session_id={id}&budget=300` from the sidecar.
4. **Context injection:** inject the returned overlay text as a tool result for a virtual tool call named `get_current_state`.

That's the minimum. Four touchpoints. No streaming, no native integration, no harness rewrite.

### §8.3 What does NOT need to change

- The harness's existing prompt caching strategy.
- The harness's existing tool definitions or tool-search integration.
- The harness's existing memory layering.
- The harness's existing routing or subagent setup.
- The model the harness uses for planning.

Belief Stack adds a layer; it doesn't replace what's already there.

### §8.4 Reference integrations (v0.1.1 — finding 11 fix)

- **Codex via TKOS write-path sidecar (v0.2.1) — capture-only:** the v0.2.1 reference integration. See [`TKOS_WRITE_PATH_SCOPE_v0.2.md`](./TKOS_WRITE_PATH_SCOPE_v0.2.md). The Codex trace adapter reads `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl` and POSTs events to the sidecar. The overlay is *available* via `overlay()` for inspection and audit, but Codex offers no documented hook for context injection in v0.2, so **automatic injection is not in scope**. The overlay-in-context value proposition is reserved for a future integration milestone — likely a Claude Code adapter that can intercept planning steps, or a custom-built harness with explicit hooks.
- **Claude Code (planned, future):** would use the same sidecar with a different trace adapter reading Claude Code's session logs, plus a planning-step hook for overlay injection. Architecturally identical to the Codex adapter on the capture side; adds live injection on the read side.
- **Custom harnesses:** any harness that controls its own context construction can wire the overlay in directly as a tool result per §5.

---

## §9 Non-goals (what Belief Stack integration is NOT)

To prevent scope drift:

- **Not a replacement for prompt caching.** Use prompt caching alongside.
- **Not a replacement for lazy-loaded tools.** Use Tool Search or equivalent alongside.
- **Not a replacement for model routing.** Use routing alongside; Belief Stack helps the routed-to model plan correctly.
- **Not a replacement for aggressive compaction.** It is the upstream alternative to compaction-as-state-management; if history still bloats for other reasons (long raw responses, voluminous tool outputs), compact separately.
- **Not an LLM-driven extractor.** v0.1 uses deterministic rules. LLM-driven extraction is a future research direction.
- **Not a memory store.** Beliefs are session-local in v0.1. Cross-session reasoning is a different system.
- **Not a governance / safety / blocking layer.** `risk()` is advisory only. The sidecar never reaches into the host or stops actions.
- **Not a runtime intervention system.** The sidecar observes; the harness decides.

---

## §10 What's missing from v0.1 of this spec

Honest gaps to be filled in v0.2:

- **Overlay format normalization.** Today the overlay is a string. A structured format (JSON with type/claim/authority fields) may be preferable for harnesses that want to render or parse it.
- **Streaming overlay updates.** Some harnesses may want a streaming connection so the overlay can update mid-call. Not in v0.1.
- **Multi-session overlays.** "Show me all currently-pending approvals across all my sessions" is a cross-session query. Not in v0.1.
- **Cross-implementation compatibility tests.** This spec describes the integration pattern; a conformance test suite for "is this a real Belief Stack?" is future work.

---

*This integration pattern reflects what the v0.3 / v0.4a / v0.4c1 experimental program measured: a sparse maintained-state projection injected at planning resolution, against a substrate that preserves warrants and lifecycle for separate human inspection. The architecture composes with the rest of the agent-cost-management toolkit. The locked default placement (tool-result observation) and pull strategy (per-plan) are the minimum-friction integration. Both are revisable when evidence justifies.*
