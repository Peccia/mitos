"""Rendering: clean documents, per-target skill frontmatter, MCP configs.

Deployed artifacts are RAW context — no banner, no provenance markers. The model reads
pure prose and pays no token tax for scaffolding. Provenance for `adopt` lives in the
lockfile (a per-section record captured at deploy), reconstructed by `split_live_sections`
below — not embedded in the file the model reads on every request.
"""
from __future__ import annotations

import difflib
import re

import yaml

from .loader import EXTENSION_ANCHOR, Prompt, Registry, Skill, SkillResource, document_stores

# how many lines plain_document inserts between sections ("\n\n" -> one blank line)
_SEP_LINES = 1

# The source label for a generated region inside an otherwise user-owned document
# (e.g. the knowledge-graph document block appended after a project's prose). It is NOT a
# registry partial — it routes to no file. Recording it as a `section_bodies` source lets
# adopt/drift treat that region as machine-owned (skip it) while protecting the prose
# sections around it, all WITHOUT any marker in the deployed file (invariant #5).
#
# A document may carry MORE THAN ONE generated region, in any position — notably a project
# node, whose generated repo roster sits inside `## Navigation` (near the top, so the
# reserved-section order holds) while its generated document map trails the prose. Each
# region kind gets its own `<generated:…>` label so the regions stay distinguishable;
# `is_generated_source` matches the whole family.
GENERATED_SECTION = "<generated>"
GENERATED_NAV = "<generated:navigation>"


def is_generated_source(src: str) -> bool:
    """True for any machine-owned region label (`<generated>`, `<generated:navigation>`, …)
    — never a registry partial path, which can't start with `<`."""
    return src == GENERATED_SECTION or src.startswith("<generated:")


