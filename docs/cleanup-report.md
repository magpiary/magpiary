# Magpiary cleanup report

30 October 2026. Scope: `docs/codex-cleanup-prompt.md`, with no intended change to application behaviour.

## Starting point and baseline

- The supplied worktree was clean on `cleanup/codex` at `ba44437`, exactly the latest local `main`. Fetching `origin/main` confirmed that its `5009e95` tip was already an ancestor of local `main`; no merge or reset was needed.
- Read `CLAUDE.md` and `docs/specs.md` before editing production code. Kept their local-first, privacy, unattended-processing and plain-Python/plain-JavaScript constraints.
- First command for validation: `uv run pytest -q` — **717 passed in 42.74 s**.
- Initial `uvx ruff check src tests`: **325 findings**. Initial Vulture scan at 80% confidence found one unused argument: `expand._site_of`'s `fallback`.
- Ruff **0.17.3** and Vulture **2.16** ran through `uvx`; no project dependencies, dependency groups or lockfile were added or changed.

## Changes, one commit per theme

| Commit | Theme | Validation after committing |
|---|---|---|
| `0e624c5` | Characterize chat persistence, media range edge cases and current post markup before refactoring. | Ruff checks passed; **728 tests passed**. |
| `ea30d19` | Remove verified unused imports, local assignments, constants, the retired inline Ask renderer, and an unused private helper argument. Preserve calls whose return values were unused. | Ruff checks passed; **728 tests passed**. |
| `5a576eb` | Remove the uncalled dot-timeline renderer, its JavaScript clustering/progress code and its exclusive CSS. | Ruff checks passed; **728 tests passed**. |
| `4efc3d4` | Extract chat persistence into `store_chat.ChatStore`, inherited by `Store`. | Ruff checks passed; **728 tests passed**. |
| `7b8fb6d` | Extract archived-media, thumbnail and profile-photo responses into `hub_media.MediaPages`, inherited by `Hub`. | Ruff checks passed; **732 tests passed**. |
| `87f7f87` | Preserve optional preview/search fallbacks while adding redacted DEBUG diagnostics and preview callback type hints. | Ruff checks passed; **736 tests passed in 37.81 s**. |

The final documentation theme updates stale source descriptions and adds this report. It is checked again after committing with the same Ruff and pytest commands.

### Dead code and assets

Reference searches used `rg` across production code, tests and documentation, alongside Ruff and Vulture. Removed 15 unused imports and four unused local assignments, preserving necessary function calls. Also removed obsolete `HEAD`, `CAN`, `CONFIDENT`, `FALLBACK_AFTER` and `SHOWN` constants and the unused `ask_inline` method. `_site_of` no longer accepts an ignored private argument.

The old `_timeline` method had no callers. Characterization tests first established that both full-page and fragment post responses already render timestamped key points without its `.tl`/`.tdot` markup. Removed that method, `clusterDots`, its inactive time-update listener and total-duration calculation, exclusive timeline styles and obsolete onboarding selector alternatives. Kept `.ttip` and its shared rules: Settings still uses those tooltips. Current key-point, transcript and carousel seeking code remains in place.

### Storage and media seams

`Store` keeps connection ownership, schema initialization, migrations, clock and locking. `ChatStore` groups only chat history, sessions, usage and notes, using the same connection and transaction boundaries. A small `_message` helper replaces duplicated JSON metadata decoding. Existing chat-history, archive, session-list and title limits have names, with the same values. The stale claim that saved chats can never resume was corrected.

`Hub` keeps routing, local-access checks and the lock gate. `MediaPages` owns file resolution, ranges, thumbnails, profile photos and media URLs. Cache durations and thumbnail width have names, with the same values. Characterization tests were run before extraction for symlinks leaving an archive, archives outside the configured library, bypassing thumbnails on range requests, and missing/present profile photos with their exact headers.

Added missing `-> None` constructor annotations on the changed `Store` and `Hub` boundaries. Every extracted chat/media method retains its return annotation; preview fetch and host-validation callbacks now have explicit types.

### Optional failures and comments

Preview page/image failures, preview icon failures and unavailable search vocabulary still produce the same fallback results, including for unexpected callback exceptions. They now emit a DEBUG record containing only a fixed operation label and exception class. No exception text, URL, question, database content or traceback is included. Tests characterize the fallbacks before editing, then verify the diagnostic and absence of private details.

