# Vendored static libraries

Two small third-party libraries back the Contextual Editor's markdown preview. Both are
fetched and pinned once at author time and committed — never loaded from a CDN at
runtime (preserves the console's offline/loopback-only guarantee). They sit flat in this
directory (no subdirectory) because the static file handler in `review.py`'s `do_GET`
only serves files whose resolved parent equals `UI_DIR`.

The SHA-256 is of the file **as vendored here** with LF endings, not of the upstream
download — stripping the trailing sourcemap comment is the only edit ever made to one, and
hashing the bytes we actually serve is what makes a hand-edit detectable.
`test_vendored_ui_libs_match_their_recorded_hashes` (`build/tests/test_review.py`) enforces
it, and `.gitattributes` marks these files `-text` so a Windows checkout can't rewrite the
endings out from under that check.

To bump a version: re-fetch, strip the sourcemap comment if present, re-hash the local
file, update the table below.

| File | Package | Version | Source URL | SHA-256 | License |
|---|---|---|---|---|---|
| `marked.min.js` | [marked](https://github.com/markedjs/marked) | 12.0.2 | https://unpkg.com/marked@12.0.2/marked.min.js | `15fabce5b65898b32b03f5ed25e9f891a729ad4c0d6d877110a7744aa847a894` | MIT |
| `dompurify.min.js` | [DOMPurify](https://github.com/cure53/DOMPurify) | 3.2.4 | https://unpkg.com/dompurify@3.2.4/dist/purify.min.js | `1e32499b1ed2de695902641db2fd342511b9b28b5d8cb9e0a24ffd3e51f25185` | Apache-2.0 / MPL-2.0 |

Both ship as UMD builds that assign a global (`window.marked`, `window.DOMPurify`)
when loaded via a classic `<script>` tag — no import map, no `type="module"`, no
bundler. Loaded in `index.html` immediately before `app.js`.

`marked` renders Markdown to HTML for the Contextual Editor's preview pane. It replaced
snarkdown in 0.1.6: snarkdown's indented-block rule matches ahead of its list rule, so a
sub-bullet rendered as stray text (2-space indent) or a `<pre class="poetry">` block
(4-space) — nested lists are out of scope upstream, not a bug to patch. marked also does
GFM tables and task lists, which the preview now styles.

marked does no sanitizing of its own (removed upstream in v5) — that is DOMPurify's job:
`DOMPurify.sanitize()` is applied to its output before it ever touches `innerHTML` —
the one deliberate, narrowly-scoped exception to the console's textContent-only rule
(see the header comment in `app.js`). A trailing `//# sourceMappingURL=...` comment was stripped
from `dompurify.min.js` since the corresponding `.map` file isn't vendored; the pinned
`marked.min.js` build ships without one.