def prose_sections(sections: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """The user-owned sections of a (possibly mixed) document — everything that is NOT a
    generated block. Drift/adopt compare and route only these."""
    return [(s, b) for s, b in sections if not is_generated_source(s)]


def join_prose(sections: list[tuple[str, str]]) -> str:
    """The prose-only projection of a section list, joined exactly as plain_document joins,
    so two section lists compare equal iff their prose is identical."""
    return "\n\n".join(b for s, b in sections if not is_generated_source(s))


# ── Documents ────────────────────────────────────────────────────────────────
def plain_document(sections: list[tuple[str, str]]) -> str:
    """The deployed artifact: partial bodies concatenated, nothing else.

    `sections` is a list of (source_rel, body). No banner, no markers — provenance is
    kept out of band (lockfile), so the moat carries only context. Ends in a newline.
    """
    return "\n\n".join(body for _, body in sections).strip("\n") + "\n"


def stub_document(import_line: str) -> str:
    """A thin generated file that just imports another (e.g. CLAUDE.md -> @AGENTS.md)."""
    return import_line.strip("\n") + "\n"


def split_live_sections(
    base_sections: list[tuple[str, str]], live: str
) -> list[tuple[str, str]] | None:
    """Carve an edited multi-section file back into per-region text.

    `base_sections` is the (source, body) breakdown recorded at deploy time. We align
    the live file against the document we deployed and map each section's content back
    out, so `adopt` can route an edit to its registry partial with no in-file markers.
    Returns [(source, live_text), …] IN DOCUMENT ORDER, or None if an edit straddles a
    section boundary (can't be cleanly attributed — the caller then resolves by hand).

    Ordered pairs, not a {source: text} mapping: one partial may contribute SEVERAL
    regions to a document when a generated region is interleaved between them (a project
    node's prose is split around its generated `## Navigation` repo roster). Keying by
    source would silently collapse those regions to whichever came last. Callers that
    write back to a partial rejoin its regions in this order — see
    `commands.route_into_registry`.
    """
    base_lines = plain_document(base_sections).rstrip("\n").split("\n")
    live_lines = live.rstrip("\n").split("\n")

    starts, cur = [], 0
    for _, body in base_sections:
        starts.append(cur)
        cur += len(body.split("\n")) + _SEP_LINES   # section lines + the blank after

    opcodes = difflib.SequenceMatcher(a=base_lines, b=live_lines,
                                      autojunk=False).get_opcodes()

    def to_live(bi: int) -> int | None:
        if bi >= len(base_lines):
            return len(live_lines)
        for tag, i1, i2, j1, j2 in opcodes:
            if i1 <= bi < i2:
                if tag == "equal":
                    return j1 + (bi - i1)
                return j1 if bi == i1 else None      # boundary inside an edit
        return len(live_lines)

    out: list[tuple[str, str]] = []
    for k, (src, body) in enumerate(base_sections):
        a = to_live(starts[k])
        b = to_live(starts[k] + len(body.split("\n")))   # first line past this section
        if a is None or b is None or b < a:
            return None
        out.append((src, "\n".join(live_lines[a:b]).strip("\n")))
    return out


def rejoin_regions(carved: list[tuple[str, str]], src: str) -> str:
    """Every region `src` contributed to a carved document, rejoined in document order
    exactly as `plain_document` joined them — so a partial split around a generated
    region round-trips to the same body it was deployed from."""
    return "\n\n".join(text for s, text in carved if s == src)



# ── User placeholders ────────────────────────────────────────────────────────
# Fixed, closed set. An unrecognized `{{...}}` token (or a known one with no configured
# value) is left as literal text by expand_placeholders — never silently dropped, since
# it might be markdown the author meant literally rather than a typo to eat.
_PLACEHOLDER_RE = re.compile(r"\{\{(\w+)\}\}")


_MACHINE_TOKENS = ("project_root", "skills_root", "returns_root")


def _machine_value(paths: dict | None, key: str) -> str | None:
    """The expansion for one machine-scoped placeholder on one machine, or None.

    - `project_root`: the agent tree root the machine hosts. Precedence mirrors which
      tree the persona navigates — `assistant_root` (the single Mitos Agent install root,
      holding both the tree and the harness's own files) over `agentic_context_root` (the
      agents-md-machine context tree) over `projects_root` (plain workstation checkouts).
    - `skills_root`: where deployed skills live — `<assistant_root>/skills` (matches the
      mitos-agent target's `skills.subdir` prefix; SOUL/skills/mcp share the install root
      with the tree).
    - `returns_root`: where a coding harness writes what it produced, for the return lane.
      On a machine hosting Mitos Agent this is its state directory's `returns/` — the exact
      folder `mitos-agent returns` reads. On a coding-only box there is no such harness and
      therefore no state directory, so it falls back to a machine-wide `.mitos-returns/`
      beside the checkouts.

      That fallback is a real seam and is documented as one: records written there are
      correct and complete, but nothing on that box reads them, so the owner points
      `mitos-agent returns --from` at the folder (or syncs it). Deliberately NOT reusing
      `project_root`: it resolves to `projects_root` on a coding box, which would put the
      records inside a path the harness's own resolver never looks at while LOOKING like it
      had worked — a silently wrong path is worse than an obviously separate one.
    """
    if not paths:
        return None
    if key == "project_root":
        for k in ("assistant_root", "agentic_context_root", "projects_root"):
            val = paths.get(k)
            if val:
                return str(val).rstrip("/")
        return None
    if key == "skills_root":
        home = paths.get("assistant_root")
        return f"{str(home).rstrip('/')}/skills" if home else None
    if key == "returns_root":
        home = paths.get("assistant_root")
        if home:
            # Must match mitos_agent.state.state_dir: <root>/.local-memory/, then returns/.
            return f"{str(home).rstrip('/')}/.local-memory/returns"
        projects = paths.get("projects_root")
        return f"{str(projects).rstrip('/')}/.mitos-returns" if projects else None
    return None


def _user_value(user: dict, key: str) -> str | None:
    """The expansion for one placeholder key, or None if `key` isn't one of the five
    fixed user tokens (or the configured value is empty)."""
    if key == "user_given_name":
        return user.get("given_name") or None
    if key == "users_given_name":
        gn = user.get("given_name")
        if not gn:
            return None
        return gn + ("'" if gn[-1].lower() == "s" else "'s")
    if key == "user_full_name":
        return user.get("full_name") or None
    if key == "user_email":
        return user.get("email") or None
    if key == "user_location":
        return user.get("location") or None
    return None


_USER_TOKENS = ("user_given_name", "users_given_name", "user_full_name",
                "user_email", "user_location")


def user_token_map(reg: Registry) -> dict[str, str]:
    """The reserved personalization tokens that resolve to a value, as {token: value}.

    The console's one-shot prompt copy reads this to auto-substitute Mitos-owned tokens
    (so the operator is never asked to type their own name) and to tell the remaining
    `{{tokens}}` apart as fillable inputs. Tokens with no configured value are omitted —
    they stay literal on copy, exactly as `expand_placeholders` leaves them at deploy."""
    return {tok: val for tok in _USER_TOKENS
            if (val := _user_value(reg.user, tok)) is not None}


def machine_token_names() -> list[str]:
    """The machine-scoped token names (`_MACHINE_TOKENS`), for callers outside this module.

    The console treats these as reserved-but-unresolvable: a copied prompt is destined for
    a chat app, not a machine deploy, so there is no machine whose paths could fill them.
    They are neither auto-substituted nor prompted for — they stay literal."""
    return list(_MACHINE_TOKENS)


def expand_placeholders(reg: Registry, text: str, machine_paths: dict | None = None) -> str:
    """Substitute the fixed personalization tokens with `reg.user` values, plus the
    machine-scoped tokens (`_MACHINE_TOKENS`) resolved from the deploying machine's
    paths (`_machine_value`). Without `machine_paths` (or on a machine that defines
    no matching path) a machine token stays literal, like any other unconfigured one."""
    def _sub(m: re.Match) -> str:
        key = m.group(1)
        val = (_machine_value(machine_paths, key) if key in _MACHINE_TOKENS
               else _user_value(reg.user, key))
        return val if val is not None else m.group(0)
    return _PLACEHOLDER_RE.sub(_sub, text)


def reverse_expand_placeholders(reg: Registry, original_text: str, live_text: str) -> str:
    """Fold expanded personalization values in `live_text` back into the placeholder
    tokens present in `original_text` (the registry partial as authored, BEFORE
    expansion) — scoped to that partial's own tokens so a coincidental match (e.g. the
    default `given_name` "User" appearing as an ordinary English word elsewhere) can
    never corrupt a partial that never used the placeholder in the first place.

    Longest expanded VALUE first: "Paul Peccia" (user_full_name) must reverse before
    "Paul" (user_given_name) — otherwise replacing "Paul" first would strand " Peccia"
    instead of restoring the full-name token.

    Machine-scoped tokens (`_MACHINE_TOKENS`) reverse against every machine's value
    (the adopt/review caller doesn't always know which machine the live text was
    expanded for), still scoped to partials that actually carry the token.
    """
    tokens = sorted(set(_PLACEHOLDER_RE.findall(original_text)))
    pairs = []
    for tok in tokens:
        if tok in _MACHINE_TOKENS:
            vals = {_machine_value((m or {}).get("paths"), tok)
                    for m in getattr(reg, "machines", {}).values()}
            pairs += [(v, f"{{{{{tok}}}}}") for v in vals if v]
            continue
        val = _user_value(reg.user, tok)
        if val:
            pairs.append((val, f"{{{{{tok}}}}}"))
    pairs.sort(key=lambda p: len(p[0]), reverse=True)
    out = live_text
    for val, tok in pairs:
        out = out.replace(val, tok)
    return out


# ── Org-roles generated block ────────────────────────────────────────────────
def _org_description(skill_body: str) -> str:
    """Extract the first paragraph under `## Description` in a skill body."""
    m = re.search(r"## Description\n(.*?)(?:\n##|\Z)", skill_body, re.DOTALL)
    if not m:
        return ""
    return m.group(1).strip()


def _org_primary_chain(skill_body: str) -> str:
    """Build a `A → B → C` chain from the `## 1.`, `## 2.`, `## 3.` section headers."""
    roles = re.findall(r"^## \d+\.\s+(.+?)(?:\s+—.*)?$", skill_body, re.MULTILINE)
    # strip sub-qualifier (e.g. "CEO — intent and objectives" → "CEO")
    names = [r.split("—")[0].strip() for r in roles]
    return " → ".join(names) if names else ""


def org_domain_table(skills: list) -> str:
    """Generate the `## Skills` section for `Projects/AGENTS.md` from the active
    org-domain skills (those whose frontmatter declares `org_domain`).

    Reserved section name (the taxonomy contract): every node's applicable playbooks live
    under `## Skills`; at the Projects node those are the simulated domain organizations.
    Each row shows: domain key, skill name, one-line description, and the primary
    delegation chain derived from the skill's section headers. Sorted by domain for
    stable output.
    """
    org_skills = [s for s in skills if s.frontmatter.get("org_domain")]
    org_skills.sort(key=lambda s: s.frontmatter["org_domain"])
    if not org_skills:
        return ""

    lines: list[str] = [
        "## Skills",
        "",
        "Simulated domain organizations for project work. Load the skill named in the "
        "`Skill` column that matches the task's domain before delegating any project work.",
        "",
        "| Domain | Skill | Description | Primary chain |",
        "|---|---|---|---|",
    ]
    for s in org_skills:
        domain = s.frontmatter["org_domain"]
        desc = _org_description(s.body)
        # Collapse multiline description to a single sentence for the table cell
        first_sentence = re.split(r"(?<=[.!?])\s", desc)[0] if desc else ""
        chain = _org_primary_chain(s.body)
        lines.append(f"| `{domain}` | `{s.name}` | {first_sentence} | {chain} |")
    return "\n".join(lines) + "\n"


_H2_HEADING = re.compile(r"^## ", re.MULTILINE)


def _skill_extensions(reg: Registry, skill: Skill) -> list[Skill]:
    """Skills that `extends_skill` this one, sorted by name for deterministic output."""
    return sorted((s for s in reg.skills.values()
                  if s.frontmatter.get("extends_skill") == skill.name),
                 key=lambda s: s.name)


def compose_skill_body(reg: Registry, skill: Skill) -> str:
    """Splice any extension skills into `skill`'s body — at RENDER time only, never on
    the loaded Registry (Skill.body stays pristine so the console, adopt, and harvest
    all read true registry state — see the R1 design decision). Extensions are inserted
    as new '### <role> — <ext-name> (extension)' subsections at the end of the
    EXTENSION_ANCHOR section (right before the next top-level '## ' heading, or at the
    end of the body if the anchor section is last) — order-independent and
    rename-tolerant, unlike matching a specific existing role heading (R2)."""
    exts = _skill_extensions(reg, skill)
    if not exts:
        return skill.body
    anchor_idx = skill.body.find(EXTENSION_ANCHOR)
    if anchor_idx < 0:
        # _validate rejects this at load time; stay defensive if called out of band
        return skill.body
    search_from = anchor_idx + len(EXTENSION_ANCHOR)
    m = _H2_HEADING.search(skill.body, search_from)
    insert_at = m.start() if m else len(skill.body)
    blocks = "\n\n".join(
        f"### {ext.frontmatter.get('extends_role', '')} — {ext.name} (extension)\n\n"
        f"{ext.body.strip(chr(10))}"
        for ext in exts)
    before = skill.body[:insert_at].rstrip("\n")
    after = skill.body[insert_at:]
    sep = "\n\n" if after else "\n"
    return f"{before}\n\n{blocks}{sep}{after}".rstrip("\n") + "\n"


def compose_skill_resources(reg: Registry, skill: Skill) -> dict[str, SkillResource]:
    """Merge `skill`'s own resources with those of any skill(s) that extend it — an
    extension's examples/scripts deploy alongside the parent's. On a relpath collision
    the extension wins (later in sort order wins), mirroring compose_skill_body's
    ordering."""
    merged = dict(skill.resources)
    for ext in _skill_extensions(reg, skill):
        merged.update(ext.resources)
    return merged


def dynamic_branches_block(branches: list[str]) -> str:
    """The `<generated>` block appended to the assistant root AGENTS.md listing any
    dynamically discovered branches (registry/context/<branch>/AGENTS.md) — see
    planner._plan_agents_md. Empty when there are none."""
    if not branches:
        return ""
    lines = ["## Extended Branches", "",
             "Custom branches discovered under `registry/context/<branch>/AGENTS.md`:", ""]
    for b in sorted(branches):
        lines.append(f"- `{b}/`")
    return "\n".join(lines) + "\n"


def navigation_block(repos: list[tuple[str, str]], *, emit_heading: bool = True) -> str:
    """The `<generated:navigation>` repo roster for a project node: one line per cloned
    checkout, `dirname/` plus its `repo_notes:` description. The SINGLE source for a
    project's repo list — a project's prose never hand-lists the same checkouts, which is
    what used to drift out of sync with the manifest.

    Deliberately NO clone URL: `## Navigation` is about local paths the agent opens with
    file/terminal tools, and the remote is deploy-time machinery the agent can read from
    the checkout's own `.git/config` on the rare occasion it needs it — not context worth
    paying for on every request.

    `emit_heading=False` when the project's prose already opened `## Navigation` (the
    roster then attaches beneath that authored routing prose) — the same
    prose-opened-the-section convention `planner._connection_emit` uses for the document
    map. Empty string when the project has no repos, so the section never renders bare.
    """
    if not repos:
        return ""
    lines = ["## Navigation", ""] if emit_heading else []
    for dirname, description in repos:
        lines.append(f"- `{dirname}/` — {description}" if description else f"- `{dirname}/`")
    return "\n".join(lines) + "\n"


def agentic_tree_note_block(subdir: str) -> str:
    """The `<generated>` cross-reference appended to a project's own root AGENTS.md when
    that project ALSO has an agentic_tree: mount — the "project within a project" note:
    two AGENTS.md-shaped files legitimately coexist (this one is the project's own
    document/repo index; the mount is a full operating tree), so name the split
    explicitly rather than leaving a reader to wonder which one is authoritative."""
    subdir = subdir.rstrip("/")
    return (
        f"## Operating Tree\n\n"
        f"This project also has a full agentic operating tree mounted at `{subdir}/` — "
        f"the same Navigation/Workflows/Skills shape a dedicated agentic machine gets. "
        f"See [`{subdir}/AGENTS.md`]({subdir}/AGENTS.md) for that context; this file is "
        f"this project's own document/repo index, generated separately.\n"
    )


def connection_label(servers: dict, ds: str | None) -> tuple[str, str] | None:
    """The `(heading, detail)` for a connection: `heading` is the STABLE section title
    `<Name> (`key`)` that SOUL and skills reference by name (never the raw description
    sentence, which would rename the section on every servers.yaml edit); `detail` is the
    human blurb — the part of the server `description` after ` — `, or "". None when the
    store is unset/"none" or unknown, so a node never names a connection it doesn't have."""
    ds = (ds or "").strip()
    if not ds or ds == "none":
        return None
    server = (servers or {}).get(ds)
    if not server:
        return None
    desc = (server.get("description") or "").strip()
    if " — " in desc:
        name, detail = desc.split(" — ", 1)
    else:
        name, detail = (desc or ds), ""
    return f"{name} (`{ds}`)", detail.strip()


def connections_block(servers: dict, machine: dict, user: dict) -> str:
    """The `<generated>` connection section(s) for a tree/branch root (operating root and
    the Assistant branch): the SHORT form — a `## <Name> (`key`)` heading plus one sentence
    on what the wired document store is for. Project nodes get the FULL form (folder paths
    + document map) from graph.py under the same heading. Empty (no section) when the
    machine has no document store. A machine bound to more than one store (multi
    connections) renders one such section per store, concatenated — each store gets its
    own heading/blurb, same as a single-store machine's."""
    possessive = _user_value(user, "users_given_name") or "the owner's"
    blocks = []
    for ds in document_stores(machine.get("document_store")):
        label = connection_label(servers, ds)
        if not label:
            continue
        heading, detail = label
        server = servers.get(ds) or {}
        categories = ", ".join(sorted((server.get("tools") or {}).keys()))
        suite = f" ({categories})" if categories else ""
        blurb = f" {detail}" if detail else ""
        blocks.append(
            f"## {heading}\n\n"
            f"Use this suite{suite} as the source of truth for {possessive} data.{blurb}")
    return ("\n\n".join(blocks) + "\n") if blocks else ""


def skills_block(skills: list) -> str:
    """The `<generated>` "## Skills" section for the operating root: one bullet per
    general-purpose (non org-domain) skill selected for this machine's Mitos Agent
    deployment, sourced from each skill's frontmatter `description` — the single place
    that text lives now (mirrors org_domain_table, which does the same for org-domain
    skills in their own table)."""
    general = sorted((s for s in skills if not s.frontmatter.get("org_domain")),
                     key=lambda s: s.name)
    if not general:
        return ""
    lines = ["## Skills", "",
             "Local instruction files at `{{skills_root}}/<category>/<name>/SKILL.md` — "
             "read one with the `read_file` file tool and follow it; a skill is never a "
             "callable tool.", ""]
    for s in general:
        desc = (s.frontmatter.get("description") or "").strip()
        lines.append(f"- `{s.name}`: {desc}")
    return "\n".join(lines) + "\n"


def project_roster_block(projects: list) -> str:
    """The `<generated>` "## Project Roster" section for Projects/AGENTS.md: one bullet
    per project folder deployed in this tree, sourced from each manifest's `name`,
    `slug`, and optional `description` — the single place that text lives (mirrors
    skills_block, which does the same for skill descriptions)."""
    if not projects:
        return ""
    lines = ["## Project Roster", ""]
    for proj in projects:
        name = proj.get("name") or proj.get("slug")
        desc = (proj.get("description") or "").strip()
        entry = f"- `Projects/{name}/` ({proj.get('slug')})"
        lines.append(entry + (f" — {desc}" if desc else ""))
    return "\n".join(lines) + "\n"


def strip_frontmatter(content: str) -> str:
    """Return a skill/markdown body with any leading YAML frontmatter removed."""
    m = re.match(r"^---\n.*?\n---\n?(.*)$", content, re.DOTALL)
    return (m.group(1) if m else content)


# ── Skills ───────────────────────────────────────────────────────────────────
_SKILL_BANNER = (
    "# Generated by mitos from registry/skills/{name}/. Do not edit here."
)


def render_skill(skill: Skill, target: str, body: str | None = None) -> str:
    """Render a skill's SKILL.md in the frontmatter flavor a target expects.

    `body` overrides skill.body when given — the planner passes the extension-composed
    body here (render.compose_skill_body) so the merge happens only at render time,
    never mutating the loaded Skill (see the R1 design decision)."""
    fm = skill.frontmatter
    b = body if body is not None else skill.body
    if target == "mitos-agent":
        meta = {
            "name": fm["name"],
            "description": fm.get("description", ""),
            "version": fm.get("version", "1.0.0"),
            "author": fm.get("author", "Paul Peccia"),
            "license": fm.get("license", "MIT"),
            "platforms": fm.get("platforms", ["linux", "macos", "windows"]),
        }
        # The per-skill tag block is still authored under the legacy `hermes:` key in
        # registry SKILL.md frontmatter — inert metadata (tags), not a target reference —
        # so the rename deliberately left those files alone (decision 4). Emitted under the
        # current name; rename the authored key when Mitos Agent defines its own skill
        # frontmatter (B-Stage 5b).
        tag_meta = fm.get("mitos_agent") or fm.get("hermes")
        if tag_meta:
            meta["metadata"] = {"mitos_agent": tag_meta}
        return _frontmatter_doc(meta, b)
    if target in ("claude-code", "claude-app", "antigravity"):
        # Agent Skills standard frontmatter: name + description. Antigravity follows
        # the same open standard — one shared branch, deliberately not a fourth flavor.
        meta = {"name": fm.get("name", skill.name),
                "description": fm.get("description", "")}
        return _frontmatter_doc(meta, b)
    raise ValueError(f"skill rendering not defined for target {target!r}")


# ── Prompts ──────────────────────────────────────────────────────────────────
def render_prompt(prompt: Prompt, target: str) -> str:
    """Render a prompt body for a target.

    claude-code: adds `description:` frontmatter so the slash-command picker shows it.
    All other targets: plain body text, no frontmatter (harness-agnostic substrate).
    """
    if target == "claude-code":
        meta = {"description": prompt.frontmatter.get("description", "")}
        return _frontmatter_doc(meta, prompt.body)
    return prompt.body.rstrip("\n") + "\n"


def _frontmatter_doc(meta: dict, body: str) -> str:
    fm = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True).rstrip("\n")
    return f"---\n{fm}\n---\n\n{body.rstrip(chr(10))}\n"


