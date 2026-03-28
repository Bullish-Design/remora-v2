# Centralized GitHub Pages Documentation System

## Concept Document

**Status:** Draft v2
**Last Updated:** 2026-03-28
**Related:** [REPO_DOCS_STRATEGY.md](./REPO_DOCS_STRATEGY.md), [GITHUB_PAGES_INTEGRATION.md](./GITHUB_PAGES_INTEGRATION.md)

---

## 1. Problem Statement

We need a way to add professional documentation websites to **existing repositories** with minimal friction. The solution must:

- Work on **existing** projects (not just new repos)
- Be **reusable** across dozens/hundreds of repositories
- Be **maintainable** (updates in one place, deployed everywhere)
- Be **automated** (CI/CD setup included)
- Require **minimal project knowledge** (generic install process)

### Why This Needs to Be Simple

The per-repo footprint is small — 3 new files (`zensical.toml`, `docs/index.md`, `.github/workflows/docs.yml`) plus a `.gitignore` entry. The real challenge is keeping the build/deploy logic centralized so that when Zensical evolves (currently v0.0.29, expect breaking changes), we fix it once, not N times.

---

## 2. Architecture: Reusable Workflow + Copier Templates

Two mechanisms, each solving a different part of the problem:

| Concern | Mechanism | Update story |
|---------|-----------|--------------|
| **Build & deploy logic** | GitHub Actions reusable workflow | Automatic — consumer repos call it by ref, update the ref to get changes |
| **Per-repo config files** | Copier template | On-demand — `copier update` pulls new template changes, shows diffs |

### 2.1 How It Fits Together

```
┌─────────────────────────────────────────────────────────┐
│              Central Repo: docs-system                  │
│                                                         │
│  .github/workflows/                                     │
│    └── build-docs.yml        ← Reusable workflow        │
│                                (Zensical install,       │
│                                 build, deploy)          │
│                                                         │
│  template/                   ← Copier template          │
│    ├── zensical.toml.jinja                              │
│    ├── docs/                                            │
│    │   └── index.md.jinja                               │
│    └── .github/workflows/                               │
│        └── docs.yml.jinja    (calls the reusable wf)    │
│                                                         │
│  copier.yml                  ← Copier config            │
│  README.md                                              │
└──────────────────────┬──────────────────────────────────┘
                       │
          copier copy / copier update
                       │
                       ▼
┌─────────────────────────────────────────────────────────┐
│              Consumer Repo: my-project                  │
│                                                         │
│  .github/workflows/                                     │
│    └── docs.yml              ← 5-line wrapper that      │
│                                calls reusable workflow   │
│  zensical.toml               ← Per-repo config          │
│  docs/                                                  │
│    ├── index.md              ← Landing page              │
│    └── *.md                  ← Existing project docs    │
│  .copier-answers.yml         ← Tracks template version  │
│  .gitignore                  ← site/ appended           │
└─────────────────────────────────────────────────────────┘
```

### 2.2 Why This Split

**Reusable workflow** handles everything that should be identical across repos: installing Python, installing Zensical, running the build, uploading the artifact, deploying to Pages. When Zensical releases a breaking change or we want to add caching, we update one file.

**Copier** handles everything that varies per repo: site name, description, URL, navigation. It also gives us `copier update` for free — when we change the template (add a new config option, change the default theme features), each repo can pull the update and review the diff.

---

## 3. Central Repo: `docs-system`

### 3.1 Repository Structure

```
docs-system/
├── .github/
│   └── workflows/
│       └── build-docs.yml     # Reusable workflow (the core value)
├── template/
│   ├── zensical.toml.jinja
│   ├── .github/
│   │   └── workflows/
│   │       └── docs.yml.jinja
│   ├── docs/
│   │   └── index.md.jinja
│   └── .gitignore.jinja       # Appends site/ entry
├── copier.yml                 # Questions, defaults, config
└── README.md
```

### 3.2 Reusable Workflow: `build-docs.yml`

