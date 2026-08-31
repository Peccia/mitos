"""Turn the registry + a machine profile into a concrete list of Output files.

An Output is one file the compiler will materialize: rendered content, where it deploys
(POSIX path, possibly ~-rooted), its drift policy, and the registry sources that fed it
(so `adopt` can route edits back). yaml_merge outputs carry the owned-keys block to
splice into a tool's own config file at deploy time.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, replace

import yaml

from . import render
from .io import safe_rel
from .loader import (Registry, RegistryError, is_manual_skill_target, resolve_local_path,
                     _repo_basename, document_stores)

# A dynamically discovered agentic branch: any partial whose logical key matches
# context/<branch>/AGENTS.md marks <branch> as a user-extensible branch (see
# _plan_agents_md's dynamic-branch discovery — the only way an overlay user extends the
# assistant tree without forking targets/agents-md.yaml, which is not overlayable).
_BRANCH_RE = re.compile(r"^context/([^/]+)/AGENTS\.md$")

# The single assistant-harness target. Three predicates below all test it today, but they
# ask genuinely different questions and must not be collapsed into one — see
# docs/concepts/mitos-agent-platform.md §4.1. NOTE a FOURTH gate lives in _plan_claude_code
# (`is_assistant_tree_machine = "agents-md" in targets`); it keys off `agents-md`, NOT this
# target, decides graph-AGENTS.md vs CLAUDE.md-stub, and is deliberately kept separate.
ASSISTANT_TARGET = "mitos-agent"


def deploys_org_content(machine) -> bool:
    """Question A — do org skills actually land on this machine? Gates the org-domain table
    and every per-effort routing line. A machine can reach the tree without deploying org
    skills, and must then render `orgDomain` as inert metadata rather than a routing line
    pointing at a skill that was never deployed."""
    return ASSISTANT_TARGET in machine.get("targets", [])


def hosts_assistant_tree(machine) -> bool:
    """Question B — does this machine already host the operating tree at its root, with a
    SOUL.md carrying the persona? Nothing to do with orgs."""
    return ASSISTANT_TARGET in machine.get("targets", [])


def deploys_assistant_skills(reg, machine) -> bool:
    """Question C — does this machine deploy the assistant's skill set? Needs the target
    spec, not just a boolean."""
    return bool(ASSISTANT_TARGET in machine.get("targets", [])
                and (reg.targets.get(ASSISTANT_TARGET) or {}).get("skills"))


@dataclass
class Output:
    target: str
    kind: str                       # "text" | "json" | "yaml_merge" | "env"
    deploy_path: str                # POSIX; may begin with ~
    dist_rel: str                   # path under dist/<machine>/
    content: str                    # rendered text (yaml_merge: owned block; env: TEMPLATE only)
    drift_policy: str               # "protect" | "harvest"
    sources: list[str] = field(default_factory=list)
    owned_keys: list[str] = field(default_factory=list)   # merge kinds: owned key paths
    target_file: str = ""           # yaml_merge/json_merge: live file to splice into
    env_local: str = ""             # env: repo-relative overlay path, merged at deploy time
    owned_prefix: str = ""          # json_merge: within an owned LIST, own only entries
                                    # with this prefix (others are user-owned, preserved)
    lane: str = "content"           # "content" (registry prose) | "connections" (MCP
                                    # wiring + env) — deploy/diff filter on --lane
    zip_member: str = ""            # zip: archive member path (e.g. "<name>/SKILL.md");
                                    # content holds the member TEXT, bytes are derived
    zip_members: dict[str, str] = field(default_factory=dict)  # zip: when set, a
                                    # multi-member archive (member path -> text) — a
                                    # skill bundling examples/scripts alongside SKILL.md.
                                    # Takes precedence over zip_member/content in _payload.
    executable: bool = False        # text outputs deployed under a skill's scripts/:
                                    # deploy sets the executable bit on POSIX machines
    section_bodies: list = field(default_factory=list)  # multi-source text outputs:
                                    # (source, body) breakdown recorded in the lockfile
                                    # so adopt can route edits back without in-file markers


def _visible_projects(reg: Registry) -> Registry:
    """A shallow copy of `reg` with `hidden: true` projects dropped from BOTH `.projects` and
    `.graphs` — the single choke point `plan_machine` and `plan_clones` route every
    project-planning loop through, so a hidden project contributes NO planned output on any
    machine: no tree node, no roster entry, no clone, no per-project AGENTS.md/CLAUDE.md.
    Both collections have to be filtered: most lanes iterate `reg.projects`, but
    `_plan_graph_tree` (the agentic-graph reference tree) drives its roster and per-project
    doc index straight from `reg.graphs`, independently of `reg.projects` — missing either
    one leaves the project half-hidden. `loader.load()` itself never filters, so the
    manifest and graph still load and query fine outside planning (`mitos graph`, the
    console) — this copy exists only for the duration of one plan call. A no-op copy when
    nothing is hidden, so the common case costs nothing."""
    if not any(p.get("hidden") for p in reg.projects.values()):
        return reg
    hidden = {s for s, p in reg.projects.items() if p.get("hidden")}
    return replace(reg,
                   projects={s: p for s, p in reg.projects.items() if s not in hidden},
                   graphs={s: g for s, g in reg.graphs.items() if s not in hidden})


def plan_machine(reg: Registry, machine_name: str) -> list[Output]:
    reg = _visible_projects(reg)
    machine = reg.machines.get(machine_name)
    if machine is None:
        raise KeyError(f"unknown machine: {machine_name}")
    paths = machine.get("paths", {})
    outputs: list[Output] = []
    for target in machine.get("targets", []):
        spec = reg.targets[target]
        if target == "agents-md":
            outputs += _plan_agents_md(reg, machine_name, spec, paths)
        elif target == "mitos-agent":
            outputs += _plan_mitos_agent(reg, machine_name, spec, paths)
        elif target == "claude-code":
            outputs += _plan_claude_code(reg, machine_name, spec, paths)
        elif target == "antigravity":
            outputs += _plan_antigravity(reg, machine_name, spec, paths)
        elif target == "claude-app":
            outputs += _plan_claude_app(reg, machine_name, spec, paths)
    outputs += _plan_env(reg, machine_name, paths)
    outputs += _plan_graph_tree(reg, machine_name, paths)
    outputs += _plan_agentic_tree_mounts(reg, machine_name)

    # Validate output path collisions (prevent two targets/rules from deploying to the
    # same file). Merge kinds (yaml_merge/json_merge) are exempt from the single-owner
    # rule — several merge blocks legitimately splice into the same tool-owned file
    # (e.g. antigravity's config.json carries both a json output and a json_merge) — but their
    # owned_keys must not overlap (exactly, or as a dotted prefix of one another), or two
    # blocks would fight over the same leaf.
    def _dotted_overlap(a: str, b: str) -> bool:
        return a == b or a.startswith(b + ".") or b.startswith(a + ".")

    seen: dict[str, Output] = {}
    seen_merge_keys: dict[str, list[tuple[str, str]]] = {}  # path -> [(owner, dotted_key)]
    is_win = machine.get("os") == "windows"
    _MERGE_KINDS = ("yaml_merge", "json_merge")
    for o in outputs:
        p = o.deploy_path.lower() if is_win else o.deploy_path
        if o.kind in _MERGE_KINDS:
            owner = f"{o.target}:{o.kind}"
            prior = seen_merge_keys.setdefault(p, [])
            for other_owner, other_key in prior:
                for key in o.owned_keys:
                    if _dotted_overlap(key, other_key):
                        raise RegistryError(
                            f"machine {machine_name}: owned-key collision on '{o.deploy_path}' — "
                            f"'{other_key}' is claimed by both {other_owner} and {owner}.")
            prior.extend((owner, k) for k in o.owned_keys)
            continue
        if p in seen:
            other = seen[p]
            raise RegistryError(
                f"machine {machine_name}: output path collision on '{o.deploy_path}'. "
                f"Target '{o.target}' ({o.kind}) and target '{other.target}' ({other.kind}) "
                f"both plan to write to the same path. Check your machine profile and target configurations.")
        seen[p] = o

    # Validate the markdown-structure contract on every tree-node file (the header
    # taxonomy skills/SOUL reference by name). Runs pre-expansion — placeholders live in
    # bodies, never in headings — so it sees the true heading grammar.
    md_problems: list[str] = []
    for o in outputs:
        for prob in lint_node_markdown(o):
            md_problems.append(f"  {o.deploy_path}: {prob}")
    if md_problems:
        raise RegistryError(
            f"machine {machine_name}: markdown-structure contract violated "
            f"({len(md_problems)} problem(s)):\n" + "\n".join(md_problems))

    return [_expand_output(reg, o, paths, machine) for o in outputs]


# The reserved H2 sections, in the canonical order every tree-node file follows. SOUL and
# skills reference these names, so an author/generator may not rename, re-level, or reorder
# them. File-specific sections (e.g. a project's `## Invariants`, the connection section, a
# generated roster) are unconstrained and may appear between them.
RESERVED_SECTIONS = ["Navigation", "Workflows", "Tools", "Skills"]


def lint_node_markdown(o: "Output") -> list[str]:
    """Structure-contract problems for a tree-node file (`AGENTS.md` / `AGENTS_DETAILS.md`),
    or [] when it conforms (and for every non-node output, which is skipped). Enforces: one
    H1 (node identity); no heading-level skips; and the reserved sections — when present —
    at H2 and in canonical order. Effort/prose collisions are prevented structurally (the
    document map renders efforts at H3, one level under the connection section)."""
    if o.kind != "text":
        return []
    base = o.deploy_path.replace("\\", "/").rsplit("/", 1)[-1]
    if base not in ("AGENTS.md", "AGENTS_DETAILS.md"):
        return []

    headings: list[tuple[int, str]] = []
    in_fence = False
    for line in o.content.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = re.match(r"^(#{1,6}) +(\S.*?)\s*$", line)
        if m:
            headings.append((len(m.group(1)), m.group(2).strip()))

    problems: list[str] = []
    h1s = [t for lvl, t in headings if lvl == 1]
    if len(h1s) != 1:
        problems.append(f"expected exactly one H1 (node identity), found {len(h1s)}: {h1s}")
    prev = 0
    for lvl, t in headings:
        if prev and lvl > prev + 1:
            problems.append(f"heading level skips H{prev}→H{lvl} at '{t}'")
        prev = lvl
    seen_idx = -1
    for lvl, t in headings:
        if t in RESERVED_SECTIONS:
            if lvl != 2:
                problems.append(f"reserved section '{t}' must be H2, found H{lvl}")
            idx = RESERVED_SECTIONS.index(t)
            if idx < seen_idx:
                problems.append(
                    f"reserved section '{t}' is out of order — canonical order is "
                    f"{RESERVED_SECTIONS}")
            seen_idx = max(seen_idx, idx)
    return problems


def _expand_output(reg: Registry, o: Output, machine_paths: dict | None = None,
                   machine: dict | None = None) -> Output:
    """Personalization pass (the dynamic-context-enhancements design): substitute the
    fixed `{{user_*}}` placeholders — plus the machine-scoped `{{project_root}}` —
    in every markdown/text output and skill-zip member.
    Tool-owned merge configs (yaml_merge/json_merge) and env templates are excluded —
    they are machine wiring, not prose the model reads, and the .local/ env overlay
    must never flow through this pass (see io/secrets invariant).

    `machine` is threaded through for `{{connection}}`, which resolves from the profile's
    `document_store:` rather than its `paths:`."""
    def _x(text: str) -> str:
        return render.expand_placeholders(reg, text, machine_paths, machine)
    if o.kind == "text":
        return replace(
            o, content=_x(o.content),
            section_bodies=[(s, _x(b)) for s, b in o.section_bodies])
    if o.kind == "zip":
        if o.zip_members:
            return replace(o, zip_members={k: _x(v) for k, v in o.zip_members.items()})
        return replace(o, content=_x(o.content))
    return o


# ── claude-app (claude.ai account surface — web + Desktop) ───────────────────────
def _plan_claude_app(reg, machine_name, spec, paths) -> list[Output]:
    """The Claude consumer app — one account surface shared by claude.ai web and the
    Desktop app. Skills and connectors set on the account appear in both. This target
    emits two independent, opt-in-by-path-key kinds:

      • SKILLS (content lane): claude.ai exposes no filesystem the compiler can reach,
        so deploy STAGES ready-to-upload skill zips (<name>/SKILL.md inside) at
        `claude_skills_staging`. Upload is MANUAL (Customize > Skills); a `pending` zip
        after a registry edit is the re-upload reminder. Synced to web + Desktop.

      • MCP (connections lane): the account Connectors UI accepts remote servers by
        URL but only over https, so a LAN/HTTP server can't be added there. As a
        Desktop-only workaround we splice an `npx mcp-remote` stdio bridge into
        `claude_desktop_config.json` (when `claude_desktop_config` is set), owning just
        the `mcpServers` key so Desktop's own preferences survive.

    Each half is independent: a web-only machine sets `claude_skills_staging` only; a
    Desktop machine sets both keys.
    """
    outputs: list[Output] = []
    # — skills —
    sk = spec.get("skills") or {}
    staging = paths.get(sk.get("deploy_to_key", "claude_skills_staging"))
    if sk and staging:
        for skill in _selected_skills(reg, sk, reg.machines[machine_name]):
            body = render.compose_skill_body(reg, skill)
            resources = render.compose_skill_resources(reg, skill)
            content = render.render_skill(skill, "claude-app", body=body)
            deploy_path = f"{staging.rstrip('/')}/{skill.name}.zip"
            # zip_members stays empty for the common case (no resources) so _payload
            # falls back to the plain zip_member+content path — content alone remains
            # the single source of truth there, exactly as before this feature.
            zip_members = {}
            if resources:
                zip_members = {f"{skill.name}/SKILL.md": content}
                zip_members.update({f"{skill.name}/{relpath}": res.text
                                    for relpath, res in resources.items()})
            outputs.append(Output(
                target="claude-app", kind="zip", deploy_path=deploy_path,
                dist_rel=f"claude-app/{safe_rel(deploy_path)}",
                content=content,
                drift_policy=sk.get("drift_policy", "protect"),
                sources=[skill.rel] + [res.rel for res in resources.values()],
                zip_member=f"{skill.name}/SKILL.md", zip_members=zip_members,
            ))
    # — Desktop MCP config (LAN/HTTP workaround) —
    mc = spec.get("mcp_config") or {}
    dest = paths.get(mc.get("deploy_to_key", "claude_desktop_config"))
    gws = _gws(reg, machine_name) if (mc and dest) else None
    if gws:
        alias = spec["server_alias"]
        outputs.append(Output(
            target="claude-app", kind="json_merge", deploy_path=dest,
            dist_rel=f"claude-app/{safe_rel(dest)}",
            content=_json(render.claude_desktop_mcp_config(
                gws, alias, os_name=reg.machines[machine_name].get("os", ""))),
            owned_keys=["mcpServers"], target_file=dest,
            drift_policy=mc.get("drift_policy", "protect"), lane="connections",
            sources=["connections/servers.yaml"],
        ))
    return outputs


# ── env overlays ─────────────────────────────────────────────────────────────
def _plan_env(reg: Registry, machine_name: str, paths: dict) -> list[Output]:
    """One output per MCP server with an env template and a `<server>_env` path key on
    this machine. The Output carries the TEMPLATE only — deploy merges the `.local/`
    overlay just-in-time, so secrets never flow through dist/ or compile.
    """
    outputs: list[Output] = []
    for name, server in (reg.servers.get("servers") or {}).items():
        tmpl_rel = server.get("env_template")
        dest = paths.get(f"{name}_env")
        if not tmpl_rel or not dest or machine_name not in (server.get("hosted_on") or []):
            continue
        tmpl_path = reg.root / tmpl_rel
        if not tmpl_path.is_file():
            raise RegistryError(f"servers.{name}: env_template not found: {tmpl_rel}")
        outputs.append(Output(
            target="env", kind="env", deploy_path=dest,
            dist_rel=f"env/{safe_rel(dest)}",
            content=tmpl_path.read_text(encoding="utf-8"),
            drift_policy="protect", lane="connections", sources=[tmpl_rel],
            env_local=server.get("env_local", ""),
        ))
    return outputs


# ── repo auto-clone (the deployed project-tree design) ───────────────────────────
@dataclass
class CloneSpec:
    slug: str
    repo: str          # git URL from the manifest
    dest: str          # POSIX checkout dir — under agentic_context_root or local_path
    branch: str = ""   # branch to check out / fast-forward (repo_branches:); "" = default
    ssh_key: str = ""  # private key to auth with (repo_ssh_keys:); "" = ambient default identity


def _project_repos(proj: dict) -> list[str]:
    """Normalized list of git URLs from a project manifest's `repo:` field.
    Accepts either a single string or a list of strings; always returns a list."""
    raw = proj.get("repo")
    if not raw:
        return []
    if isinstance(raw, str):
        url = raw.strip()
        return [url] if url else []
    return [u.strip() for u in raw if isinstance(u, str) and u.strip()]


def _project_repo_entries(proj: dict) -> list[tuple[str, str, str]]:
    """(url, checkout basename, description) for each of a project's repos — the
    description comes from `repo_notes:`, keyed by basename (loader-validated to match),
    empty string when the repo has no note. Feeds `graph.project_full_markdown`'s
    generated `## Workspace Layout` section — the one place repo descriptions render."""
    notes = proj.get("repo_notes") or {}
    return [(url, _repo_basename(url), str(notes.get(_repo_basename(url), "")).strip())
            for url in _project_repos(proj)]


def _repo_branch(proj: dict, basename: str) -> str:
    """The branch to check out for a repo, keyed by checkout basename (`repo_branches:`).
    Empty string means the repo's default branch."""
    return str((proj.get("repo_branches") or {}).get(basename, "")).strip()