# ── MCP ──────────────────────────────────────────────────────────────────────
# The stdio<->HTTP bridge package + a PINNED version. `npx` launches whatever this
# resolves to as a child process of Claude, so a floating tag ("mcp-remote" / "@latest")
# would let a compromised or typosquatted publish run silently on every launch. Pinning
# an exact version makes every upgrade a deliberate, reviewable change to this one line.
# MAINTAINER: verify the version exists on npm (`npm view mcp-remote versions`) and bump
# here intentionally — never widen this to a range or a floating tag.
MCP_REMOTE_PKG = "mcp-remote"
MCP_REMOTE_VERSION = "0.1.29"
MCP_REMOTE_SPEC = f"{MCP_REMOTE_PKG}@{MCP_REMOTE_VERSION}"


def flat_tools(server: dict) -> list[str]:
    """Flatten servers.yaml tools (domain -> [tool]) into an ordered list."""
    tools: list[str] = []
    for group in (server.get("tools") or {}).values():
        tools.extend(group)
    return tools


def mitos_agent_mcp_config(servers: dict) -> dict:
    """The whole mcp.json Mitos Agent reads: one entry per wired store (keyed by server
    name), each carrying its transport, the URL as seen from this machine, and the flat
    tool list. A one-store machine yields a single entry — the same shape Hermes had, minus
    the surgical merge. See planner._agent_servers for the server map this consumes."""
    return {"mcpServers": {alias: {
        "url": server["url"],
        "transport": server.get("transport", "streamable-http"),
        "tools": flat_tools(server),
    } for alias, server in servers.items()}}


