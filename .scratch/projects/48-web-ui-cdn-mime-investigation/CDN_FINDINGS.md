# CDN FINDINGS

Date verified: 2026-03-24

## Source URLs in Web UI
- `https://unpkg.com/graphology@0.25.4/dist/graphology.umd.min.js`
- `https://unpkg.com/sigma@3.0.0-beta.31/build/sigma.min.js`
- `https://unpkg.com/graphology-layout-forceatlas2@0.10.1/build/graphology-layout-forceatlas2.min.js`

## HTTP Results

1. Graphology URL
- Status: `200`
- `Content-Type: text/javascript; charset=utf-8`
- Loads as JavaScript as expected.

2. Sigma URL currently used (`/build/sigma.min.js`)
- Status: `404`
- `Content-Type: text/plain;charset=UTF-8`
- Body starts with: `Not found: /sigma@3.0.0-beta.31/build/sigma.min.js`
- Browser blocks due to `nosniff` + non-JS MIME.

3. ForceAtlas2 URL currently used (`/build/graphology-layout-forceatlas2.min.js`)
- Status: `404`
- `Content-Type: text/plain;charset=UTF-8`
- Body starts with: `Not found: /graphology-layout-forceatlas2@0.10.1/build/graphology-layout-forceatlas2.min.js`
- Browser blocks due to `nosniff` + non-JS MIME.

## Package Metadata Checks

1. `sigma@3.0.0-beta.31`
- `package.json` exists and is valid.
- Declares `dist/*` artifacts.
- `?meta` includes `/dist/sigma.min.js` (UMD-style bundle exposing `window.Sigma`).
- Conclusion: configured path `/build/sigma.min.js` is wrong; `/dist/sigma.min.js` exists.

2. `graphology-layout-forceatlas2@0.10.1`
- `package.json` exists and is valid.
- File list includes `index.js`, `iterate.js`, `worker.js`, `webworker.js`.
- No `build/` directory and no minified browser-global UMD file in package metadata.
- `index.js` uses CommonJS `require(...)` and is not directly browser-global script-tag ready.

## Runtime Link to Console Errors
- Inline script creates renderer with `new Sigma(...)`.
- Since Sigma script fails to load, `Sigma` is undefined and throws `ReferenceError` at runtime.
- ForceAtlas2 call is guarded by `if (window.graphologyLayoutForceatlas2)`, so that one does not throw by itself; it simply never runs.