def _repo_ssh_key(proj: dict, basename: str) -> str:
    """The private key to authenticate with for a repo, keyed by checkout basename
    (`repo_ssh_keys:`). Empty string means the ambient default git/ssh identity."""
    return str((proj.get("repo_ssh_keys") or {}).get(basename, "")).strip()


def _reg_root_norm(reg: Registry) -> str:
    """Normalised, slash-terminated registry root for guard comparisons."""
    return str(reg.root).replace("\\", "/").rstrip("/")


def plan_clones(reg: Registry, machine_name: str) -> list[CloneSpec]:
    """Repos to clone (and keep current) on machines that host a project tree, absent-only
    for the clone / fast-forward-only for the pull — never destructive.

    Two lanes:
    - assistant_root (mitos-agent machines): clone into
      <assistant_root>/Projects/<name>/<basename> — a SIBLING of the operating tree's
      project node (_emit_tree uses the project NAME for that folder), so the planning
      harness resolves a checkout structurally from the node's own directory.
    - agentic_context_root (agents-md + claude-code machines): clone into
      <agentic_context_root>/Projects/<slug>/<basename> — the reference context tree
      (_plan_graph_tree uses the SLUG for that folder).

    The deploy executor clones each only when its checkout is ABSENT, and fast-forwards an
    existing checkout (never resetting or deleting one — design rule #8). Machines that host
    no project tree (no mitos-agent and no claude-code + agents-md reference tree) get nothing.
    """
    reg = _visible_projects(reg)
    machine = reg.machines.get(machine_name) or {}
    targets = machine.get("targets", [])
    paths = machine.get("paths") or {}
    suppressed = _suppressed_examples(reg)

    def _repo_specs(slug: str, proj: dict, parent: str) -> list[CloneSpec]:
        specs: list[CloneSpec] = []
        for repo in _project_repos(proj):
            bn = _repo_basename(repo)
            specs.append(CloneSpec(slug=slug, repo=repo, dest=f"{parent}/{bn}",
                                   branch=_repo_branch(proj, bn),
                                   ssh_key=_repo_ssh_key(proj, bn)))
        return specs

    out: list[CloneSpec] = []

    # assistant_root lane (mitos-agent operating tree — clones beside the project node,
    # which _emit_tree names with the project NAME). Suppressed examples step aside, exactly
    # as the operating tree itself does when real overlay projects exist.
    if "mitos-agent" in targets:
        aroot = paths.get("assistant_root")
        if aroot:
            aroot = str(aroot).rstrip("/")
            for slug, proj in sorted(reg.projects.items()):
                if slug in suppressed:
                    continue
                name = proj.get("name", slug)
                out += _repo_specs(slug, proj, f"{aroot}/Projects/{name}")

    if "claude-code" not in targets or "agents-md" not in targets:
        return out

    # agentic_context_root lane (agents-md machines that also run claude-code)
    root = paths.get("agentic_context_root")
    if root:
        root = str(root).rstrip("/")
        for slug, proj in sorted(reg.projects.items()):
            out += _repo_specs(slug, proj, f"{root}/Projects/{slug}")

    return out


