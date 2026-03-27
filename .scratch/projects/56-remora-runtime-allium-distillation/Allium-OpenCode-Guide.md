# Allium with OpenCode: installation and usage guide

## Overview

This guide shows how to use the **Allium** language inside **OpenCode**.

The short version:

- Install the Allium skill with `npx skills add juxt/allium`.[^allium-install]
- Open your repo in OpenCode and run `/init` once to generate or update `AGENTS.md` for project instructions.[^opencode-init][^opencode-rules]
- Let OpenCode discover the Allium skill through its skill search paths, including Claude-compatible `.claude/skills/...` locations.[^opencode-skills][^opencode-claude-compat]
- Use normal prompts to ask OpenCode to create, refine, distill, or validate `.allium` specifications.
- Optionally install the `allium` CLI for validation, parsing, model extraction, and test planning.[^allium-tools]

---

## What Allium is

Allium is an LLM-native specification language for describing **what a system should do** without prescribing implementation details. The repo positions it as a behavioral language centered on entities, rules, transitions, surfaces, contracts, and invariants, and its built-in workflows cover:

- **elicit**: build a spec through structured conversation
- **distill**: extract a spec from an existing codebase
- **propagate**: generate tests from a spec
- **tend**: edit and grow specs
- **weed**: compare spec and implementation for drift[^allium-readme][^allium-skill]

If you are using OpenCode, the key thing to understand is that **Allium is delivered as skill files and documentation**, not as a separate compiler/runtime for the language itself.[^allium-readme]

---

## Important OpenCode-specific caveat

The Allium docs say that in **Claude Code** you can type `/allium` directly.[^allium-install]

For **OpenCode**, the model behavior is slightly different:

- OpenCode has its own built-in slash commands such as `/init`, `/help`, `/undo`, `/redo`, and `/share`.[^opencode-commands][^opencode-tui]
- OpenCode discovers reusable skills from `SKILL.md` files in locations such as:
  - `.opencode/skills/<name>/SKILL.md`
  - `~/.config/opencode/skills/<name>/SKILL.md`
  - `.claude/skills/<name>/SKILL.md`
  - `~/.claude/skills/<name>/SKILL.md`[^opencode-skills]
- OpenCode explicitly supports **Claude-compatible skill locations** as fallbacks.[^opencode-claude-compat]

So in OpenCode, the most reliable way to use Allium is:

1. install the skill,
2. let OpenCode discover it,
3. prompt OpenCode normally about `.allium` work,
4. optionally add your own `/allium` command as a convenience.

That means **you should not assume `/allium` is a built-in OpenCode command out of the box** unless you define it yourself.

---

## Prerequisites

Before using Allium in OpenCode, you should already have:

- OpenCode installed and configured with at least one model/provider
- a local project/repository open in OpenCode
- a terminal where `npx` is available for the skill install path shown by Allium[^allium-install]

Optional but recommended:

- Homebrew or Cargo if you want the standalone `allium` CLI[^allium-tools]

---

## Recommended setup path

### 1) Open your project in OpenCode

Start OpenCode in the project directory.

```bash
opencode
```

OpenCode’s TUI runs against the current working directory, and you can also start it for a specific directory.[^opencode-tui]

### 2) Initialize project rules with `/init`

Inside OpenCode, run:

```text
/init
```

OpenCode documents `/init` as the command that creates or updates `AGENTS.md`, and explains that it scans the project to generate project-aware instructions.[^opencode-tui][^opencode-rules]

Why this matters for Allium:

- `AGENTS.md` can tell OpenCode that your repo uses Allium specs
- you can record team conventions such as where `.allium` files live
- you can document whether the code or the spec is your current source of truth during migrations

A good `AGENTS.md` note might look like this:

```md
## Allium conventions

- We use `.allium` files for behavioral specifications.
- Prefer updating specs before changing implementation when requirements change.
- Use Allium for domain behavior, not storage or framework details.
- When editing `.allium`, validate with the Allium CLI if it is installed.
```

### 3) Install Allium

Use the install command published by the Allium docs:

```bash
npx skills add juxt/allium
```

That is the official install path Allium gives for Cursor, Windsurf, Copilot, Aider, Continue, and “40+ other tools.”[^allium-install]

### 4) Make sure OpenCode can discover the skill

OpenCode loads skills from `.opencode/skills/...`, `.claude/skills/...`, and related global locations.[^opencode-skills]

Because OpenCode also supports Claude-compatible skill directories, a skill installed into `.claude/skills/...` can still be usable from OpenCode unless Claude compatibility has been disabled.[^opencode-claude-compat]

If skill loading seems broken, check these first:

- `SKILL.md` must be uppercase and present in a matching skill folder name.[^opencode-skills]
- `name` and `description` must exist in the YAML frontmatter.[^opencode-skills]
- no permission rule in `opencode.json` is hiding the skill.[^opencode-skills]
- the environment variable `OPENCODE_DISABLE_CLAUDE_CODE_SKILLS=1` is **not** set if you are relying on `.claude/skills` fallback support.[^opencode-claude-compat]