def antigravity_mcp_config(server: dict, alias: str) -> dict:
    url = server["url"]
    return {"mcpServers": {alias: {"url": url, "serverUrl": url}}}


def claude_desktop_mcp_config(server: dict, alias: str, *, os_name: str) -> dict:
    """Claude Desktop's claude_desktop_config.json only launches **stdio** child
    processes — it does not consume a remote `url`/`type` entry, and Anthropic's
    Connectors UI rejects non-https URLs, so a LAN server can't be added there either.

    For an HTTP/SSE server we therefore bridge stdio<->HTTP with `npx mcp-remote`,
    which runs locally and connects out to the server's url. Two flags mcp-remote
    requires for this case (confirmed against its README):
      • `--transport http-only` for a streamable-http server (else mcp-remote's default
        `http-first` makes a spurious SSE fallback attempt); `sse-only` for an SSE server.
      • `--allow-http` when the url is plain `http://` — mcp-remote REFUSES a non-https
        URL without it. Not added for https urls (not needed there).
    On Windows `npx` is a `.cmd` shim that Electron's spawn can't resolve directly, so
    the command is wrapped in `cmd /c`. A native stdio `command` server is passed through.

    The bridge package is pinned to an exact version (MCP_REMOTE_SPEC) so a floating
    tag can't silently pull a compromised publish on launch — see that constant.
    """
    transport = server.get("transport", "")
    if transport in ("streamable-http", "sse", "http"):
        url = server["url"]
        mode = "sse-only" if transport == "sse" else "http-only"
        bridge = [MCP_REMOTE_SPEC, url, "--transport", mode]
        if url.startswith("http://"):           # plain http needs explicit opt-in
            bridge.append("--allow-http")
        npx_args = ["-y", *bridge]
        if os_name == "windows":
            return {"mcpServers": {alias: {"command": "cmd", "args": ["/c", "npx", *npx_args]}}}
        return {"mcpServers": {alias: {"command": "npx", "args": npx_args}}}
    # native stdio server: pass its command/args straight through
    entry = {"command": server["command"]}
    if server.get("args"):
        entry["args"] = server["args"]
    return {"mcpServers": {alias: entry}}


def antigravity_permission_grants(server: dict, alias: str) -> dict:
    allow = [f"mcp({alias}/{tool})" for tool in flat_tools(server)]
    return {"sidecars": {}, "userSettings": {"globalPermissionGrants": {"allow": allow}}}


# ── Env overlay ──────────────────────────────────────────────────────────────
def merge_env(template_text: str, overlay_text: str | None) -> str:
    """Merge a .local overlay over an env template (overlay KEY=VALUE wins).

    Comments and key order from the template are preserved; overlay-only keys are
    appended.
    """
    overlay = _parse_env(overlay_text) if overlay_text else {}
    used: set[str] = set()
    lines_out: list[str] = []
    for line in template_text.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in overlay:
                lines_out.append(f"{key}={overlay[key]}")
                used.add(key)
                continue
        lines_out.append(line)
    extra = [k for k in overlay if k not in used]
    if extra:
        lines_out.append("")
        lines_out.append("# ── from .local overlay ──")
        lines_out.extend(f"{k}={overlay[k]}" for k in extra)
    return "\n".join(lines_out).rstrip("\n") + "\n"


def _parse_env(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        out[k.strip()] = v.strip()
    return out