# ── agentic-graph: the deployed project tree (the deployed project-tree design) ───
def _plan_graph_tree(reg: Registry, machine_name: str, paths: dict) -> list[Output]:
    """Materialize the Agentic Context tree from the knowledge graph, on Claude Code
    environments only:

        <agentic_context_root>/AGENTS.md                       roster: every Project + desc
        <agentic_context_root>/Projects/<slug>/AGENTS.md          lightweight doc index
        <agentic_context_root>/Projects/<slug>/AGENTS_DETAILS.md  detailed doc reference

    The index/details split keeps the harness's always-loaded prompt tiny. All three files
    are GENERATED and non-adoptable (drift_policy
    "generated"): regenerated from registry/graph/ every deploy, in-place edits overwritten
    by design — they have no registry partial to route an edit back to. Repo auto-clone
    into Projects/<slug>/ is handled separately (plan_clones).
    """
    machine = reg.machines[machine_name]
    root = (paths or {}).get("agentic_context_root")
    # gate: a harness environment (claude-code target) that opts in via the path key,
    # and at least one project graph to render.
    if not root or "claude-code" not in machine.get("targets", []) or not reg.graphs:
        return []
    from . import graph as graphmod
    root = str(root).rstrip("/")

    # Example sample projects step aside once the user supplies their own (overlay) projects
    # — the same guard the assistant tree applies, so the graph roster never lists samples
    # on a configured fleet. On a fresh clone the set is empty and examples render.
    suppressed = _suppressed_examples(reg)
    active_graphs = {slug: g for slug, g in reg.graphs.items() if slug not in suppressed}

    def _generated(deploy_path: str, content: str) -> Output:
        return Output(
            target="agentic-graph", kind="text", deploy_path=deploy_path,
            dist_rel=f"agentic-graph/{safe_rel(deploy_path)}",
            content=content, drift_policy="generated", sources=[])

    # This tree fires on ANY claude-code machine that sets agentic_context_root, whether
    # or not agents-md/mitos-agent is also present (the gate above is claude-code + the path
    # key alone — see the docstring). Org skills deploy only when `mitos-agent` is literally
    # a target, so the org routing line must key off that, not off reaching this tree.
    org_routing = deploys_org_content(machine)
    outputs: list[Output] = [
        _generated(f"{root}/AGENTS.md",
                   graphmod.roster_markdown(list(active_graphs.values())))]
    for slug, pg in sorted(active_graphs.items()):
        base = f"{root}/Projects/{slug}"
        proj = reg.projects.get(slug) or {}
        agents_path = f"{base}/AGENTS.md"
        # full document context inline (no details file); repos cloned beside this file
        # render as the generated `## Navigation` roster inside _project_node_regions
        prose_src, prose = _project_prose(reg, proj, "agents-md")
        gen_body = _project_doc_block(
            reg, proj, pg, graphmod.project_full_markdown,
            level=2 if prose_src else 1,
            emit_heading=_connection_emit(proj, prose),
            org_routing=org_routing)
        regions = _project_node_regions(proj, prose_src, prose, gen_body)
        if prose_src:
            # prose (protected) interleaved with the generated nav + doc regions
            outputs.append(_mixed_doc_output(
                "agentic-graph", agents_path, regions, prose_src, "protect"))
        else:
            # no human prose for this project → the file is wholly generated
            outputs.append(_generated(agents_path, render.plain_document(
                [(s, b.rstrip("\n")) for s, b in regions if b.strip()])))
    return outputs


# ── helpers ──────────────────────────────────────────────────────────────────
def _suppressed_examples(reg: Registry) -> set[str]:
    """Slugs of `example: true` sample projects to hide once the user supplies their own.

    Mirrors the machine guard in cmd_compile: shipped examples step aside as soon as real
    (overlay) content exists, so they never pollute a configured fleet. A fresh clone with no
    overlay projects renders them for the quick-start. Driven off `_is_local` (any overlay
    project present), not off graphs — so an overlay project without a graph still suppresses.
    """
    if not any(p.get("_is_local") for p in reg.projects.values()):
        return set()
    return {slug for slug, p in reg.projects.items() if p.get("example")}


def _sections(reg: Registry, source_rels: list[str], target: str) -> list[tuple[str, str]]:
    """Resolve registry-relative partial paths to (source, body) sections, honoring
    each partial's audience for this target."""
    out: list[tuple[str, str]] = []
    for rel in source_rels:
        p = reg.partial(rel)
        if p.visible_to(target):
            out.append((rel, p.body))
    return out


def _strip_reg(path: str) -> str:
    return path.split("registry/", 1)[-1]


def _multi(sections: list[tuple[str, str]]) -> list:
    """Per-section breakdown to record in the lockfile, only when a document is fed by
    more than one partial (single-source files route trivially in adopt)."""
    return list(sections) if len(sections) > 1 else []


def _mixed_doc_output(target: str, deploy_path: str, regions: list[tuple[str, str]],
                      prose_src: str, drift_policy: str) -> "Output":
    """One AGENTS.md interleaving user prose with machine-generated regions.

    `regions` is the ordered (source, body) list — prose regions carry the partial's rel,
    generated ones a `render.GENERATED_*` label — so adopt routes only the prose back to
    its partial and drift detection protects only the prose, while every generated region
    regenerates on each deploy. No marker is written into the file (invariant #5); the
    split lives in the lockfile. The file is `protect` (its prose is the user's), but its
    generated regions are never captured as drift (see commands.classify_output).

    A partial may appear in MORE THAN ONE region — a project node's prose is split around
    the generated `## Navigation` repo roster, which has to sit near the top to satisfy the
    reserved-section order. `render.split_live_sections` returns ordered pairs (not a
    source-keyed map) precisely so those regions survive the round trip; `route_into_registry`
    rejoins them before writing back."""
    regions = [(src, body.rstrip("\n")) for src, body in regions if body.strip()]
    return Output(
        target=target, kind="text", deploy_path=deploy_path,
        dist_rel=f"{target}/{safe_rel(deploy_path)}",
        content=render.plain_document(regions), drift_policy=drift_policy,
        sources=[prose_src], section_bodies=regions)


def _split_prose_for_nav(prose: str) -> tuple[str, str, bool]:
    """Split a project's prose at the insertion point for its generated repo roster:
    `(head, tail, prose_opened_navigation)`.

    - Prose HAS a `## Navigation` section -> head ends with that section's authored
      routing text, tail is everything from the next `##` on. The roster attaches beneath
      the author's own prose (heading suppressed), mirroring how a curated connection
      section receives the document map.
    - Prose has NO `## Navigation` -> head is everything before the first `##` (the H1 and
      its description), tail is the rest, and the roster emits its own `## Navigation`
      heading there — first among the reserved sections, as the taxonomy requires.
    - Prose has no `##` at all -> the whole body is head and the roster follows it.
    """
    lines = prose.split("\n")
    nav_at = next((i for i, ln in enumerate(lines)
                   if re.match(r"^##\s+Navigation\s*$", ln)), None)
    if nav_at is not None:
        end = next((i for i in range(nav_at + 1, len(lines))
                    if lines[i].startswith("## ")), len(lines))
        return "\n".join(lines[:end]), "\n".join(lines[end:]), True
    first_h2 = next((i for i, ln in enumerate(lines) if ln.startswith("## ")), len(lines))
    return "\n".join(lines[:first_h2]), "\n".join(lines[first_h2:]), False


def _project_node_regions(proj: dict, prose_src: str | None, prose: str,
                          gen_body: str) -> list[tuple[str, str]]:
    """The ordered region list for a project node: prose head, the generated `## Navigation`
    repo roster, prose tail, then the generated document block. Any empty region is dropped
    by `_mixed_doc_output`, so a project with no repos (or no prose) degrades to exactly the
    shape it had before the roster existed."""
    repos = [(dirname, description)
             for _url, dirname, description in _project_repo_entries(proj)]
    if not prose_src:
        # wholly generated node: the roster still leads, above the document block
        nav = render.navigation_block(repos)
        return [(render.GENERATED_NAV, nav), (render.GENERATED_SECTION, gen_body)]
    head, tail, prose_opened_nav = _split_prose_for_nav(prose)
    nav = render.navigation_block(repos, emit_heading=not prose_opened_nav)
    return [(prose_src, head), (render.GENERATED_NAV, nav), (prose_src, tail),
            (render.GENERATED_SECTION, gen_body)]