This is a [reusable workflow](https://docs.github.com/en/actions/sharing-automations/reusing-workflows) that consumer repos call. It encapsulates all build/deploy logic.

```yaml
# .github/workflows/build-docs.yml
name: Build and Deploy Docs

on:
  workflow_call:
    inputs:
      python-version:
        type: string
        default: '3.x'
      zensical-version:
        type: string
        default: ''           # Empty = latest
      site-dir:
        type: string
        default: 'site'

permissions:
  contents: read
  pages: write
  id-token: write

concurrency:
  group: "pages"
  cancel-in-progress: false

jobs:
  deploy:
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}
    runs-on: ubuntu-latest
    steps:
      - name: Setup Pages
        uses: actions/configure-pages@v5

      - name: Checkout
        uses: actions/checkout@v5

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: ${{ inputs.python-version }}

      - name: Install Zensical
        run: |
          if [ -n "${{ inputs.zensical-version }}" ]; then
            pip install "zensical==${{ inputs.zensical-version }}"
          else
            pip install zensical
          fi

      - name: Build Documentation
        run: zensical build --clean

      - name: Upload artifact
        uses: actions/upload-pages-artifact@v4
        with:
          path: ./${{ inputs.site-dir }}

      - name: Deploy to GitHub Pages
        id: deployment
        uses: actions/deploy-pages@v4
```

**Key design choices:**

- `workflow_call` makes it callable from other repos
- Inputs have sensible defaults — most repos pass nothing
- `zensical-version` input lets repos pin if needed during breaking changes
- Permissions are declared here, not in consumer workflows

### 3.3 Copier Configuration: `copier.yml`

```yaml
# copier.yml
_min_copier_version: "9.0.0"
_subdirectory: template

# Questions asked during `copier copy`
site_name:
  type: str
  help: "Site name (appears in header and title)"
  default: "{{ repo_name | replace('-', ' ') | title }}"

site_description:
  type: str
  help: "One-line description of the project"
  default: ""

repo_owner:
  type: str
  help: "GitHub org or username"

repo_name:
  type: str
  help: "Repository name"

default_branch:
  type: str
  help: "Default branch"
  default: "main"

copyright_holder:
  type: str
  help: "Copyright holder name"
  default: "{{ repo_owner | replace('-', ' ') | title }}"

docs_system_ref:
  type: str
  help: "docs-system version to pin (tag, branch, or SHA)"
  default: "v1"
```

Copier auto-detects answers from `.copier-answers.yml` on subsequent runs, so `copier update` is non-interactive.

### 3.4 Templates

#### `template/zensical.toml.jinja`

```toml
[project]
site_name = "{{ site_name }}"
site_url = "https://{{ repo_owner }}.github.io/{{ repo_name }}/"
site_description = "{{ site_description }}"
repo_url = "https://github.com/{{ repo_owner }}/{{ repo_name }}"
repo_name = "{{ repo_owner }}/{{ repo_name }}"
edit_uri = "edit/{{ default_branch }}/docs/"
copyright = "Copyright &copy; {% now 'utc', '%Y' %} {{ copyright_holder }}"

nav = [
  { "Home" = "index.md" },
]

[project.theme]
features = [
  "navigation.instant",
  "navigation.instant.prefetch",
  "navigation.tracking",
  "navigation.sections",
  "navigation.path",
  "navigation.top",
  "navigation.footer",
  "navigation.indexes",
  "content.code.copy",
  "content.code.annotate",
  "content.action.edit",
  "content.action.view",
  "search.highlight",
  "toc.follow",
]

[[project.theme.palette]]
media = "(prefers-color-scheme: light)"
scheme = "default"
toggle = { icon = "lucide/moon", name = "Switch to dark mode" }

[[project.theme.palette]]
media = "(prefers-color-scheme: dark)"
scheme = "slate"
toggle = { icon = "lucide/sun", name = "Switch to light mode" }

[project.theme.icon]
repo = "fontawesome/brands/github"
edit = "material/pencil"
view = "material/eye"
```

#### `template/.github/workflows/docs.yml.jinja`

This is what lands in each consumer repo — a thin wrapper:

```yaml
name: Documentation

on:
  push:
    branches:
      - {{ default_branch }}
  workflow_dispatch:

jobs:
  docs:
    uses: {{ repo_owner }}/docs-system/.github/workflows/build-docs.yml@{{ docs_system_ref }}
```

That's it. All build logic lives in the reusable workflow.

#### `template/docs/index.md.jinja`

```markdown
# {{ site_name }}

{{ site_description }}

## Getting Started

Add your documentation to the `docs/` folder as Markdown files.

## Quick Links

- [GitHub Repository](https://github.com/{{ repo_owner }}/{{ repo_name }})
```

#### `template/.gitignore.jinja`

```
# Zensical build output
site/
```

Copier merges this with the existing `.gitignore` if one exists (via `_tasks` or Copier's append strategy).

---

## 4. Consumer Repo Usage

### 4.1 First-Time Setup

```bash
# In any existing repo:
copier copy gh:bullish-design/docs-system .

# Answer the prompts (or accept defaults):
#   site_name: Remora
#   site_description: Reactive agent substrate
#   repo_owner: bullish-design
#   repo_name: remora-v2
#   default_branch: main
#   copyright_holder: Bullish Design
#   docs_system_ref: v1
```

This creates:
- `zensical.toml`
- `.github/workflows/docs.yml`
- `docs/index.md`
- `.copier-answers.yml`
- Appends `site/` to `.gitignore`

Then:
1. Go to GitHub repo **Settings > Pages > Source > GitHub Actions**
2. Commit and push
3. Site deploys to `https://<owner>.github.io/<repo>/`

### 4.2 Updating When Templates Change

```bash
copier update
```

Copier compares your current files against the latest template, shows diffs, and lets you accept or reject each change. Your customizations to `zensical.toml` (nav, description, etc.) are preserved because Copier tracks answers in `.copier-answers.yml`.

### 4.3 Updating the Build Pipeline

To pick up a new reusable workflow version, update the ref in `.github/workflows/docs.yml`:

```yaml
# Change @v1 to @v2, or pin to a specific SHA
uses: bullish-design/docs-system/.github/workflows/build-docs.yml@v2
```

Or use `copier update` if the template itself has bumped the default ref.

### 4.4 What Lands in Each Repo

| File | Size | Changes often? |
|------|------|---------------|
| `.github/workflows/docs.yml` | ~10 lines | Rarely (ref bumps only) |
| `zensical.toml` | ~40 lines | Sometimes (nav, metadata) |
| `docs/index.md` | ~10 lines | Once (then user-maintained) |
| `.copier-answers.yml` | ~10 lines | On `copier update` |
| `.gitignore` addition | 1 line | Never |

---

## 5. Handling Edge Cases

### Existing `docs/` directory

Copier only writes `docs/index.md`. Existing markdown files are untouched. If `docs/index.md` already exists, Copier shows a conflict and lets the user choose.

### Custom navigation

The template generates a minimal `nav` with just `"Home"`. Users edit `zensical.toml` directly to add their docs to the nav — this is a per-repo concern, not a template concern.

For repos that want zero-config nav, delete the `nav` key entirely and Zensical auto-infers navigation from the file tree.

### Private repos

The `docs-system` repo must be accessible to consumer repos for the reusable workflow to work. Options:
- **Public repo** (recommended) — templates and workflow contain no secrets
- **Same org, internal visibility** — works for GitHub Enterprise
- **Private + PAT** — possible but adds friction; avoid if possible

### GitHub Pages activation

Not automated. The success message after `copier copy` reminds the user to enable Pages via Settings. Automating this via `gh api` is a possible future enhancement but not worth the complexity now.

---

## 6. Implementation Plan

### Phase 1: Reusable Workflow

1. Create `docs-system` repo
2. Write `build-docs.yml` reusable workflow
3. Test by calling it from one existing repo with a manually-created wrapper workflow
4. Verify end-to-end: push triggers build, site deploys

**Validates:** The core pipeline works before we add any templating.

### Phase 2: Copier Template

1. Create `copier.yml` with questions
2. Create Jinja templates for `zensical.toml`, `docs.yml`, `index.md`, `.gitignore`
3. Run `copier copy` on 2-3 existing repos
4. Verify generated files are correct and site builds

**Validates:** Template produces correct output for different repos.

### Phase 3: Versioning & Tags

1. Tag `docs-system` repo as `v1`
2. Set up major version tags (`v1` always points to latest `v1.x.x`)
3. Test `copier update` after making a template change
4. Document the update workflow in README

**Validates:** The update story works for both the workflow and the templates.

### Phase 4: Adoption

1. Roll out to existing repos
2. Document in `docs-system` README
3. Iterate based on real usage

---

## 7. Design Principles

**Centralize the moving parts.** Zensical is young and will change. The reusable workflow is the single point where we absorb those changes. Consumer repos are insulated.

**Use existing tools.** Copier handles templating, placeholder substitution, conflict resolution, and updates. We don't write any of that ourselves.

**Minimize per-repo footprint.** A consumer repo adds ~70 lines across 4 files. The workflow wrapper is 10 lines. Most of the content is in `zensical.toml`, which the user owns and edits.

**Fail visibly.** If the reusable workflow breaks, every consumer repo's CI fails and points to the same workflow file. Easy to diagnose, fix once.

---

## 8. Comparison to Previous Approach

| Aspect | v1 (Custom install scripts) | v2 (Reusable workflow + Copier) |
|--------|---------------------------|-------------------------------|
| Install mechanism | Custom Python/Bash scripts | `copier copy` (existing tool) |
| Build logic location | Copied into every repo | Centralized reusable workflow |
| Update story | Custom `--update` flag | `copier update` (built-in) |
| Workflow updates | Re-run installer or manual | Change ref or `copier update` |
| Dependencies to write | ~200 lines of install scripts | 0 lines of custom code |
| Zensical breakage | Fix N repos | Fix 1 workflow |

---

## 9. Open Questions

### Q1: Should consumer workflows pin `@v1` or `@main`?

**`@v1` (recommended):** Stable, opt-in updates. We maintain a `v1` tag that tracks the latest `v1.x.x`. Breaking changes go to `v2`.

**`@main`:** Always latest. Riskier but zero-friction updates. Acceptable for a single-owner org where you control both sides.

### Q2: Should we use Copier's `_tasks` to auto-enable GitHub Pages?

Copier supports post-copy tasks. We could run `gh api` to enable Pages automatically. However, this requires `gh` to be installed and authenticated. Recommendation: skip for now, revisit if the manual step proves to be a real friction point.

---

## 10. Next Steps

1. **Create `docs-system` repo** on GitHub
2. **Write the reusable workflow** and test it manually
3. **Set up the Copier template** and test `copier copy`
4. **Install on remora-v2** as the first real consumer
5. **Tag v1** and document

---

**Document History:**

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-03-28 | — | Initial concept (custom install scripts) |
| 2.0 | 2026-03-28 | — | Rewrite: reusable workflow + Copier |
