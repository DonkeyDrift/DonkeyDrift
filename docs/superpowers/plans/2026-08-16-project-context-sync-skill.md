# project-context-sync Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a user-scope skill `project-context-sync` (single `SKILL.md`) that scans a project's real state and maintains its `AGENTS.md` / `CLAUDE.md`, fixing outdated or incorrect content.

**Architecture:** One self-contained markdown skill file with no scripts or dependencies. The body prescribes a 6-phase procedure (collect facts → compare → detect → fix → template → verify) plus a fallback path and a mandatory report step.

**Tech Stack:** Markdown, Kimi Code `SKILL.md` frontmatter format (`name` + `description`).

**Reference spec:** `docs/superpowers/specs/2026-08-16-project-context-sync-skill-design.md`

**Note on location:** The skill file is written OUTSIDE the git working directory, to the user-scope skills dir `C:/Users/cross/.agents/skills/project-context-sync/SKILL.md`, per the user's explicit "user scope / cross-project" choice. No git commits are performed (the skill lives outside the repo; the spec doc was explicitly left uncommitted).

---

## File Structure

- **Create:** `C:/Users/cross/.agents/skills/project-context-sync/SKILL.md` — the complete skill (frontmatter, principles, 6-phase workflow, templates, fallback, report).
- **Read (reference, do not modify):** existing skill frontmatter examples at `C:/Users/cross/.agents/skills/brainstorming/SKILL.md` and `C:/Users/cross/.kimi-code/plugins/managed/superpowers/skills/writing-skills/SKILL.md` to confirm format.
- **Modify (only during smoke test, and only per the skill's own rules):** `C:/Dev/DDC/DonkeyDrift/AGENTS.md`, `C:/Dev/DDC/DonkeyDrift/CLAUDE.md`.

---

## Task 1: Create skill directory and write the frontmatter + intro sections

**Files:**
- Create: `C:/Users/cross/.agents/skills/project-context-sync/SKILL.md`

- [ ] **Step 1: Create the directory**

Run:
```bash
mkdir -p "/c/Users/cross/.agents/skills/project-context-sync"
```
Expected: exit code 0, directory exists.

- [ ] **Step 2: Write the frontmatter + title + Invocation + Principles**

Write the following to `C:/Users/cross/.agents/skills/project-context-sync/SKILL.md` (this is the first chunk; later tasks append to the same file):

```markdown
---
name: project-context-sync
description: "Use when creating or updating AGENTS.md/CLAUDE.md, syncing agent context files with the actual project state, or after significant project changes (new/renamed commands, moved files, changed build/test steps)."
---

# Project Context Sync

Maintain the repository's `AGENTS.md` and `CLAUDE.md` so they always match the project's real state. Scan the project, compare against the existing files, fix outdated or incorrect content, and report what changed.

## Invocation

Run this skill when:
- `AGENTS.md` or `CLAUDE.md` is missing, stale, or needs a full audit.
- The user asks to "sync context", "update AGENTS.md/CLAUDE.md", "init the project", or similar.
- Significant changes landed (new commands, moved files, changed build/test steps).

## Principles

- Facts come from the project, never from memory. Every claim must trace to a file, command definition, or manifest entry you actually read.
- Minimal diff. Do not rewrite wording or formatting that is still accurate; fix only what is wrong or missing.
- Keep `AGENTS.md` as the single source of truth; `CLAUDE.md` is a thin wrapper pointing at it (plus Claude-specific notes only if truly needed).
- Confirm before changing anything that affects how the project is built/tested/run.
```

- [ ] **Step 3: Verify the frontmatter format**

Run:
```bash
head -5 "/c/Users/cross/.agents/skills/project-context-sync/SKILL.md"
```
Expected: exactly the `---`, `name:`, `description:`, `---` block shown above.

---

## Task 2: Write Phase 1 (fact collection) and Phase 2 (comparison)

**Files:**
- Modify: `C:/Users/cross/.agents/skills/project-context-sync/SKILL.md` (append)

- [ ] **Step 1: Append Phase 1 and Phase 2**

Append the following to the same `SKILL.md`:

```markdown
## Workflow

### Phase 1 — Collect facts (full scan)

Read these sources in order. Record findings as you go.

1. Project root:
   - Confirm the working directory.
   - List the top-level layout (depth 1-2).
   - Locate existing `AGENTS.md`, `CLAUDE.md`, `README*`, and any nested `AGENTS.md`.
2. Commands and entry points:
   - `Makefile` — every target and the command it runs.
   - `setup.cfg` / `pyproject.toml` — `console_scripts`, `[options.scripts]`, `extras_require`, `install_requires`, `python_requires`.
   - `package.json` — `scripts`, `dependencies`, `devDependencies`.
   - `.github/workflows/*.yml` — build/test/lint steps.
   - CLI subcommands — argparse `prog=` values, or the command dispatch table (for example `execute_from_command_line`'s command dict).
   - `Dockerfile` / `docker-compose*.yml` — key entry points.
3. Layout and responsibilities:
   - Identify each top-level package/directory; read its `__init__.py` docstring or a nested `README` to state its purpose.
4. Dependencies and versions:
   - `install_requires`, `extras_require`, `requirements*.txt`, `package.json` deps, `python_requires`.
5. Conventions:
   - Import style, naming, test command, language/style rules, and any nested `AGENTS.md` guidance.
6. Recent changes:
   - `git log --oneline -20`
   - `git status --short`
   - `git diff --stat` (against a recent tag/base, or `HEAD~N`)
   - `CHANGELOG.md` top entries.

### Phase 2 — Compare with existing files

- If `AGENTS.md` does not exist: generate it from the template in Phase 5.
- If `CLAUDE.md` does not exist: generate the thin wrapper.
- If both exist: walk each section of `AGENTS.md` and compare every claim against the Phase 1 facts.
```

- [ ] **Step 2: Verify the section landed**

Run:
```bash
grep -n "Phase 1" "/c/Users/cross/.agents/skills/project-context-sync/SKILL.md" && grep -n "Phase 2" "/c/Users/cross/.agents/skills/project-context-sync/SKILL.md"
```
Expected: both `grep` commands print matching line numbers.

---

## Task 3: Write Phase 3 (detection) and Phase 4 (fix)

**Files:**
- Modify: `C:/Users/cross/.agents/skills/project-context-sync/SKILL.md` (append)

- [ ] **Step 1: Append Phase 3 and Phase 4**

Append the following:

```markdown
### Phase 3 — Detect stale / incorrect content

Flag content when any of these is true:

1. A documented command is not defined in `Makefile`, `setup.cfg`, `pyproject.toml`, `package.json`, or the CLI dispatch table.
2. A referenced path or directory does not exist in the current layout.
3. A documented dependency or version contradicts the manifest.
4. A description contradicts the actual code behavior (read the module to confirm).
5. `AGENTS.md` and `CLAUDE.md` contradict each other.
6. Content references a deleted, renamed, or deprecated module, command, or flag.

For each flag, record: file, section, current (wrong) text, and the correct replacement.

### Phase 4 — Fix

- Default: edit directly to correct commands, paths, dependencies, and descriptions; add missing sections; remove dead content.
- Key changes require confirmation first: anything that changes how the project is built/tested/run — commands, paths, entry points, dependency versions. Before editing, list "old -> new" and wait for the user to approve. (When the user has already pre-authorized fixes, apply them and clearly report each change.)
- Keep diffs minimal; do not reword accurate prose.
- If nested `AGENTS.md` files exist, check whether they are still accurate and update them under the same rules.
- If the two files duplicate facts, consolidate into `AGENTS.md` and make `CLAUDE.md` reference it.
```

- [ ] **Step 2: Verify the section landed**

Run:
```bash
grep -n "Phase 3" "/c/Users/cross/.agents/skills/project-context-sync/SKILL.md" && grep -n "Phase 4" "/c/Users/cross/.agents/skills/project-context-sync/SKILL.md"
```
Expected: both print matching line numbers.

---

## Task 4: Write Phase 5 (templates), Phase 6 (verify), Fallback, and Report

**Files:**
- Modify: `C:/Users/cross/.agents/skills/project-context-sync/SKILL.md` (append)

- [ ] **Step 1: Append Phase 5, Phase 6, Fallback, and Report**

Append the following:

```markdown
### Phase 5 — Templates

`AGENTS.md` (authoritative source of truth):

```markdown
# Project Name

<one-paragraph overview>

## Build / Test / Run

<only commands verified to exist, with exact syntax>

## Repository Layout

<top-level dirs with one-line responsibilities>

## Conventions

<import style, naming, language, style, nested AGENTS.md pointers>

## Dependencies & Versions

<manifest-backed list and version constraints>

## Notes

<gotchas, known issues, safety notes>
```

`CLAUDE.md` (thin wrapper):

```markdown
# Project Name

See [AGENTS.md](AGENTS.md) for the authoritative project context: build/test/run commands, layout, conventions, dependencies, and notes.

<Claude-specific additions only if genuinely needed; otherwise nothing>
```

### Phase 6 — Verify (mandatory before finishing)

- Every documented command can be traced to its definition.
- Every documented path exists (`Glob` or `ls`).
- Dependencies/versions match the manifest.
- The two files do not contradict each other.
- No placeholders, empty sections, or `TBD`.
- When safe and fast, actually run one documented test/build command and confirm it works.

### Fallback

For non-Python/Node projects (or when manifests cannot be parsed): still scan the directory layout, git history, and README; document only what you can confirm; mark unverifiable items as "unconfirmed" rather than inventing commands or dependencies.

## Report

At the end, summarize to the user:
- files created or updated
- every stale/incorrect item found and how it was fixed
- any key changes that were held for confirmation
- verification results
```

- [ ] **Step 2: Verify the file is complete and well-formed**

Run:
```bash
wc -l "/c/Users/cross/.agents/skills/project-context-sync/SKILL.md" && grep -n "^### Phase" "/c/Users/cross/.agents/skills/project-context-sync/SKILL.md"
```
Expected: `wc -l` reports a non-zero line count; `grep` lists `Phase 1` through `Phase 6` exactly once each.

---

## Task 5: Self-review the SKILL.md against the spec

**Files:**
- Read: `C:/Users/cross/.agents/skills/project-context-sync/SKILL.md`
- Read: `docs/superpowers/specs/2026-08-16-project-context-sync-skill-design.md`

- [ ] **Step 1: Read both files**

Read the full `SKILL.md` and the spec.

- [ ] **Step 2: Check spec coverage**

Confirm each spec requirement has a corresponding section:
- 6-phase workflow → present (`Phase 1`-`Phase 6`).
- Detection signals (6 items) → present in `Phase 3`.
- Key-change confirmation rule → present in `Phase 4`.
- `AGENTS.md` authoritative + `CLAUDE.md` thin wrapper → present in `Phase 5`.
- Verification checklist → present in `Phase 6`.
- Fallback for unparseable manifests → present in `Fallback`.
- Report step → present in `Report`.

- [ ] **Step 3: Placeholder scan**

Run:
```bash
grep -nE "TBD|TODO|implement later|fill in|<appropriate|<add|similar to" "/c/Users/cross/.agents/skills/project-context-sync/SKILL.md" || true
```
Expected: only the intentional template placeholders `<one-paragraph overview>`, `<top-level dirs...>`, `<import style...>`, `<manifest-backed...>`, `<gotchas...>`, and `<Claude-specific additions...>` appear — these are deliberate template slots, not plan gaps. No `TBD`/`TODO`/`implement later`.

- [ ] **Step 4: Consistency check**

Confirm the description text, the 6 phase names, and the `old -> new` wording are used consistently throughout (no renamed section titles).

---

## Task 6: Smoke-test the skill on DonkeyDrift

**Files:**
- Create (if missing): `C:/Dev/DDC/DonkeyDrift/AGENTS.md`
- Create (if missing): `C:/Dev/DDC/DonkeyDrift/CLAUDE.md`
- Read: `C:/Dev/DDC/DonkeyDrift/README.md`, `C:/Dev/DDC/DonkeyDrift/Makefile`, `C:/Dev/DDC/DonkeyDrift/setup.cfg`, `C:/Dev/DDC/DonkeyDrift/donkeycar/management/base.py` (command dispatch table)

- [ ] **Step 1: Invoke the skill on the current project**

Invoke `project-context-sync` and follow its workflow against `C:/Dev/DDC/DonkeyDrift`. Collect facts from `Makefile`, `setup.cfg`, the CLI dispatch table in `donkeycar/management/base.py` (`createcar`, `findcar`, `calibrate`, `tubplot`, `tubhist`, `makemovie`, `createjs`, `cnnactivations`, `update`, `train`, `models`, `ui`, `tui`, `web`, `drive`, `installweb`), `package.json`, and `git log`.

- [ ] **Step 2: Generate `AGENTS.md`**

Expected content includes at least these verified commands (all traceable to the code):
- `pip install -e ".[pc,dev]"` (README local dev)
- `pytest` (Makefile `tests` target)
- `donkey installweb --path ./web_ui` (CLI `installweb`)
- `donkey web` / `donkey drive` / `donkey tui` / `donkey createcar --path ~/mycar --template complete` (CLI dispatch table)

- [ ] **Step 3: Generate `CLAUDE.md` as a thin wrapper**

Expected: it points to `AGENTS.md` and does not duplicate the command list.

- [ ] **Step 4: Run the skill's Phase 6 verification**

Confirm every command in the generated `AGENTS.md` traces to a real definition, every path exists, and the two files do not contradict each other.

- [ ] **Step 5: Report**

Summarize the created files, the facts captured, and the verification results to the user. Do NOT run `git commit`.

---

## Self-Review (completed by plan author)

- **Spec coverage:** All 7 spec sections (goal, decisions, metadata, 6-phase workflow, fallback, boundaries, skill verification) map to Tasks 1-6. The "skill's own verification" from spec section 7 is covered by Task 6.
- **Placeholder scan:** Only intentional template slots remain in the SKILL.md content; no `TBD`/`TODO`.
- **Type consistency:** Phase names (`Phase 1`-`Phase 6`) and the `old -> new` confirmation wording are consistent across tasks.