def _doc_store_heading(reg: Registry, proj: dict) -> str | None:
    """The connection-section title for a project's generated document block: the bound
    store's STABLE label `<Name> (`key`)` (render.connection_label) — the same heading the
    operating root's connection block uses, so SOUL/skills reference one name. None (→
    "<name> — Documents" fallback) when the project has no store, an unknown one, or more
    than one (a multi-store project's per-store headings come from `_project_doc_block`
    instead — this single label only makes sense for exactly one store)."""
    stores = document_stores(proj.get("document_store"))
    if len(stores) != 1:
        return None
    label = render.connection_label(reg.servers.get("servers") or {}, stores[0])
    return label[0] if label else None


def _connection_emit(proj: dict, prose_text: str) -> bool:
    """Whether the generated document block emits its own `## <Name> (`key`)` heading. True
    unless the project's prose already opened that connection section — detected by the
    `` (`<store>`) `` marker an author writes when curating store-folder paths — in which
    case the document map attaches beneath the curated section instead of duplicating it.
    Always True for a multi-store project — curated-prose attach is a single-store nicety;
    `_project_doc_block` always emits its own heading per store."""
    stores = document_stores(proj.get("document_store"))
    if len(stores) != 1 or stores[0] == "none":
        return True
    return f"(`{stores[0]}`)" not in (prose_text or "")


def _project_doc_block(reg: Registry, proj: dict, pg, render_fn, **kwargs) -> str:
    """Render a project's document connection block via one of graph.py's per-project
    renderers (project_index_markdown / project_details_markdown / project_full_markdown),
    looping once per store for a multi-store project — each store gets its own
    `## <Name> (`key`)` section (the render primitive already produces one section per
    call; multi-store just calls it once per store, filtered to that store's documents,
    and concatenates the blocks). A project with 0 or 1 store renders exactly as before:
    one call, the full unfiltered document set, the caller's own `heading`/`emit_heading`
    (curated-prose attach only applies to the single-store case).

    Legacy documents with no store tag are never dropped: when multiple real stores exist,
    any keyless leftover (predating the second store) renders as its own trailing section
    with heading=None (graph.py's "<project name> — Documents" fallback).

    Header taxonomy (invariant #12 — exactly one H1 per file): the caller's `level` is
    honored ONLY for the first store's section; every later section is forced to at least
    level 2. When the caller's level is 1 (this block IS the file's own identity, e.g.
    project_details_markdown's standalone AGENTS_DETAILS.md), the first store's heading
    stays the file's H1 and later stores nest as sibling H2 sections — never two H1s in
    one file. When the caller's level is already 2 (nested under an existing prose H1),
    every store's section renders at that same level, as normal sibling sections."""
    stores = document_stores(proj.get("document_store"))
    if len(stores) <= 1:
        return render_fn(pg, heading=_doc_store_heading(reg, proj), **kwargs)
    from dataclasses import replace as _dc_replace
    servers = reg.servers.get("servers") or {}
    base_level = kwargs.pop("level", 2)
    if "emit_heading" in kwargs:
        kwargs["emit_heading"] = True
    blocks: list[str] = []
    seen: set[str] = set()
    for i, s in enumerate(stores):
        docs = [d for d in pg.documents if d.store == s]
        seen.update(d.drive_id for d in docs)
        label = render.connection_label(servers, s)
        level = base_level if i == 0 else max(base_level, 2)
        blocks.append(render_fn(_dc_replace(pg, documents=docs),
                                heading=(label[0] if label else s),
                                level=level, **kwargs))
    leftover = [d for d in pg.documents if d.drive_id not in seen]
    if leftover:
        level = max(base_level, 2) if stores else base_level
        blocks.append(render_fn(_dc_replace(pg, documents=leftover),
                                heading=None, level=level, **kwargs))
    return "\n\n".join(b.rstrip("\n") for b in blocks) + "\n"


def _project_prose(reg: Registry, proj: dict, audience: str) -> tuple[str | None, str]:
    """A project's human-authored context prose for a target audience: (source_rel, body),
    or (None, "") if the manifest declares no context partial visible to this audience.
    Tries the `assistant` key, then `builder` (the mitos self-hosting key)."""
    ctx = proj.get("context") or {}
    for key in ("assistant", "builder"):
        if key in ctx:
            src_rel = _strip_reg(ctx[key])
            sections = _sections(reg, [src_rel], audience)
            if sections:
                return src_rel, render.plain_document(sections).rstrip("\n")
    return None, ""


# Targets that deploy a `scope: project` skill GLOBALLY, defeating the confinement its scope
# promises. `mitos-agent` is the only one: it writes real files, automatically, machine-wide.
#
# `claude-app` ignores scope too, but it is NOT here, because it deploys nothing — `deploy`
# stages a zip and the last mile is a human uploading it (targets/claude-app.yaml). A staged
# zip is inert, so there is no leak to warn about, and warning anyway left the operator no
# quiet correct state: excluding the skill warned that it was excluded, keeping it warned that
# it leaked, and the only silent configuration was to drop the target from the skill's
# frontmatter — i.e. to give the capability up. See is_manual_skill_target.
SCOPE_IGNORING_SKILL_TARGETS = {"mitos-agent"}


def _declared_deliverables(reg: Registry) -> set[str]:
    """Demand for the return lane: every deliverable term some effort actually asks for.

    Example graphs step aside once real projects exist — the same rule the graph roster
    applies (_suppressed_examples), and for the same reason: a shipped sample must not
    switch the return lane on for a fleet that never opted into it.
    """
    suppressed = _suppressed_examples(reg)
    return {d for slug, pg in (reg.graphs or {}).items() if slug not in suppressed
            for e in pg.efforts for d in e.deliverables}


def _selected_skills(reg: Registry, sk_spec: dict, machine: dict | None = None) -> list:
    """Skills a target receives, for ONE machine. Two layers compose:
    - push: the skill's `targets:` frontmatter declares which tools it is FOR;
    - pull: the machine profile's optional `skills: {<target>: {include:/exclude:}}`
      curates that set in one place (names validated against the registry at load
      time). Curation is a personal, per-box choice, so it lives on the (overlayable)
      machine profile — never on the target spec, which is core and shared by everyone.

    A skill carrying `extends_skill` never deploys standalone — it splices into its
    parent's body at render time only (render.compose_skill_body); shipping it as its
    own duplicate file would clutter every target it targets.

    On top of those two, a third, non-curatable gate: a skill declaring
    `requires_server:` is dropped unless this machine declares that server in its
    `document_store:`. A skill that is nothing but instructions for one MCP server's
    tools is noise — or worse, a dangling instruction — on a box where that server was
    never wired, and a brand-new coding-harness user should not have to hand-write an
    `exclude:` list to keep the maintainer's workspace skills off their machine.

    A fourth gate, non-curatable for the same reason: a skill declaring `delivers:` is
    dropped unless some effort in the registry declares that deliverable
    (_declared_deliverables). It is the exact inverse of _undelivered_warnings — that
    reports demand with no supply, this stops shipping supply with no demand. A procedure
    for an artifact nothing asks for is not inert: every harness pays for it in the skill
    roster of every session, which is what put seven return-lane skills on a laptop that
    runs one coding harness and nothing that reads a return record.

    It keys off the REGISTRY, not this machine, and that distinction is load-bearing: a
    coding-only box whose records a Mitos Agent elsewhere harvests still receives them
    (render._machine_value's `returns_root` fallback exists for exactly that box). A gate
    on `mitos-agent` being a target HERE would have deleted that configuration.

    **A MANUAL target takes no curation** (`is_manual_skill_target`): staging a zip is not
    deploying it, so the pile is a menu and the operator picks from it at upload time. Curating
    the menu buys nothing and costs the choice — a skill filtered out here is one they cannot
    upload later without a registry edit and a redeploy. The `requires_server:` gate still
    applies: which MCP connections a box has is a fact about the box, not a preference, and a
    skill that is nothing but instructions for a server this machine never wired is a dangling
    instruction whether a human uploaded it or the compiler wrote it. Rejected at load time
    (loader) so a curation list here cannot quietly do nothing.
    """
    tgt = sk_spec["include_target"]
    manual = is_manual_skill_target({"skills": sk_spec})
    curation = {} if manual else (((machine or {}).get("skills") or {}).get(tgt) or {})
    include = curation.get("include")
    exclude = set(curation.get("exclude") or [])
    stores = set(document_stores((machine or {}).get("document_store")))
    declared = _declared_deliverables(reg)
    return [s for s in reg.skills.values()
            if tgt in s.targets
            and not s.frontmatter.get("extends_skill")
            and (s.requires_server is None or s.requires_server in stores)
            and (s.delivers is None or s.delivers in declared)
            and (include is None or s.name in include)
            and s.name not in exclude]


