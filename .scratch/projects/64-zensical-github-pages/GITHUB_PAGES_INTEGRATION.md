# GitHub Pages Integration Analysis

## Table of Contents

1. [How Zensical + GitHub Pages Works](#1-how-zensical--github-pages-works)
2. [Deployment Approaches](#2-deployment-approaches)
3. [Recommended Workflow (GitHub Actions)](#3-recommended-workflow-github-actions)
4. [Alternative: Third-Party Action](#4-alternative-third-party-action)
5. [GitHub Repository Settings Required](#5-github-repository-settings-required)
6. [Trigger Strategy](#6-trigger-strategy)
7. [Build & Output Details](#7-build--output-details)
8. [URL & Domain](#8-url--domain)
9. [Caching Considerations](#9-caching-considerations)
10. [Security & Permissions](#10-security--permissions)

---

## 1. How Zensical + GitHub Pages Works

The integration is straightforward:

1. Documentation lives as Markdown files in the repo (e.g., `docs/`)
2. A GitHub Actions workflow triggers on push to `main`
3. The workflow installs Zensical, runs `zensical build --clean`
4. The built `site/` directory is uploaded as a GitHub Pages artifact
5. GitHub deploys the artifact to `<username>.github.io/<repo>`

There is **no separate branch** (no `gh-pages` branch needed). The modern approach uses GitHub's built-in Pages deployment via artifacts, which is cleaner and avoids polluting the git history with built files.

## 2. Deployment Approaches

### Approach A: Official workflow (recommended)

Uses standard GitHub Actions (`actions/upload-pages-artifact` + `actions/deploy-pages`). This is the approach documented on [zensical.org](https://zensical.org/docs/publish-your-site/).

**Pros**: No third-party dependencies, official support, fine-grained control.
**Cons**: Slightly more YAML to write.

### Approach B: Zensical Action (cssnr/zensical-action)

A third-party GitHub Action from the marketplace that wraps checkout + build + upload + deploy.

**Pros**: Minimal YAML (single `uses:` line).
**Cons**: Third-party dependency, less control over build steps.

### Approach C: gh-pages branch (legacy)

Build locally or in CI, push to a `gh-pages` branch.

**Pros**: Works without Pages artifact support.
**Cons**: Pollutes git history, more complex, legacy pattern.

**Recommendation**: Approach A — official workflow with standard GitHub Actions.

## 3. Recommended Workflow (GitHub Actions)

File: `.github/workflows/docs.yml`

```yaml
name: Documentation

on:
  push:
    branches:
      - main

permissions:
  contents: read
  pages: write
  id-token: write

jobs:
  deploy:
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}
    runs-on: ubuntu-latest
    steps:
      - uses: actions/configure-pages@v5

      - uses: actions/checkout@v5

      - uses: actions/setup-python@v5
        with:
          python-version: 3.x

      - run: pip install zensical

      - run: zensical build --clean

      - uses: actions/upload-pages-artifact@v4
        with:
          path: site

      - uses: actions/deploy-pages@v4
        id: deployment
```

### How it works step by step

1. **`configure-pages`** — Prepares the GitHub Pages environment
2. **`checkout`** — Clones the repo (including `docs/` and `zensical.toml`)
3. **`setup-python`** — Installs Python 3.x
4. **`pip install zensical`** — Installs Zensical and all dependencies
5. **`zensical build --clean`** — Builds Markdown → static HTML into `site/`
6. **`upload-pages-artifact`** — Packages `site/` as a deployment artifact
7. **`deploy-pages`** — Deploys the artifact to GitHub Pages

## 4. Alternative: Third-Party Action

File: `.github/workflows/docs.yml`

```yaml
name: Documentation

on:
  push:
    branches:
      - main

permissions:
  contents: read
  pages: write
  id-token: write

jobs:
  deploy:
    environment:
      name: github-pages
      url: ${{ steps.zensical.outputs.page_url }}
    runs-on: ubuntu-latest
    steps:
      - uses: cssnr/zensical-action@v1
        id: zensical
```

Source: [cssnr/zensical-action on GitHub Marketplace](https://github.com/marketplace/actions/zensical-action)

This is simpler but adds a third-party dependency. The official approach (Section 3) is preferred.

## 5. GitHub Repository Settings Required

Before the workflow runs, you need to configure GitHub Pages in the repo settings:

1. Go to **Settings → Pages**
2. Under **Source**, select **GitHub Actions** (not "Deploy from a branch")
3. No branch selection needed — the workflow handles everything

This is a one-time setup. After this, every push to `main` triggers automatic deployment.

## 6. Trigger Strategy

The workflow triggers on push to `main`. For a documentation site that should "just update automatically," this is ideal:

```yaml
on:
  push:
    branches:
      - main
```

### Optional: Path filtering

To only rebuild when docs actually change (saves CI minutes):

```yaml
on:
  push:
    branches:
      - main
    paths:
      - 'docs/**'
      - 'zensical.toml'
```

**Trade-off**: Path filtering means changes to `zensical.toml` or docs are the only triggers. If you reference files outside `docs/`, you'd need to add those paths too. For a small project, triggering on every push to `main` is fine — Zensical builds are fast.

### Optional: Manual trigger

Add `workflow_dispatch` for on-demand rebuilds:

```yaml
on:
  push:
    branches:
      - main
  workflow_dispatch:
```

## 7. Build & Output Details

- **Input**: `docs/` directory + `zensical.toml` (both at repo root)
- **Output**: `site/` directory containing static HTML, CSS, JS, search index
- **Build command**: `zensical build --clean`
  - `--clean` removes stale output before building
- **Build time**: Very fast (Rust core); typically seconds even for moderate sites
- The `site/` directory should be in `.gitignore` (no need to commit built files)

## 8. URL & Domain

### Default URL
After deployment, the site appears at:
```
https://bullish-design.github.io/remora-v2/
```

This is derived from: `https://<org>.github.io/<repo>/`

### Custom domain
GitHub Pages supports custom domains. Configure via:
1. **Settings → Pages → Custom domain**
2. Add a `CNAME` file to the built output (or `docs/CNAME`)
3. Set DNS records (CNAME or A record)

### site_url configuration
The `site_url` in `zensical.toml` must match the deployment URL for instant navigation and sitemap generation to work:

```toml
[project]
site_url = "https://bullish-design.github.io/remora-v2/"
```

## 9. Caching Considerations

Zensical's official documentation explicitly advises **against using pip caching on CI** during this phase of development, as performance optimization is still underway. The Rust-based build itself is fast enough that this isn't a practical issue.

If you later want to add caching:
```yaml
- uses: actions/setup-python@v5
  with:
    python-version: 3.x
    cache: pip
```

But defer this until Zensical officially supports it.

## 10. Security & Permissions

The workflow requires three permissions:

| Permission | Reason |
|------------|--------|
| `contents: read` | Read repo files (checkout) |
| `pages: write` | Deploy to GitHub Pages |
| `id-token: write` | OIDC token for Pages deployment auth |

These are the minimum required. The workflow runs in a fresh Ubuntu container, installs Python + Zensical, builds, and deploys. No secrets or tokens need manual configuration — GitHub's OIDC handles auth automatically.

---

*Sources*:
- [Zensical — Publish Your Site](https://zensical.org/docs/publish-your-site/)
- [cssnr/zensical-action (GitHub Marketplace)](https://github.com/marketplace/actions/zensical-action)
- [GitHub Pages Documentation](https://docs.github.com/en/pages)
