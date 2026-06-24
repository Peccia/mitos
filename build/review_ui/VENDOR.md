# Vendored static libraries

Two small third-party libraries back the Contextual Editor's markdown preview. Both are
fetched and pinned once at author time and committed — never loaded from a CDN at
runtime (preserves the console's offline/loopback-only guarantee). They sit flat in this
directory (no subdirectory) because the static file handler in `review.py`'s `do_GET`
only serves files whose resolved parent equals `UI_DIR`.

To bump a version: re-fetch, re-hash, update the table below.

| File | Package | Version | Source URL | SHA-256 | License |
|---|---|---|---|---|---|
| `snarkdown.js` | [snarkdown](https://github.com/developit/snarkdown) | 2.0.0 | https://unpkg.com/snarkdown@2.0.0/dist/snarkdown.umd.js | `13738c61429d28d7a440c55498e54015d46ad2411d27bc1fa29ae7611c140a40` | MIT |
| `dompurify.min.js` | [DOMPurify](https://github.com/cure53/DOMPurify) | 3.2.4 | https://unpkg.com/dompurify@3.2.4/dist/purify.min.js | `1e32499b1ed2de695902641db2fd342511b9b28b5d8cb9e0a24ffd3e51f25185` | Apache-2.0 / MPL-2.0 |

Both ship as UMD builds that assign a global (`window.snarkdown`, `window.DOMPurify`)
when loaded via a classic `<script>` tag — no import map, no `type="module"`, no
bundler. Loaded in `index.html` immediately before `app.js`.

`snarkdown` renders Markdown to HTML for the Contextual Editor's preview pane;
`DOMPurify.sanitize()` is applied to that output before it ever touches `innerHTML` —
the one deliberate, narrowly-scoped exception to the console's textContent-only rule
(see the header comment in `app.js`). Trailing `//# sourceMappingURL=...` comments were
stripped from both files since the corresponding `.map` files aren't vendored.