def skill_deploy_warnings(reg: Registry, machine_name: str) -> list[str]:
    """Loud diagnostics for skills that are compatible with a target (their own
    `targets:` frontmatter says so) but don't end up deployed there for this machine —
    filtered out by this machine's curation, dropped because their `requires_server:`
    connection isn't wired here, or landing on a scope-ignoring target while marked
    `scope: project` (its confinement guarantee doesn't hold there). Warn-only: nothing
    here changes what deploys, it only surfaces filters that were previously silent.

    The `delivers:` gate (_declared_deliverables) is deliberately NOT reported: unlike the
    three above it is the DEFAULT state — a fresh clone declares no deliverables — so a line
    here would fire on every deploy of a correct configuration, and the only way to silence
    it would be to declare work you do not do. The reverse direction stays loud in
    _undelivered_warnings, where the gap is real.

    A MANUAL target (`is_manual_skill_target`) reaches only the `requires_server:` line: it
    takes no curation, and it deploys nothing to leak. Every diagnostic here has to leave the
    operator a configuration that is both correct and quiet — one that fires whatever they do
    is not a diagnostic, it is a standing alarm, and it trains them to stop reading the rest."""
    machine = reg.machines.get(machine_name) or {}
    machine_targets = set(machine.get("targets", []))
    stores = set(document_stores(machine.get("document_store")))
    declared = _declared_deliverables(reg)
    warnings: list[str] = []
    # Every deliverable term this machine can actually satisfy, accumulated across targets:
    # a term is covered if ANY target here deploys a skill declaring it.
    delivered: set[str] = set()
    for tname, tspec in reg.targets.items():
        if tname not in machine_targets:
            continue
        sk_spec = tspec.get("skills")
        if not sk_spec:
            continue
        candidates = {s.name for s in reg.skills.values()
                      if tname in s.targets and not s.frontmatter.get("extends_skill")}
        selected = _selected_skills(reg, sk_spec, machine)
        selected_names = {s.name for s in selected}
        delivered.update(s.delivers for s in selected if s.delivers)
        for name in sorted(candidates - selected_names):
            sk = reg.skills[name]
            req = sk.requires_server
            if req and req not in stores:
                warnings.append(
                    f"skill '{name}' targets '{tname}' but requires the '{req}' "
                    f"connection, which machines/{machine_name}.yaml does not declare "
                    f"(document_store:) — not deployed")
            elif sk.delivers and sk.delivers not in declared:
                continue        # the default state, not a filter — see the docstring
            else:
                warnings.append(
                    f"skill '{name}' targets '{tname}' but is excluded by this machine's "
                    f"curation (skills.{tname} in machines/{machine_name}.yaml)")
        if tname in SCOPE_IGNORING_SKILL_TARGETS:
            for skill in selected:
                if skill.scope == "project":
                    warnings.append(
                        f"skill '{skill.name}' is scope: project but targets "
                        f"'{tname}', which ignores scope and deploys it globally "
                        f"(account-wide/machine-wide, not confined to bound projects)")
    warnings.extend(_undelivered_warnings(reg, machine_name, delivered))
    return warnings


def _undelivered_warnings(reg: Registry, machine_name: str,
                          delivered: set[str]) -> list[str]:
    """An effort declares a deliverable that nothing on this machine knows how to produce.

    The forward contract only means something if a procedure answers it. Without this, an
    effort can declare `deploy-book`, every harness can read the compiled line asking for one,
    and no skill anywhere describes how to write one — a gap discovered months later by the
    deploy book's absence. Warn-only: an effort may legitimately be ahead of its skills, and a
    machine that deploys no skills at all (an agents-md-only box) is not misconfigured.

    Reported once per term with the efforts that want it, not once per effort, so adding one
    missing skill retires exactly one line."""
    wanted: dict[str, list[str]] = {}
    for slug, pg in (reg.graphs or {}).items():
        for e in pg.efforts:
            for d in e.deliverables:
                if d not in delivered:
                    wanted.setdefault(d, []).append(f"{slug}/{e.id}")
    return [f"deliverable '{term}' is declared by {', '.join(sorted(efforts))} but no skill "
            f"deployed to {machine_name} declares 'delivers: {term}' — nothing here knows how "
            f"to produce it"
            for term, efforts in sorted(wanted.items())]


def _skill_resource_outputs(skill, resources: dict, target: str, base_dir: str,
                            drift_policy: str) -> list["Output"]:
    """One Output per skill resource file (examples/*, scripts/*), deployed alongside
    SKILL.md at base_dir. `sources` names the resource's OWN registry-relative path (not
    SKILL.md) so adopt/harvest routes an edited example/script back to the file that
    authored it (R5) — resources merged in from an extension route back to the
    extension's own file, never the parent's."""
    outs: list[Output] = []
    for relpath, res in sorted(resources.items()):
        deploy_path = f"{base_dir.rstrip('/')}/{relpath}"
        outs.append(Output(
            target=target, kind="text", deploy_path=deploy_path,
            dist_rel=f"{target}/{safe_rel(deploy_path)}",
            content=res.text, drift_policy=drift_policy, sources=[res.rel],
            executable=relpath.startswith("scripts/"),
        ))
    return outs


def _local(reg: Registry, machine_name: str, proj: dict) -> str | None:
    """A project's resolved local path on this machine, or None if not present here.
    Relative manifest entries resolve against the machine's `projects_root`."""
    raw = (proj.get("local_path") or {}).get(machine_name)
    if not raw:
        return None
    return resolve_local_path(machine_name, reg.machines[machine_name], raw)


def _gws(reg: Registry, machine_name: str) -> dict | None:
    """The gws server definition with its URL resolved for the consuming machine
    (the server is hosted on the assistant laptop; other machines reach it over LAN).

    None when this machine never declared the connection in its `document_store:` — a
    box with no Google Workspace must not get a gws server spliced into its harness
    config, any more than it gets the gws SKILL.md (_selected_skills). Same signal both
    times: the machine profile states which connections it actually has."""
    if "gws" not in document_stores(reg.machines[machine_name].get("document_store")):
        return None
    server = dict(reg.servers["servers"]["gws"])
    server["url"] = (server.get("urls") or {}).get(machine_name, server["url"])
    return server


def _agent_servers(reg: Registry, machine_name: str) -> dict:
    """Every MCP server this machine's assistant is wired to, keyed by server name — the
    whole `mcp.json` Mitos Agent reads (design §3.1). Generalizes _gws from one hard-coded
    server to the machine's full `document_store:` list, resolving each server's per-machine
    URL the same way. `none`/unset yields {} (no mcp.json). A one-store machine yields
    {"gws": <server>} — identical in effect to what the single-server _gws did."""
    machine = reg.machines[machine_name]
    servers: dict = {}
    for name in document_stores(machine.get("document_store")):
        if name == "none":
            continue
        src = (reg.servers.get("servers") or {}).get(name)
        if not src:
            continue
        server = dict(src)
        server["url"] = (server.get("urls") or {}).get(machine_name, server["url"])
        servers[name] = server
    return servers


# ── agents-md ────────────────────────────────────────────────────────────────
def _plan_agentic_tree_mounts(reg: Registry, machine_name: str) -> list[Output]:
    """Project-mounted operating trees (agentic_tree: on a project manifest) — the
    workstation-side counterpart to a machine's assistant_root mount. Called
    unconditionally from plan_machine (like _plan_graph_tree), deliberately independent
    of whether THIS machine lists agents-md as a target: agents-md is a context format a
    project opts into, not a harness a machine opts into, so one project's mount must not
    require a machine-wide target-list edit (which would also flip is_assistant_tree_machine
    for every OTHER project's co-located AGENTS.md in _plan_claude_code).

    No-op on an agentic (mitos-agent) machine — it already hosts this tree at its machine
    root; a project mount there would be a redundant second reconciliation surface over
    the exact same content."""
    machine = reg.machines[machine_name]
    if hosts_assistant_tree(machine):
        return []
    spec = reg.targets.get("agents-md") or {}
    outputs: list[Output] = []
    for tree in (spec.get("trees") or {}).values():
        if not tree.get("project_mountable"):
            continue
        for slug, proj in sorted(reg.projects.items()):
            subdir = proj.get("agentic_tree")
            if not subdir:
                continue
            local = _local(reg, machine_name, proj)
            if not local:
                continue
            mount_root = f"{local.rstrip('/')}/{subdir}"
            outputs += _emit_tree(reg, machine_name, tree, mount_root, [])
    return outputs