### 5) Start using Allium in normal prompts

Once the skill is installed, the Allium docs say the LLM should load the skill when it encounters `.allium` files or when you mention Allium in conversation.[^allium-install]

In OpenCode, practical prompts look like this:

```text
Create a new Allium spec for subscription billing in this repo.
```

```text
Distill an Allium spec from the auth module under src/auth.
```

```text
Review this .allium file and refine the rules for cancellation and refunds.
```

```text
Compare the payment implementation to the Allium spec and point out drift.
```

```text
Generate the test obligations implied by this Allium spec.
```

These map cleanly onto the workflows documented by the Allium repo: elicit, distill, tend, weed, and propagate.[^allium-readme][^allium-skill]

---

## What a good OpenCode + Allium workflow looks like

### Workflow A: create a new specification from intent

Use this when the feature is new or the requirements are still fuzzy.

Prompt example:

```text
We are adding promo codes to subscriptions. Use Allium to elicit a spec from me before any code changes.
```

What should happen:

- OpenCode loads the Allium skill.
- The model asks structured questions.
- You converge on a `.allium` spec that captures behavior rather than API or DB details.[^allium-skill]

### Workflow B: distill a spec from an existing codebase

Use this when the code already exists and you want a behavioral model.

Prompt example:

```text
Distill an Allium spec from the order and refund logic under services/billing.
```

What to expect:

- OpenCode reads the codebase.
- It abstracts away ORM, routes, framework details, and storage choices.
- It produces entities, states, preconditions, and outcomes in Allium form.[^allium-distill]

### Workflow C: update an existing spec as requirements evolve

Prompt example:

```text
Update the Allium spec so enterprise customers can pause subscriptions for up to 90 days.
```

This is the “tend” shape of work: modifying `.allium` files while keeping the language rules and abstractions intact.[^allium-tend]

### Workflow D: check code/spec drift

Prompt example:

```text
Check whether the login code still matches the auth.allium spec.
```

This is the “weed” workflow: compare implementation and specification and classify divergences.[^allium-weed]

### Workflow E: derive tests from the specification

Prompt example:

```text
Use the Allium spec to generate test obligations for order cancellation.
```

This is the “propagate” workflow, which the repo describes as generating tests from the spec, including surface tests, state tests, invariant tests, and transition-oriented tests.[^allium-propagate]

---

## Optional but recommended: install the Allium CLI

The separate `juxt/allium-tools` repo provides the parser, CLI, LSP server, and editor integrations.[^allium-tools]

Official install methods listed in that repo:

### Homebrew

```bash
brew tap juxt/allium && brew install allium
```

### Cargo

```bash
cargo install allium-cli
```

The repo also says prebuilt Linux and macOS binaries are available on its releases page.[^allium-tools]

### Most useful CLI commands

```bash
allium check
allium parse
allium plan
allium model
```

According to the tools repo:

- `allium check` validates specifications and reports diagnostics
- `allium parse` outputs the syntax tree
- `allium plan` derives test obligations from a spec
- `allium model` extracts the domain model as structured data[^allium-tools]

### Why the CLI is worth it in OpenCode

Without the CLI, the model can still work from the language reference. With the CLI installed, you get a much tighter loop for:

- syntax/structure validation
- parser-level feedback
- model extraction for tooling
- test planning from the spec[^allium-readme][^allium-tools]

---

## Suggested project layout

A simple, practical structure:

```text
your-repo/
├─ AGENTS.md
├─ specs/
│  ├─ auth.allium
│  ├─ billing.allium
│  └─ subscriptions.allium
├─ src/
├─ tests/
└─ .opencode/
   ├─ commands/
   └─ skills/
```

Notes:

- `AGENTS.md` is OpenCode’s project instruction file.[^opencode-rules]
- `.opencode/commands/` is where OpenCode custom slash commands live.[^opencode-commands]
- `.opencode/skills/` is an OpenCode-native skill location.[^opencode-skills]
- `.claude/skills/` is also supported for compatibility.[^opencode-skills][^opencode-claude-compat]

---

## Add your own `/allium` command in OpenCode

If you want a Claude-like shortcut, create a custom OpenCode command.

OpenCode documents custom commands as Markdown files in `.opencode/commands/` or `~/.config/opencode/commands/`.[^opencode-commands]

Create:

```text
.opencode/commands/allium.md
```

Example:

```md
---
description: Start an Allium workflow
---

Work in Allium mode for this repository.

If there are existing `.allium` files, inspect them first.
If there are no `.allium` files, determine whether to:
1. elicit a new spec from requirements,
2. distill a spec from the existing codebase, or
3. compare spec and implementation for drift.

Prefer behavioral specifications over implementation details.
If the Allium CLI is available, validate any edited `.allium` files.
```

Then invoke it in OpenCode as:

```text
/allium
```

This is not built into OpenCode by default; it is simply a user-defined command layered on top of OpenCode’s command system.[^opencode-commands]

