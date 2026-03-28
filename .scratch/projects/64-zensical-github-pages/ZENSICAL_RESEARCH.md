# Zensical Research Analysis

## Table of Contents

1. [What Is Zensical](#1-what-is-zensical)
2. [Technical Foundation](#2-technical-foundation)
3. [Installation & Prerequisites](#3-installation--prerequisites)
4. [Project Structure](#4-project-structure)
5. [Configuration Format](#5-configuration-format)
6. [Key Features](#6-key-features)
7. [Theming & Customization](#7-theming--customization)
8. [Navigation System](#8-navigation-system)
9. [Markdown Capabilities](#9-markdown-capabilities)
10. [Development Workflow](#10-development-workflow)
11. [Comparison to MkDocs Material](#11-comparison-to-mkdocs-material)
12. [Current Limitations](#12-current-limitations)

---

## 1. What Is Zensical

Zensical is a modern static site generator built by the creators of **Material for MkDocs** (squidfunk). It takes Markdown files and produces a professional, searchable, responsive documentation website. It was announced in November 2025 and is under active development (v0.0.29 as of March 24, 2026).

Key positioning:
- Spiritual successor to Material for MkDocs, rewritten from scratch.
- Designed to overcome MkDocs' technical limitations.
- "Batteries included" — ships with a polished default theme, search, dark/light mode, 60+ languages.
- MIT licensed.

Repository: https://github.com/zensical/zensical (3.9k stars, 94 forks)

## 2. Technical Foundation

- **Language**: Rust (83.9%) + Python (15.5%)
- **Template engine**: MiniJinja (Rust-based, Jinja-inspired)
- **Distributed as**: Python package (`pip install zensical`)
- **Config format**: TOML (`zensical.toml`)
- **Output**: Static HTML/CSS/JS in a `site/` directory

The Rust core provides fast builds; the Python layer handles the package distribution and plugin ecosystem.

## 3. Installation & Prerequisites

**Prerequisites**: Python 3.x + pip (or uv)

**Method 1 — pip (recommended)**:
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install zensical
```

**Method 2 — uv**:
```bash
uv init
uv add --dev zensical
uv run zensical
```

**Method 3 — Docker**: Official image on Docker Hub.

## 4. Project Structure

After `zensical new .`:

```
.
├── .github/           # GitHub Actions workflow for auto-deploy
├── docs/              # Markdown source files
│   ├── index.md       # Landing page
│   └── markdown.md    # Example page
└── zensical.toml      # Configuration
```

Key directories:
- `docs/` — Source markdown (configurable via `docs_dir`)
- `site/` — Build output (configurable via `site_dir`)
- `overrides/` — Custom templates, CSS, JS (when using `custom_dir`)

## 5. Configuration Format

`zensical.toml` — TOML format. Only required setting is `site_name`.

### Core settings

| Setting | Default | Description |
|---------|---------|-------------|
| `site_name` | *required* | Project name, appears in header |
| `site_url` | — | Canonical URL; **required** for instant navigation |
| `site_description` | — | HTML meta description |
| `site_author` | — | HTML meta author |
| `copyright` | — | Footer text (supports HTML) |
| `docs_dir` | `"docs"` | Source directory (relative to config) |
| `site_dir` | `"site"` | Build output directory |
| `use_directory_urls` | `true` | Clean URLs (`/foo/`) vs file URLs (`/foo/index.html`) |
| `dev_addr` | `localhost:8000` | Local dev server binding |
| `repo_url` | — | Repository URL (shows stars/forks badge) |
| `repo_name` | auto-inferred | Display name for repo link |
| `edit_uri` | auto-inferred | Path prefix for edit buttons |

### Theme settings

```toml
[project.theme]
variant = "modern"  # or "classic"
features = [
  "navigation.instant",
  "navigation.instant.prefetch",
  "navigation.tabs",
  "navigation.sections",
  "navigation.top",
  "navigation.tracking",
  "navigation.path",
  "navigation.indexes",
  "navigation.footer",
  "content.code.copy",
  "content.code.annotate",
  "content.action.edit",
  "content.action.view",
  "search.highlight",
  "toc.follow",
]
```

### Palette (light/dark toggle)

```toml
[[project.theme.palette]]
media = "(prefers-color-scheme: light)"
scheme = "default"
toggle = { icon = "lucide/moon", name = "Switch to dark mode" }

[[project.theme.palette]]
media = "(prefers-color-scheme: dark)"
scheme = "slate"
toggle = { icon = "lucide/sun", name = "Switch to light mode" }
```

## 6. Key Features

### Navigation features
- **Instant navigation**: XHR-based page transitions, no full reload
- **Prefetching**: Fetches linked pages on hover
- **Progress indicator**: Loading bar for slow connections
- **Tabs**: Top-level sections as horizontal tabs
- **Sticky tabs**: Tabs stay visible on scroll
- **Sections**: Sidebar group headers for top-level sections
- **Expand**: Auto-expand sidebar subsections
- **Breadcrumbs** (`navigation.path`): Breadcrumb trail above content
- **Pruning** (`navigation.prune`): 33%+ smaller output
- **Section indexes**: Attach pages directly to section headers
- **Back-to-top** (`navigation.top`): Scroll-up button

### Content features
- **Code copy** (`content.code.copy`): One-click code block copying
- **Code annotations** (`content.code.annotate`): Inline explanations
- **Code select** (`content.code.select`): Line selection in code blocks
- **Edit button** (`content.action.edit`): Link to edit on GitHub
- **View source** (`content.action.view`): Link to view source on GitHub

### Search
- Built-in search with `search.highlight` for term highlighting

### TOC
- `toc.follow`: Active heading tracking in table of contents
- `toc.integrate`: Merge TOC into navigation sidebar

## 7. Theming & Customization

### Custom CSS
Place in `docs/stylesheets/extra.css`, reference in config:
```toml
[project]
extra_css = ["stylesheets/extra.css"]
```

### Custom JavaScript
Place in `docs/javascripts/extra.js`, reference in config:
```toml
[project]
extra_javascript = ["javascripts/extra.js"]
```

### Template overrides
Set `custom_dir` to an overrides directory:
```toml
[project.theme]
custom_dir = "overrides"
```

Override specific templates by recreating them in `overrides/`:
- `overrides/main.html` — Extend `base.html`, override blocks (`htmltitle`, `header`, `footer`, `content`, `scripts`, `styles`)
- `overrides/partials/footer.html` — Replace specific partials
- `overrides/404.html` — Custom 404 page
- Use `{{ super() }}` to preserve original content while adding to it

### Icons
```toml
[project.theme.icon]
repo = "fontawesome/brands/github"
edit = "material/pencil"
view = "material/eye"
```

## 8. Navigation System

### Automatic
If no `nav` is specified, Zensical infers site structure from the file tree. Zero-configuration mode.

### Explicit

```toml
[project]
nav = [
  {"Home" = "index.md"},
  {"User Guide" = "user-guide.md"},
  {"Architecture" = [
    "architecture.md",
    "event-semantics.md",
  ]},
  {"API Reference" = [
    "externals-api.md",
    "externals-contract.md",
  ]},
  {"GitHub" = "https://github.com/Bullish-Design/remora-v2"},
]
```

Key rules:
- Paths are relative to `docs_dir`
- Strings that don't resolve to a file are treated as external URLs
- Sections are arrays of sub-items
- Can mix named entries with plain file paths

## 9. Markdown Capabilities

Zensical supports standard Markdown plus extensions:
- Fenced code blocks with syntax highlighting
- Tables
- Admonitions (callout boxes)
- Task lists
- Footnotes
- Definition lists
- Abbreviations
- MathJax / KaTeX support
- Mermaid diagrams (via code fences)
- Content tabs
- Icons / emojis
- Relative cross-page links (always link to `.md` files, not `.html`)

## 10. Development Workflow

```bash
# Preview locally with hot reload
zensical serve

# Build for production
zensical build --clean

# Create new project scaffold
zensical new .
```

`zensical serve` watches for file changes and auto-rebuilds. `zensical build --clean` removes old output before building.

## 11. Comparison to MkDocs Material

| Aspect | MkDocs Material | Zensical |
|--------|----------------|----------|
| Core language | Python | Rust + Python |
| Config format | YAML (`mkdocs.yml`) | TOML (`zensical.toml`) |
| Template engine | Jinja2 | MiniJinja (Rust) |
| Build speed | Slower for large sites | Significantly faster |
| Plugin ecosystem | Mature, extensive | Early, growing |
| Theme compatibility | MkDocs plugins | Partially compatible (migration path) |
| API docs | Via plugins (mkdocstrings) | Built-in capability planned |
| Maturity | 10+ years | ~5 months (v0.0.29) |

Zensical supports legacy `mkdocs.yml` for migration but recommends `zensical.toml`.

## 12. Current Limitations

- **Early release** (v0.0.29) — expect breaking changes
- **Plugin ecosystem** not yet as mature as MkDocs Material
- **CI caching** explicitly not recommended yet (performance optimization ongoing)
- **docs_dir cannot be `.`** — must be a subdirectory
- **No hook/plugin system documented** yet in public docs (only template overrides)

---

*Sources*:
- [Zensical GitHub Repository](https://github.com/zensical/zensical)
- [Zensical Documentation — Get Started](https://zensical.org/docs/get-started/)
- [Zensical Documentation — Create Your Site](https://zensical.org/docs/create-your-site/)
- [Zensical Documentation — Basics](https://zensical.org/docs/setup/basics/)
- [Zensical Documentation — Navigation](https://zensical.org/docs/setup/navigation/)
- [Zensical Documentation — Repository](https://zensical.org/docs/setup/repository/)
- [Zensical Documentation — Customization](https://zensical.org/docs/customization/)
- [Zensical Documentation — Publish Your Site](https://zensical.org/docs/publish-your-site/)
- [Zensical Announcement (Material for MkDocs blog)](https://squidfunk.github.io/mkdocs-material/blog/2025/11/05/zensical/)