def _emit_tree(reg, machine_name, tree, root, agent_selected_skills) -> list[Output]:
    """Render one agents-md tree at `root` — a machine's tree-root path key, or a
    project's agentic_tree mount inside its own checkout. Mount-point-agnostic: the
    output (Navigation/Workflows/Skills, roster, dynamic branches, per-project doc
    entries) is identical either way, only the deploy root differs.
    """
    machine = reg.machines[machine_name]
    outputs: list[Output] = []
    policy = tree.get("drift_policy", "protect")
    # This tree renders whenever agents-md is a target (the machine-wide assistant_root
    # mount) or a project opts into agentic_tree: (workstation mount, independent of
    # agents-md) — neither requires `mitos-agent`. Org skills deploy only when `mitos-agent`
    # is literally a target, so both the org-domain table and every per-effort routing line
    # below must key off that, not off reaching this tree.
    org_routing = deploys_org_content(machine)

    # Dynamic branches (the dynamic-branches design): any partial matching
    # context/<branch>/AGENTS.md marks <branch> as a user-extensible branch — the
    # only way an overlay user extends this tree without forking
    # targets/agents-md.yaml, which is not overlayable. Discovered before the
    # static-files loop so the root AGENTS.md's generated block can list them.
    reserved = {rf.split("/", 1)[0].lower() for rf in tree["files"] if "/" in rf}
    branches: set[str] = set()
    for logical in reg.partials:
        m = _BRANCH_RE.match(logical)
        if m:
            branches.add(m.group(1))
    for branch in sorted(branches):
        if branch.lower() in reserved:
            raise RegistryError(
                f"context/{branch}/AGENTS.md: branch name {branch!r} collides "
                f"with a reserved top-level entry ({sorted(reserved)}) — choose a "
                f"different folder name under registry/context/")

    # Roster for the generated Project Roster block on Projects/AGENTS.md: exactly
    # the projects that get a Projects/<name>/ folder in this tree — via the
    # ctx-key route (context.<project_context_key>) or the builder route (a
    # builder-context project whose local_path lands under <root>/Projects/, e.g.
    # Mitos self-hosting). Shipped examples suppressed, same as the folders.
    roster_key = tree.get("project_context_key")
    roster: list[dict] = []
    if roster_key:
        _sup = _suppressed_examples(reg)
        proj_prefix = f"{root.rstrip('/')}/Projects/".replace("\\", "/")
        for slug, proj in sorted(reg.projects.items()):
            if slug in _sup:
                continue
            ctx = proj.get("context") or {}
            if roster_key in ctx:
                roster.append(proj)
                continue
            if "builder" in ctx:
                local = _local(reg, machine_name, proj)
                if local and local.replace("\\", "/").rstrip("/").startswith(proj_prefix):
                    roster.append(proj)

    for rel_file, srcs in tree["files"].items():
        sections = _sections(reg, srcs, "agents-md")
        deploy_path = f"{root.rstrip('/')}/{rel_file}"
        # For Projects/AGENTS.md, append the org-domain table (the `## Skills` section)
        # and then the generated Project Roster as ONE <generated> section — in that
        # order so the file follows the reserved section order (Skills before rosters).
        # The table replaces the retired static org-roles.md partial; the roster
        # replaces the hand-written list that used to live in projects-index.md — both
        # always reflect the active registry.
        if rel_file == "Projects/AGENTS.md":
            gen_parts = []
            org_block = (render.org_domain_table(list(reg.skills.values()))
                        if org_routing else "")
            if org_block:
                gen_parts.append(org_block.rstrip("\n"))
            roster_block = render.project_roster_block(roster)
            if roster_block:
                gen_parts.append(roster_block.rstrip("\n"))
            if gen_parts:
                combined_sections = list(sections) + [
                    (render.GENERATED_SECTION, "\n\n".join(gen_parts))]
                outputs.append(Output(
                    target="agents-md", kind="text", deploy_path=deploy_path,
                    dist_rel=f"agents-md/{safe_rel(deploy_path)}",
                    content=render.plain_document(combined_sections),
                    drift_policy=policy,
                    sources=srcs,
                    section_bodies=combined_sections,
                ))
                continue
        # For the tree root AGENTS.md, append connections (this machine's document
        # store), the general-skills catalog, and the dynamic-branches roster — each
        # only when it has content — combined into ONE <generated> section (a second
        # tuple sharing the same GENERATED_SECTION source key would collide in the
        # section-map dict that adopt/split_live_sections builds).
        if rel_file == "AGENTS.md":
            # Reserved section order: `## Skills`, then the connection section, then the
            # dynamic-branches roster (navigation appendix).
            gen_parts = []
            sk_block = render.skills_block(agent_selected_skills)
            if sk_block:
                gen_parts.append(sk_block.rstrip("\n"))
            conn_block = render.connections_block(
                reg.servers.get("servers") or {}, machine, reg.user)
            if conn_block:
                gen_parts.append(conn_block.rstrip("\n"))
            if branches:
                gen_parts.append(render.dynamic_branches_block(sorted(branches)).rstrip("\n"))
            if gen_parts:
                combined_sections = list(sections) + [
                    (render.GENERATED_SECTION, "\n\n".join(gen_parts))]
                outputs.append(Output(
                    target="agents-md", kind="text", deploy_path=deploy_path,
                    dist_rel=f"agents-md/{safe_rel(deploy_path)}",
                    content=render.plain_document(combined_sections),
                    drift_policy=policy, sources=srcs,
                    section_bodies=combined_sections,
                ))
                continue
        # For the Assistant branch root, append this machine's connections as a
        # <generated> section — the one-shot workflow's own "what's wired up" note.
        if rel_file == "Assistant/AGENTS.md":
            conn_block = render.connections_block(
                reg.servers.get("servers") or {}, machine, reg.user)
            if conn_block:
                combined_sections = list(sections) + [
                    (render.GENERATED_SECTION, conn_block.rstrip("\n"))]
                outputs.append(Output(
                    target="agents-md", kind="text", deploy_path=deploy_path,
                    dist_rel=f"agents-md/{safe_rel(deploy_path)}",
                    content=render.plain_document(combined_sections),
                    drift_policy=policy, sources=srcs,
                    section_bodies=combined_sections,
                ))
                continue
        outputs.append(Output(
            target="agents-md", kind="text", deploy_path=deploy_path,
            dist_rel=f"agents-md/{safe_rel(deploy_path)}",
            content=render.plain_document(sections), drift_policy=policy,
            sources=srcs, section_bodies=_multi(sections),
        ))

    # Emit every file under each discovered branch (not just its AGENTS.md) at
    # <root>/<branch>/<relative-path-after-branch>.
    for branch in sorted(branches):
        prefix_key = f"context/{branch}/"
        for logical in sorted(reg.partials):
            if not logical.startswith(prefix_key):
                continue
            sub_rel = logical[len(prefix_key):]
            sections = _sections(reg, [logical], "agents-md")
            if not sections:
                continue
            deploy_path = f"{root.rstrip('/')}/{branch}/{sub_rel}"
            outputs.append(Output(
                target="agents-md", kind="text", deploy_path=deploy_path,
                dist_rel=f"agents-md/{safe_rel(deploy_path)}",
                content=render.plain_document(sections), drift_policy=policy,
                sources=[logical], section_bodies=_multi(sections),
            ))

    # Dynamic per-project entries: generate "Projects/<name>/AGENTS.md" for each
    # project whose manifest declares context.<project_context_key>.
    # When the project also has a knowledge graph, append the titles-index and
    # emit a companion AGENTS_DETAILS.md (non-adoptable, drift_policy generated).
    ctx_key = tree.get("project_context_key")
    if ctx_key:
        from . import graph as graphmod
        suppressed = _suppressed_examples(reg)
        # On a mitos-agent operating tree, plan_clones drops each repo checkout beside this
        # project node (<assistant_root>/Projects/<name>/<basename>), so the generated
        # `## Navigation` repo roster is real here — the harness resolves a checkout from the
        # node's own directory. On an agentic_tree mount (a claude-code workstation, no
        # mitos-agent target) the checkouts land beside the MOUNT, not inside it, so no roster.
        clone_siblings = "mitos-agent" in machine.get("targets", [])
        for slug, proj in sorted(reg.projects.items()):
            if slug in suppressed:
                continue
            ctx = proj.get("context") or {}
            if ctx_key not in ctx:
                continue
            src_rel = _strip_reg(ctx[ctx_key])
            name = proj.get("name", slug)
            rel_file = f"Projects/{name}/AGENTS.md"
            sections = _sections(reg, [src_rel], "agents-md")
            if not sections:
                continue
            deploy_path = f"{root.rstrip('/')}/{rel_file}"
            pg = reg.graphs.get(slug)
            prose_body = render.plain_document(sections).rstrip("\n")
            # Lightweight titles index (generated); full per-document detail lives in the
            # companion AGENTS_DETAILS.md. Empty when the project has no graph.
            gen_body = _project_doc_block(
                reg, proj, pg, graphmod.project_index_markdown, level=2,
                emit_heading=_connection_emit(proj, prose_body),
                org_routing=org_routing) if pg else ""
            if clone_siblings and _project_repo_entries(proj):
                # prose interleaved with the generated nav roster + doc index
                regions = _project_node_regions(proj, src_rel, prose_body, gen_body)
                outputs.append(_mixed_doc_output(
                    "agents-md", deploy_path, regions, src_rel, policy))
            elif pg:
                outputs.append(_mixed_doc_output(
                    "agents-md", deploy_path,
                    [(src_rel, prose_body), (render.GENERATED_SECTION, gen_body)],
                    src_rel, policy))
            else:
                outputs.append(Output(
                    target="agents-md", kind="text", deploy_path=deploy_path,
                    dist_rel=f"agents-md/{safe_rel(deploy_path)}",
                    content=render.plain_document(sections),
                    drift_policy=policy,
                    sources=[src_rel], section_bodies=_multi(sections),
                ))
            if pg:
                details_path = (f"{root.rstrip('/')}/Projects/{name}/"
                                f"{graphmod.DETAILS_FILENAME}")
                outputs.append(Output(
                    target="agents-md", kind="text", deploy_path=details_path,
                    dist_rel=f"agents-md/{safe_rel(details_path)}",
                    content=_project_doc_block(
                        reg, proj, pg, graphmod.project_details_markdown, level=1,
                        org_routing=org_routing),
                    drift_policy="generated", sources=[],
                ))
    return outputs