---

## First-run prompts that work well

### Create a new spec

```text
Use Allium to create a behavioral spec for team invitations and role assignment.
```

### Distill from code

```text
Distill an Allium spec from src/payments and src/invoices.
Focus on observable behavior and constraints.
```

### Tighten a vague requirement

```text
Use Allium elicitation to refine this requirement: users can cancel subscriptions.
Surface edge cases, timing rules, refunds, and audit requirements.
```

### Update a spec before implementation

```text
Update specs/subscriptions.allium so annual plans can be upgraded mid-cycle with prorated billing.
```

### Check for drift

```text
Weed the billing spec against the current implementation and report divergences.
```

### Generate tests

```text
Generate the tests implied by specs/auth.allium.
If the CLI is installed, use allium plan first.
```

---

## Minimal `.allium` example

This example is adapted to match the style used in the Allium docs.

```allium
-- allium: 3

entity Subscription {
    status: active | paused | cancelled
    paused_until: Timestamp?
}

rule PauseSubscription {
    when: PauseSubscription(subscription, until)
    requires: subscription.status = active
    ensures:
        subscription.status = paused
        subscription.paused_until = until
}
```

This is the level of abstraction Allium is aiming for: behavior and conditions, not controller methods, SQL, HTTP routes, or ORM syntax.[^allium-skill][^allium-distill]

---

## Troubleshooting

### The skill does not seem to load

Check:

1. the install completed successfully
2. the skill exists in one of OpenCode’s supported paths
3. `SKILL.md` is uppercase
4. the skill frontmatter has `name` and `description`
5. no permission rule hides it
6. Claude compatibility has not been disabled if you are relying on `.claude/skills`[^opencode-skills][^opencode-claude-compat]

### `/allium` does nothing in OpenCode

That usually means you have not defined a custom command. In OpenCode, slash commands are documented as built-in commands plus user-defined command files in `.opencode/commands/`.[^opencode-commands][^opencode-tui]

### I installed Allium but validation is weak

Install the separate CLI from `juxt/allium-tools` and run `allium check` after edits.[^allium-tools]

### The model is writing implementation detail into the spec

Add guidance to `AGENTS.md`, for example:

```md
When writing `.allium` files:
- do not mention REST endpoints
- do not mention ORM classes
- do not mention storage engines
- capture observable behavior, timing, transitions, and constraints
```

That lines up with Allium’s documented philosophy of modeling behavior, not implementation.[^allium-readme][^allium-skill]

---

## Best practices

- Keep specs close to the domain, not the framework.
- Update the spec before or alongside major behavioral changes.
- Use `/init` and `AGENTS.md` to make the Allium workflow explicit for the whole repo.[^opencode-rules]
- Install the Allium CLI if you will edit specs regularly.[^allium-tools]
- Create an OpenCode custom `/allium` command if your team wants a repeatable entrypoint.[^opencode-commands]
- Use distillation for legacy code, elicitation for new features, weed for drift checks, and propagate for tests.[^allium-readme][^allium-distill][^allium-weed][^allium-propagate]

---

## Bottom line

The cleanest way to use Allium with OpenCode today is:

1. run `/init` in OpenCode,
2. install Allium with `npx skills add juxt/allium`,
3. let OpenCode discover the skill through `.opencode/skills` or `.claude/skills`,
4. prompt normally for spec work,
5. optionally add your own `/allium` command,
6. install `allium` CLI if you want strong validation and test planning.

That setup gives you a practical OpenCode workflow for writing, refining, validating, and using behavioral specs in `.allium` files.

---

## Sources

[^allium-install]: Allium installation page: <https://juxt.github.io/allium/installation>
[^allium-readme]: Allium repository README: <https://github.com/juxt/allium/blob/main/README.md>
[^allium-skill]: Allium `SKILL.md`: <https://github.com/juxt/allium/blob/main/SKILL.md>
[^allium-distill]: Allium distillation guide: <https://github.com/juxt/allium/blob/main/skills/distill/SKILL.md>
[^allium-tend]: Allium tend agent guide: <https://github.com/juxt/allium/blob/main/.claude/agents/tend.md>
[^allium-weed]: Allium weed agent guide: <https://github.com/juxt/allium/blob/main/.claude/agents/weed.md>
[^allium-propagate]: Allium propagation guide: <https://github.com/juxt/allium/blob/main/skills/propagate/SKILL.md>
[^allium-tools]: Allium Tools README: <https://github.com/juxt/allium-tools>
[^opencode-rules]: OpenCode Rules docs: <https://opencode.ai/docs/rules>
[^opencode-tui]: OpenCode TUI docs: <https://opencode.ai/docs/tui/>
[^opencode-commands]: OpenCode Commands docs: <https://opencode.ai/docs/commands/>
[^opencode-skills]: OpenCode Agent Skills docs: <https://opencode.ai/docs/skills>
[^opencode-claude-compat]: OpenCode Claude compatibility section: <https://opencode.ai/docs/rules>