Updated module descriptions for the composed hub, chat storage and Nest delivery table. Removed the obsolete old-address comment and descriptions of abandoned search/design trials; corrected the pause-control and link-status comments. Searched production code for TODO/FIXME markers, breakpoints and console debug output; no unfinished debug cleanup was identified. Intentional CLI output and receiver operational messages remain.

## Verification and limits

- **19 added test cases**, bringing the suite from **717 to 736**. They use temporary databases/config/library folders and injected network callbacks. Existing test fixtures isolate Magpiary data and refuse real relay connections.
- `uvx ruff check --select F401,F841,F821 src tests` passes across production code and tests after every commit. This checks unused imports, unused local assignments and undefined names.
- Full Ruff checks pass on both new modules and the characterization test file. The broader `uvx ruff check src tests` scan falls from **325 to 303 findings**; it is **not globally clean**. Remaining findings include import ordering, older style conventions, pytest fixture-name redefinitions and deliberately broad fallback exceptions. No project-wide suppressions or lint-policy changes were added.
- `uvx vulture src/magpiary --min-confidence 80` is clean. Lower-confidence results were reviewed against references; see the exclusions below.
- Ruff formatted the new modules/tests and selected changed ranges in existing Python files. Existing files were not reformatted wholesale, preserving surrounding style and limiting unrelated diff churn.
- `node --check src/magpiary/static/hub.js`, Python compilation and `git diff --check` pass. The existing suite also checks page-script syntax.
- Compared the ASTs of `SCHEMA`, `HUB_SCHEMA`, `BOARD_SCHEMA`, `ASK_SCHEMA`, `SEARCH_SCHEMA`, `SEARCH_COLUMNS` and `MIGRATIONS` with `ba44437`: all are identical. CLI commands, dependency manifests and lockfile are unchanged.
- Commit secret checks passed. No service was installed, restarted or updated; no real library, real keys, live AI requests or public relay writes were used for validation. No push or history rewrite was performed.
- HTTP response and source/syntax checks establish regression coverage for this cleanup. This was not a fresh visual audit, interactive browser walkthrough, phone test or live-provider test.

## Deliberately left alone

- **Large JavaScript closure.** Removed verified dead code, but kept the live Ask/player/search/navigation code together. It shares selection, navigation, DOM helpers, callbacks and state. Splitting it safely needs explicit dependencies and browser interaction coverage; a line-count-driven file split would hide those dependencies.
- **Remaining large Store/Hub methods.** Queue receipt, short-link merging, schema migration, search and route ordering remain intact. Further extraction would touch transaction, migration or dispatch semantics outside the two characterized seams.
- **Other exception boundaries.** Worker loops, relay sync, doctor checks and optional provider/cache paths have different recovery contracts. Did not narrow their exception types or expose raw errors merely to satisfy a linter.
- **Low-confidence Vulture candidates.** HTTP handlers, HTML parser callbacks, `row_factory`, connection hooks and server settings are used by frameworks. `boards.make_invite` and several Store methods are called from tests or remain existing public helpers. Retained descriptive/public constants such as `DIMENSIONS` and `PING_PATH` rather than guessing about downstream use.
- **Historical material.** Kept spikes, prototype assets, vendored libraries, historical handovers and the append-oriented spec intact. They are evidence of earlier decisions, not the current implementation guide.
- **Public contracts.** Did not rename CLI commands, database columns, settings keys, routes or current public Store methods. No new runtime layer or dependency was introduced.

## Ranked ideas for later

1. **Characterize live browser interactions, then split `hub.js`.** Cover Ask send/stop/minimize/history, navigation/back, player/carousel seeking and selection first. Extract one feature at a time with explicit state and callback inputs, keeping the no-build setup.
2. **Characterize database upgrades and rollback paths before more Store extraction.** Use fixture databases from supported schema versions and injected transaction failures. Then consider schema initialization and board storage as separate seams.
3. **Agree a repository-wide Ruff policy and clear its baseline in dedicated commits.** Handle fixture imports/re-exports deliberately; keep mechanical import/style work separate from changes to recovery or resource management. Avoid blanket unsafe fixes.
4. **Extend redacted diagnostics one subsystem at a time.** Specify what failures must recover, retry or surface before changing worker/relay/provider boundaries. Never log fetched text, keys or raw remote errors.
5. **Expand public boundary types incrementally.** Start with provider/network callbacks and small return-value records, retaining the project's current naming and dependency footprint. Avoid a repository-wide type rewrite mixed into behavioural work.