def _plan_agents_md(reg, machine_name, spec, paths) -> list[Output]:
    outputs: list[Output] = []
    machine = reg.machines[machine_name]
    # General-purpose skills selected for THIS machine's Mitos Agent deployment (the same
    # selection _plan_mitos_agent uses) — feeds the operating root's generated Skills block.
    # Empty on a machine with no mitos-agent target: skill files never physically land there,
    # so listing them would be a claim the machine can't back up.
    agent_sk_spec = (reg.targets.get("mitos-agent") or {}).get("skills") or {}
    agent_selected_skills = (
        _selected_skills(reg, agent_sk_spec, machine)
        if deploys_assistant_skills(reg, machine) else [])
    # Org skills deploy only when `mitos-agent` is literally a target — agents-md alone
    # (this whole function's gate) is not sufficient. Threaded into the builder-context
    # branch below; _emit_tree computes its own copy for the tree branch above.
    org_routing = deploys_org_content(machine)
    # tree: assistant — the machine mount (root_key resolves in this machine's paths).
    # Project mounts (agentic_tree: on a project manifest) are a SEPARATE, unconditional
    # call site (_plan_agentic_tree_mounts, below) — deliberately not gated on "agents-md"
    # being one of THIS machine's targets, since agents-md is a context format a project
    # opts into, not a harness a machine opts into. Keeping it here would tie a project's
    # own mount to a machine-wide target-list edit that also reshapes every OTHER
    # project's co-located AGENTS.md on that machine (is_assistant_tree_machine in
    # _plan_claude_code) — a blast radius far wider than one project's own field.
    for tree_name, tree in (spec.get("trees") or {}).items():
        root_key = tree["root_key"]
        if root_key in paths:
            outputs += _emit_tree(reg, machine_name, tree, paths[root_key], agent_selected_skills)

    # per-project root AGENTS.md (builder context)
    pa = spec.get("project_agents")
    if pa:
        reg_root = _reg_root_norm(reg)
        # On a machine that also deploys mitos-agent, SOUL.md (the system prompt) already
        # carries the identity partials — repeating them at the top of every project
        # AGENTS.md would tax context with prose the model has on every request. Drop
        # them here; agents-md-only machines (no SOUL.md) keep the full persona header.
        pa_sources = pa["sources"]
        if hosts_assistant_tree(machine):
            pa_sources = [s for s in pa_sources if not str(s).startswith("identity/")]
        for slug, proj in reg.projects.items():
            local = _local(reg, machine_name, proj)
            ctx = proj.get("context") or {}
            if not local or "builder" not in ctx:
                continue
            local = local.rstrip("/")
            local_norm = local.replace("\\", "/").rstrip("/")
            srcs = [(_strip_reg(ctx["builder"]) if s == "{project.context.builder}"
                     else s) for s in pa_sources]
            sections = _sections(reg, srcs, "agents-md")
            deploy_path = f"{local}/{pa.get('filename', 'AGENTS.md')}"
            policy = pa.get("drift_policy", "protect")
            pg = reg.graphs.get(slug)
            # A project may ALSO have an agentic_tree mount — two AGENTS.md-shaped files
            # then legitimately coexist (this one: doc/repo index; the mount: a full
            # operating tree). Name the split rather than leave a reader to guess.
            at_subdir = proj.get("agentic_tree")
            if pg and local_norm != reg_root:
                # A builder-context project (e.g. Mitos self-hosting) still gets the same
                # lightweight titles-index + companion AGENTS_DETAILS.md that every other
                # project in this agents-md tree gets (the ctx_key branch above) — the bound
                # document store's connection heading + document titles in AGENTS.md, full
                # per-document detail on demand — so declaring `builder` instead of
                # `assistant` context never costs it its knowledge-graph docs.
                from . import graph as graphmod
                prose_body = render.plain_document(sections).rstrip("\n")
                gen_body = _project_doc_block(
                    reg, proj, pg, graphmod.project_index_markdown, level=2,
                    emit_heading=_connection_emit(proj, prose_body),
                    org_routing=org_routing)
                if at_subdir:
                    gen_body = gen_body.rstrip("\n") + "\n\n" + render.agentic_tree_note_block(at_subdir)
                combined_sections = list(sections) + [
                    (render.GENERATED_SECTION, gen_body.rstrip("\n"))]
                outputs.append(Output(
                    target="agents-md", kind="text", deploy_path=deploy_path,
                    dist_rel=f"agents-md/{safe_rel(deploy_path)}",
                    content=render.plain_document(combined_sections),
                    drift_policy=policy, sources=srcs,
                    section_bodies=combined_sections,
                ))
                details_path = f"{local}/{graphmod.DETAILS_FILENAME}"
                outputs.append(Output(
                    target="agents-md", kind="text", deploy_path=details_path,
                    dist_rel=f"agents-md/{safe_rel(details_path)}",
                    content=_project_doc_block(
                        reg, proj, pg, graphmod.project_details_markdown, level=1,
                        org_routing=org_routing),
                    drift_policy="generated", sources=[],
                ))
                continue
            if at_subdir:
                note = render.agentic_tree_note_block(at_subdir)
                combined_sections = list(sections) + [(render.GENERATED_SECTION, note.rstrip("\n"))]
                outputs.append(Output(
                    target="agents-md", kind="text", deploy_path=deploy_path,
                    dist_rel=f"agents-md/{safe_rel(deploy_path)}",
                    content=render.plain_document(combined_sections),
                    drift_policy=policy, sources=srcs,
                    section_bodies=combined_sections,
                ))
                continue
            outputs.append(Output(
                target="agents-md", kind="text", deploy_path=deploy_path,
                dist_rel=f"agents-md/{safe_rel(deploy_path)}",
                content=render.plain_document(sections),
                drift_policy=policy, sources=srcs,
                section_bodies=_multi(sections),
            ))
    return outputs


# ── mitos-agent ──────────────────────────────────────────────────────────────
def _plan_mitos_agent(reg, machine_name, spec, paths) -> list[Output]:
    outputs: list[Output] = []
    home = paths.get("assistant_root")   # the single install root (SOUL/skills/mcp + the tree)
    # SOUL.md
    cf = spec["context_file"]
    if home:
        sections = _sections(reg, cf["sources"], "mitos-agent")
        deploy_path = f"{home.rstrip('/')}/{cf['filename']}"
        outputs.append(Output(
            target="mitos-agent", kind="text", deploy_path=deploy_path,
            dist_rel=f"mitos-agent/{safe_rel(deploy_path)}",
            content=render.plain_document(sections),
            drift_policy=cf.get("drift_policy", "protect"), sources=cf["sources"],
            section_bodies=_multi(sections),
        ))
    # skills
    sk = spec["skills"]
    if home:
        for skill in _selected_skills(reg, sk, reg.machines[machine_name]):
            sub = sk["subdir"].format(category=skill.category, name=skill.name)
            base_dir = f"{home.rstrip('/')}/{sub}"
            policy = sk.get("drift_policy", "harvest")
            body = render.compose_skill_body(reg, skill)
            resources = render.compose_skill_resources(reg, skill)
            deploy_path = f"{base_dir}/SKILL.md"
            outputs.append(Output(
                target="mitos-agent", kind="text", deploy_path=deploy_path,
                dist_rel=f"mitos-agent/{safe_rel(deploy_path)}",
                content=render.render_skill(skill, "mitos-agent", body=body),
                drift_policy=policy, sources=[skill.rel],
            ))
            outputs += _skill_resource_outputs(skill, resources, "mitos-agent", base_dir, policy)
    # mcp.json — a WHOLE file Mitos owns (invariant #7 does not apply to this lane), carrying
    # every wired store keyed by server name so §5.4's resolve(id, store) can pick the right
    # server for a multi-store project. No surgical merge, no owned_keys.
    mcp = spec["mcp"]
    servers = _agent_servers(reg, machine_name)
    if home and servers:
        deploy_path = f"{home.rstrip('/')}/{mcp['filename']}"
        outputs.append(Output(
            target="mitos-agent", kind="json", deploy_path=deploy_path,
            dist_rel=f"mitos-agent/{safe_rel(deploy_path)}",
            content=_json(render.mitos_agent_mcp_config(servers)),
            drift_policy=mcp.get("drift_policy", "protect"), lane="connections",
            sources=["connections/servers.yaml"],
        ))
    return outputs


# ── claude-code ──────────────────────────────────────────────────────────────
def _plan_claude_code(reg, machine_name, spec, paths) -> list[Output]:
    outputs: list[Output] = []
    machine = reg.machines[machine_name]
    is_assistant_tree_machine = "agents-md" in machine.get("targets", [])
    cf = spec["context_file"]
    stub_map = cf.get("stub_import") or {}
    reg_root = _reg_root_norm(reg)
    suppressed = _suppressed_examples(reg) if not is_assistant_tree_machine else set()

    for slug, proj in reg.projects.items():
        local = _local(reg, machine_name, proj)
        if not local:
            continue
        local = local.rstrip("/")
        local_norm = local.replace("\\", "/").rstrip("/")

        pg = reg.graphs.get(slug) if not is_assistant_tree_machine and slug not in suppressed else None

        if pg and local_norm != reg_root:
            # Non-agents-md workstation + project has a knowledge graph: emit a self-contained
            # AGENTS.md (full doc context + prose header) and a stub CLAUDE.md → @AGENTS.md.
            # The prose is resolved under the agents-md audience so that shared context
            # partials (audience: [mitos-agent, agents-md]) are visible without requiring a
            # separate claude-code audience declaration on each partial.
            from . import graph as graphmod
            prose_src, prose = _project_prose(reg, proj, "agents-md")
            gen_body = _project_doc_block(
                reg, proj, pg, graphmod.project_full_markdown,
                level=2 if prose_src else 1,
                emit_heading=_connection_emit(proj, prose),
                # Org skills target mitos-agent only (never claude-code) — a non-mitos-agent
                # workstation checkout must not tell the agent to load one that was
                # never deployed here.
                org_routing=False)
            # A project may ALSO have an agentic_tree mount — two AGENTS.md-shaped files
            # then legitimately coexist (this one: the doc/repo index; the mount: a full
            # operating tree). Name the split rather than leave a reader to guess.
            at_subdir = proj.get("agentic_tree")
            if at_subdir:
                gen_body = gen_body.rstrip("\n") + "\n\n" + render.agentic_tree_note_block(at_subdir)
            agents_path = f"{local}/AGENTS.md"
            regions = _project_node_regions(proj, prose_src, prose, gen_body)
            if prose_src:
                outputs.append(_mixed_doc_output(
                    "claude-code", agents_path, regions, prose_src, "protect"))
            else:
                outputs.append(Output(
                    target="claude-code", kind="text", deploy_path=agents_path,
                    dist_rel=f"claude-code/{safe_rel(agents_path)}",
                    content=render.plain_document(
                        [(s, b.rstrip("\n")) for s, b in regions if b.strip()]),
                    drift_policy="generated", sources=[],
                ))
            claude_path = f"{local}/{cf['filename']}"
            outputs.append(Output(
                target="claude-code", kind="text",
                deploy_path=claude_path,
                dist_rel=f"claude-code/{safe_rel(claude_path)}",
                content=render.stub_document("@AGENTS.md"),
                drift_policy=cf.get("drift_policy", "protect"), sources=[],
            ))
        else:
            # agents-md machines, no-graph projects, or suppressed examples: emit CLAUDE.md
            # only (existing behaviour — stub_map or inlined repo context or skip).
            deploy_path = f"{local}/{cf['filename']}"
            section_bodies: list = []
            ctx = proj.get("context") or {}
            if slug in stub_map and is_assistant_tree_machine:
                # the stub @AGENTS.md is valid only because the agents-md target deploys
                # that AGENTS.md at this same root on this machine.
                content, sources = render.stub_document(stub_map[slug]), []
            elif slug in stub_map:
                # claude-code-only machine: no AGENTS.md is generated here, so a stub
                # import would dangle. Inline the project's builder context into a
                # self-contained CLAUDE.md instead, so AGENTS/CLAUDE never split.
                builder = ctx.get("builder")
                if not builder:
                    continue  # nothing to inline → no CLAUDE.md
                srcs = [(_strip_reg(builder) if s == "{project.context.repo}" else s)
                        for s in cf["sources"]]
                sections = _sections(reg, srcs, "claude-code")
                content, sources, section_bodies = (
                    render.plain_document(sections), srcs, _multi(sections))
            else:
                if "repo" not in ctx:
                    continue  # no code-structure context → no CLAUDE.md
                srcs = [(_strip_reg(ctx["repo"]) if s == "{project.context.repo}" else s)
                        for s in cf["sources"]]
                sections = _sections(reg, srcs, "claude-code")
                content, sources, section_bodies = (
                    render.plain_document(sections), srcs, _multi(sections))
            outputs.append(Output(
                target="claude-code", kind="text", deploy_path=deploy_path,
                dist_rel=f"claude-code/{safe_rel(deploy_path)}",
                content=content, drift_policy=cf.get("drift_policy", "protect"),
                sources=sources, section_bodies=section_bodies,
            ))
    # scope: global (default) skills targeting claude-code deploy once to the personal
    # skills directory (claude_code_skills, ~/.claude/skills/) — available in every
    # project on this machine, no per-project binding needed. Mirrors antigravity's
    # antigravity_skills global surface (_plan_antigravity).
    sk = spec.get("skills") or {}
    global_skills_dir = paths.get(sk.get("deploy_to_key", "claude_code_skills"))
    if global_skills_dir and sk:
        for skill in _selected_skills(reg, sk, reg.machines[machine_name]):
            if skill.scope == "project":
                continue
            base_dir = f"{global_skills_dir.rstrip('/')}/{skill.name}"
            policy = sk.get("drift_policy", "harvest")
            body = render.compose_skill_body(reg, skill)
            resources = render.compose_skill_resources(reg, skill)
            deploy_path = f"{base_dir}/SKILL.md"
            outputs.append(Output(
                target="claude-code", kind="text", deploy_path=deploy_path,
                dist_rel=f"claude-code/{safe_rel(deploy_path)}",
                content=render.render_skill(skill, "claude-code", body=body),
                drift_policy=policy, sources=[skill.rel],
            ))
            outputs += _skill_resource_outputs(skill, resources, "claude-code",
                                               base_dir, policy)
    # per-project skills and prompts (the per-project binding design): each
    # project's manifest names the assets it uses; they deploy to that project's checkout.
    # A skill/prompt is reused across projects by naming it in each manifest, never
    # copied. Only scope: project skills are read here — a scope: global skill already
    # deploys everywhere above, so a stray manifest listing for it is simply inert.
    pr = spec.get("prompts") or {}
    sk_subdir = sk.get("subdir", ".claude/skills/{name}")
    pr_subdir = pr.get("subdir", ".claude/commands")
    for slug, proj in reg.projects.items():
        local = _local(reg, machine_name, proj)
        if not local:
            continue
        local = local.rstrip("/")
        bound_skills = set(proj.get("skills") or [])
        for skill in reg.skills.values():
            if ("claude-code" not in skill.targets or skill.name not in bound_skills
                    or skill.scope != "project"
                    or skill.frontmatter.get("extends_skill")):
                continue
            base_dir = f"{local}/{sk_subdir.format(name=skill.name)}"
            policy = sk.get("drift_policy", "harvest")
            body = render.compose_skill_body(reg, skill)
            resources = render.compose_skill_resources(reg, skill)
            deploy_path = f"{base_dir}/SKILL.md"
            outputs.append(Output(
                target="claude-code", kind="text", deploy_path=deploy_path,
                dist_rel=f"claude-code/{safe_rel(deploy_path)}",
                content=render.render_skill(skill, "claude-code", body=body),
                drift_policy=policy, sources=[skill.rel],
            ))
            outputs += _skill_resource_outputs(skill, resources, "claude-code",
                                               base_dir, policy)
        for pname in sorted(proj.get("prompts") or []):
            prompt = reg.prompts.get(pname)
            if prompt is None or "claude-code" not in prompt.targets:
                continue
            deploy_path = f"{local}/{pr_subdir.rstrip('/')}/{prompt.name}.md"
            outputs.append(Output(
                target="claude-code", kind="text", deploy_path=deploy_path,
                dist_rel=f"claude-code/{safe_rel(deploy_path)}",
                content=render.render_prompt(prompt, "claude-code"),
                drift_policy=pr.get("drift_policy", "harvest"), sources=[prompt.rel],
            ))
    return outputs


# ── antigravity ────────────────────────────────────────────────────────────────
def _plan_antigravity(reg, machine_name, spec, paths) -> list[Output]:
    outputs: list[Output] = []
    alias = spec["server_alias"]
    gws = _gws(reg, machine_name)
    cfg_dir = paths.get("antigravity_config")
    if cfg_dir and gws:
        mc = spec["mcp_config"]
        deploy_path = f"{cfg_dir.rstrip('/')}/{mc['filename']}"
        outputs.append(Output(
            target="antigravity", kind="json", deploy_path=deploy_path,
            dist_rel=f"antigravity/{safe_rel(deploy_path)}",
            content=_json(render.antigravity_mcp_config(gws, alias)),
            drift_policy=mc.get("drift_policy", "protect"), lane="connections",
            sources=["connections/servers.yaml"],
        ))
        # config.json is the TOOL's file — surgical merge (invariant #7): a third party's
        # config file, unlike Mitos Agent's own whole-file mcp.json.
        # The compiler owns only its alias's mcp(...) entries inside the allow list;
        perm = spec["permissions"]
        deploy_path = f"{cfg_dir.rstrip('/')}/{perm['filename']}"
        outputs.append(Output(
            target="antigravity", kind="json_merge", deploy_path=deploy_path,
            dist_rel=f"antigravity/{safe_rel(deploy_path)}",
            content=_json(render.antigravity_permission_grants(gws, alias)),
            drift_policy=perm.get("drift_policy", "protect"), lane="connections",
            sources=["connections/servers.yaml"],
            owned_keys=["userSettings.globalPermissionGrants.allow"],
            owned_prefix=f"mcp({alias}/", target_file=deploy_path,
        ))
    # Skills — Antigravity follows the directory-based Agent Skills standard, so this
    # mirrors _plan_claude_code exactly: <dir>/<name>/SKILL.md with extension-composed
    # body plus supporting-file outputs. Global scope deploys to the machine's
    # antigravity_skills path (~/.gemini/config/skills/); project scope deploys only
    # into bound checkouts at <local_path>/.agents/skills/ (the workspace convention).
    sk = spec.get("skills") or {}
    skills_dir = paths.get(sk.get("deploy_to_key", "antigravity_skills"))
    if skills_dir and sk:
        policy = sk.get("drift_policy", "harvest")
        for skill in _selected_skills(reg, sk, reg.machines[machine_name]):
            if skill.scope == "project":
                continue
            base_dir = f"{skills_dir.rstrip('/')}/{sk['subdir'].format(name=skill.name)}"
            body = render.compose_skill_body(reg, skill)
            resources = render.compose_skill_resources(reg, skill)
            deploy_path = f"{base_dir}/SKILL.md"
            outputs.append(Output(
                target="antigravity", kind="text", deploy_path=deploy_path,
                dist_rel=f"antigravity/{safe_rel(deploy_path)}",
                content=render.render_skill(skill, "antigravity", body=body),
                drift_policy=policy, sources=[skill.rel],
            ))
            outputs += _skill_resource_outputs(skill, resources, "antigravity",
                                               base_dir, policy)
        for slug, proj in reg.projects.items():
            local = _local(reg, machine_name, proj)
            if not local:
                continue
            local = local.rstrip("/")
            bound_skills = set(proj.get("skills") or [])
            for skill in reg.skills.values():
                if (skill.name not in bound_skills or "antigravity" not in skill.targets
                        or skill.scope != "project"
                        or skill.frontmatter.get("extends_skill")):
                    continue
                base_dir = f"{local}/.agents/skills/{sk['subdir'].format(name=skill.name)}"
                body = render.compose_skill_body(reg, skill)
                resources = render.compose_skill_resources(reg, skill)
                deploy_path = f"{base_dir}/SKILL.md"
                outputs.append(Output(
                    target="antigravity", kind="text", deploy_path=deploy_path,
                    dist_rel=f"antigravity/{safe_rel(deploy_path)}",
                    content=render.render_skill(skill, "antigravity", body=body),
                    drift_policy=policy, sources=[skill.rel],
                ))
                outputs += _skill_resource_outputs(skill, resources, "antigravity",
                                                   base_dir, policy)
    return outputs


def _json(data: dict) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"
