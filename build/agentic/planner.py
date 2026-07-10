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
from .loader import Registry, RegistryError, resolve_local_path, _repo_basename

# A dynamically discovered agentic branch: any partial whose logical key matches
# context/<branch>/AGENTS.md marks <branch> as a user-extensible branch (see
# _plan_agents_md's dynamic-branch discovery — the only way an overlay user extends the
# assistant tree without forking targets/agents-md.yaml, which is not overlayable).
_BRANCH_RE = re.compile(r"^context/([^/]+)/AGENTS\.md$")


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


def plan_machine(reg: Registry, machine_name: str) -> list[Output]:
    machine = reg.machines.get(machine_name)
    if machine is None:
        raise KeyError(f"unknown machine: {machine_name}")
    paths = machine.get("paths", {})
    outputs: list[Output] = []
    for target in machine.get("targets", []):
        spec = reg.targets[target]
        if target == "agents-md":
            outputs += _plan_agents_md(reg, machine_name, spec, paths)
        elif target == "hermes":
            outputs += _plan_hermes(reg, machine_name, spec, paths)
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
    # (e.g. hermes's config.yaml carries both the mcp: and settings: merges) — but their
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

    return [_expand_output(reg, o, paths) for o in outputs]


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


def _expand_output(reg: Registry, o: Output, machine_paths: dict | None = None) -> Output:
    """Personalization pass (the dynamic-context-enhancements design): substitute the
    fixed `{{user_*}}` placeholders — plus the machine-scoped `{{project_root}}` —
    in every markdown/text output and skill-zip member.
    Tool-owned merge configs (yaml_merge/json_merge) and env templates are excluded —
    they are machine wiring, not prose the model reads, and the .local/ env overlay
    must never flow through this pass (see io/secrets invariant)."""
    def _x(text: str) -> str:
        return render.expand_placeholders(reg, text, machine_paths)
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
    if mc and dest:
        alias = spec["server_alias"]
        gws = _gws(reg, machine_name)
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


def _reg_root_norm(reg: Registry) -> str:
    """Normalised, slash-terminated registry root for guard comparisons."""
    return str(reg.root).replace("\\", "/").rstrip("/")


def plan_clones(reg: Registry, machine_name: str) -> list[CloneSpec]:
    """Repos to clone on Claude Code environments, absent-only / non-destructive.

    Two lanes:
    - agentic_context_root (Hermes + claude-code machines): clone into
      <agentic_context_root>/Projects/<slug>/<basename> — the separate context tree.
    - local_path (non-Hermes claude-code machines, i.e. agents-md NOT in targets):
      clone into <local_path>/<basename> — co-located with the project workspace.

    The deploy executor clones each only when its checkout is ABSENT — never pulling,
    resetting, or deleting an existing tree (design rule #8). Planning-only machines
    (no claude-code target) get nothing.
    """
    machine = reg.machines.get(machine_name) or {}
    targets = machine.get("targets", [])
    if "claude-code" not in targets:
        return []

    out: list[CloneSpec] = []

    # agentic_context_root lane (Hermes machines that also run claude-code)
    root = (machine.get("paths") or {}).get("agentic_context_root")
    if root:
        root = str(root).rstrip("/")
        for slug, proj in sorted(reg.projects.items()):
            for repo in _project_repos(proj):
                dest = f"{root}/Projects/{slug}/{_repo_basename(repo)}"
                out.append(CloneSpec(slug=slug, repo=repo, dest=dest))

    # local_path lane (workstation machines without agents-md)
    if "agents-md" not in targets:
        reg_root = _reg_root_norm(reg)
        suppressed = _suppressed_examples(reg)
        for slug, proj in sorted(reg.projects.items()):
            if slug in suppressed:
                continue
            repos = _project_repos(proj)
            if not repos:
                continue
            local = _local(reg, machine_name, proj)
            if not local:
                continue
            local_norm = local.replace("\\", "/").rstrip("/")
            if local_norm == reg_root:
                continue  # guard: never clone into the Mitos repo itself
            for repo in repos:
                dest = f"{local_norm}/{_repo_basename(repo)}"
                out.append(CloneSpec(slug=slug, repo=repo, dest=dest))

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

    outputs: list[Output] = [
        _generated(f"{root}/AGENTS.md",
                   graphmod.roster_markdown(list(active_graphs.values())))]
    for slug, pg in sorted(active_graphs.items()):
        base = f"{root}/Projects/{slug}"
        proj = reg.projects.get(slug) or {}
        agents_path = f"{base}/AGENTS.md"
        # full document context inline + repos cloned beside this file (no details file)
        repos = [(r, _repo_basename(r)) for r in _project_repos(proj)]
        prose_src, prose = _project_prose(reg, proj, "agents-md")
        gen_body = graphmod.project_full_markdown(
            pg, repos or None, _doc_store_heading(reg, proj),
            level=2 if prose_src else 1,
            emit_heading=_connection_emit(proj, prose))
        if prose_src:
            # prose header (protected) + generated doc block in one AGENTS.md
            outputs.append(_mixed_doc_output(
                "agentic-graph", agents_path, prose, gen_body, prose_src, "protect"))
        else:
            # no human prose for this project → the file is wholly generated
            outputs.append(_generated(agents_path, gen_body))
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


def _mixed_doc_output(target: str, deploy_path: str, prose_body: str, gen_body: str,
                      prose_src: str, drift_policy: str) -> "Output":
    """One AGENTS.md that is user prose FOLLOWED BY a machine-generated document block.

    The two are recorded as `section_bodies` with the generated half tagged
    `render.GENERATED_SECTION` — so adopt routes only the prose back to its partial and
    drift detection protects only the prose, while the doc block regenerates every deploy.
    No marker is written into the file (invariant #5); the split lives in the lockfile.
    The file is `protect` (its prose is the user's), but its generated tail is never
    captured as drift (see commands.classify_output)."""
    sections = [(prose_src, prose_body.rstrip("\n")),
                (render.GENERATED_SECTION, gen_body.rstrip("\n"))]
    return Output(
        target=target, kind="text", deploy_path=deploy_path,
        dist_rel=f"{target}/{safe_rel(deploy_path)}",
        content=render.plain_document(sections), drift_policy=drift_policy,
        sources=[prose_src], section_bodies=sections)


def _doc_store_heading(reg: Registry, proj: dict) -> str | None:
    """The connection-section title for a project's generated document block: the bound
    store's STABLE label `<Name> (`key`)` (render.connection_label) — the same heading the
    operating root's connection block uses, so SOUL/skills reference one name. None (→
    "<name> — Documents" fallback) when the project has no store or an unknown one."""
    label = render.connection_label(reg.servers.get("servers") or {},
                                    proj.get("document_store"))
    return label[0] if label else None


def _connection_emit(proj: dict, prose_text: str) -> bool:
    """Whether the generated document block emits its own `## <Name> (`key`)` heading. True
    unless the project's prose already opened that connection section — detected by the
    `` (`<store>`) `` marker an author writes when curating store-folder paths — in which
    case the document map attaches beneath the curated section instead of duplicating it."""
    ds = (proj.get("document_store") or "").strip()
    if not ds or ds == "none":
        return True
    return f"(`{ds}`)" not in (prose_text or "")


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


# hermes and claude-app have no project-scoped surface (loader.PROJECT_SCOPE_CAPABLE_
# TARGETS is the other two) — they IGNORE `scope: project` and always deploy globally.
# Kept in sync with loader.KNOWN_TARGETS - loader.PROJECT_SCOPE_CAPABLE_TARGETS.
SCOPE_IGNORING_SKILL_TARGETS = {"hermes", "claude-app"}


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
    """
    tgt = sk_spec["include_target"]
    curation = ((machine or {}).get("skills") or {}).get(tgt) or {}
    include = curation.get("include")
    exclude = set(curation.get("exclude") or [])
    return [s for s in reg.skills.values()
            if tgt in s.targets
            and not s.frontmatter.get("extends_skill")
            and (include is None or s.name in include)
            and s.name not in exclude]


def skill_deploy_warnings(reg: Registry, machine_name: str) -> list[str]:
    """Loud diagnostics for skills that are compatible with a target (their own
    `targets:` frontmatter says so) but don't end up deployed there for this machine —
    either filtered out by this machine's curation, or landing on a scope-ignoring
    target while marked `scope: project` (its confinement guarantee doesn't hold
    there). Warn-only: nothing here changes what deploys, it only surfaces filters
    that were previously silent."""
    machine = reg.machines.get(machine_name) or {}
    machine_targets = set(machine.get("targets", []))
    warnings: list[str] = []
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
        for name in sorted(candidates - selected_names):
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
    return warnings


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


def _gws(reg: Registry, machine_name: str) -> dict:
    """The gws server definition with its URL resolved for the consuming machine
    (the server is hosted on the Hermes laptop; other machines reach it over LAN)."""
    server = dict(reg.servers["servers"]["gws"])
    server["url"] = (server.get("urls") or {}).get(machine_name, server["url"])
    return server


# ── agents-md ────────────────────────────────────────────────────────────────
def _plan_agentic_tree_mounts(reg: Registry, machine_name: str) -> list[Output]:
    """Project-mounted operating trees (agentic_tree: on a project manifest) — the
    workstation-side counterpart to a machine's assistant_root mount. Called
    unconditionally from plan_machine (like _plan_graph_tree), deliberately independent
    of whether THIS machine lists agents-md as a target: agents-md is a context format a
    project opts into, not a harness a machine opts into, so one project's mount must not
    require a machine-wide target-list edit (which would also flip is_hermes_machine for
    every OTHER project's co-located AGENTS.md in _plan_claude_code).

    No-op on an agentic (hermes) machine — it already hosts this tree at its machine
    root; a project mount there would be a redundant second reconciliation surface over
    the exact same content."""
    machine = reg.machines[machine_name]
    if "hermes" in machine.get("targets", []):
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


def _emit_tree(reg, machine_name, tree, root, hermes_selected_skills) -> list[Output]:
    """Render one agents-md tree at `root` — a machine's tree-root path key, or a
    project's agentic_tree mount inside its own checkout. Mount-point-agnostic: the
    output (Navigation/Workflows/Skills, roster, dynamic branches, per-project doc
    entries) is identical either way, only the deploy root differs.
    """
    machine = reg.machines[machine_name]
    outputs: list[Output] = []
    policy = tree.get("drift_policy", "protect")

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
            org_block = render.org_domain_table(list(reg.skills.values()))
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
            sk_block = render.skills_block(hermes_selected_skills)
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
            if pg:
                # prose header (protected) + lightweight titles index (generated);
                # full per-document detail lives in the companion AGENTS_DETAILS.md.
                prose_body = render.plain_document(sections).rstrip("\n")
                outputs.append(_mixed_doc_output(
                    "agents-md", deploy_path, prose_body,
                    graphmod.project_index_markdown(
                        pg, _doc_store_heading(reg, proj),
                        emit_heading=_connection_emit(proj, prose_body)),
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
                    content=graphmod.project_details_markdown(
                        pg, _doc_store_heading(reg, proj)),
                    drift_policy="generated", sources=[],
                ))
    return outputs


def _plan_agents_md(reg, machine_name, spec, paths) -> list[Output]:
    outputs: list[Output] = []
    machine = reg.machines[machine_name]
    # General-purpose skills selected for THIS machine's Hermes deployment (the same
    # selection _plan_hermes uses) — feeds the operating root's generated Skills block.
    # Empty on a machine with no hermes target: skill files never physically land there,
    # so listing them would be a claim the machine can't back up.
    hermes_sk_spec = (reg.targets.get("hermes") or {}).get("skills") or {}
    hermes_selected_skills = (
        _selected_skills(reg, hermes_sk_spec, machine)
        if "hermes" in machine.get("targets", []) and hermes_sk_spec else [])
    # tree: assistant — the machine mount (root_key resolves in this machine's paths).
    # Project mounts (agentic_tree: on a project manifest) are a SEPARATE, unconditional
    # call site (_plan_agentic_tree_mounts, below) — deliberately not gated on "agents-md"
    # being one of THIS machine's targets, since agents-md is a context format a project
    # opts into, not a harness a machine opts into. Keeping it here would tie a project's
    # own mount to a machine-wide target-list edit that also reshapes every OTHER
    # project's co-located AGENTS.md on that machine (is_hermes_machine in
    # _plan_claude_code) — a blast radius far wider than one project's own field.
    for tree_name, tree in (spec.get("trees") or {}).items():
        root_key = tree["root_key"]
        if root_key in paths:
            outputs += _emit_tree(reg, machine_name, tree, paths[root_key], hermes_selected_skills)

    # per-project root AGENTS.md (builder context)
    pa = spec.get("project_agents")
    if pa:
        reg_root = _reg_root_norm(reg)
        # On a machine that also deploys hermes, SOUL.md (the system prompt) already
        # carries the identity partials — repeating them at the top of every project
        # AGENTS.md would tax context with prose the model has on every request. Drop
        # them here; agents-md-only machines (no SOUL.md) keep the full persona header.
        pa_sources = pa["sources"]
        if "hermes" in machine.get("targets", []):
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
                # project in this Hermes tree gets (the ctx_key branch above) — the bound
                # document store's connection heading + document titles in AGENTS.md, full
                # per-document detail on demand — so declaring `builder` instead of
                # `assistant` context never costs it its knowledge-graph docs.
                from . import graph as graphmod
                heading = _doc_store_heading(reg, proj)
                prose_body = render.plain_document(sections).rstrip("\n")
                gen_body = graphmod.project_index_markdown(
                    pg, heading, emit_heading=_connection_emit(proj, prose_body))
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
                    content=graphmod.project_details_markdown(pg, heading),
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


# ── hermes ───────────────────────────────────────────────────────────────────
def _plan_hermes(reg, machine_name, spec, paths) -> list[Output]:
    outputs: list[Output] = []
    home = paths.get("hermes_home")
    # SOUL.md
    cf = spec["context_file"]
    if home:
        sections = _sections(reg, cf["sources"], "hermes")
        deploy_path = f"{home.rstrip('/')}/{cf['filename']}"
        outputs.append(Output(
            target="hermes", kind="text", deploy_path=deploy_path,
            dist_rel=f"hermes/{safe_rel(deploy_path)}",
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
                target="hermes", kind="text", deploy_path=deploy_path,
                dist_rel=f"hermes/{safe_rel(deploy_path)}",
                content=render.render_skill(skill, "hermes", body=body),
                drift_policy=policy, sources=[skill.rel],
            ))
            outputs += _skill_resource_outputs(skill, resources, "hermes", base_dir, policy)
    # mcp merge
    mcp = spec["mcp"]
    cfg = paths.get(mcp["file_key"]) or paths.get("hermes_config")
    if cfg:
        block = {"mcp_servers": render.hermes_mcp_block(_gws(reg, machine_name),
                                                        mcp["server_alias"])}
        outputs.append(Output(
            target="hermes", kind="yaml_merge", deploy_path=cfg,
            dist_rel=f"hermes/{safe_rel(cfg)}.mcp_servers.yaml",
            content=yaml.safe_dump(block, sort_keys=False, allow_unicode=True),
            drift_policy=mcp.get("drift_policy", "protect"), lane="connections",
            sources=["connections/servers.yaml"], owned_keys=mcp["owned_keys"],
            target_file=cfg,
        ))
    # settings merge — leaf-path ownership of a few machine-declared runtime knobs.
    # Unlike the mcp merge above (whole-key ownership of mcp_servers), this owns
    # individual leaf paths inside otherwise Hermes/user-owned blocks (terminal.*,
    # memory.*, ...), so sibling settings (terminal.timeout, agent.max_turns, ...)
    # are left untouched. Declared after the mcp block so a `next(kind == yaml_merge)`
    # lookup still finds the mcp block first.
    st = spec.get("settings")
    if st:
        cfg = paths.get(st["file_key"]) or paths.get("hermes_config")
        machine = reg.machines[machine_name]
        block = render.hermes_settings_block(paths, machine.get("hermes_settings") or {})
        if cfg and block:
            outputs.append(Output(
                target="hermes", kind="yaml_merge", deploy_path=cfg,
                dist_rel=f"hermes/{safe_rel(cfg)}.settings.yaml",
                content=yaml.safe_dump(block, sort_keys=False, allow_unicode=True),
                drift_policy=st.get("drift_policy", "protect"), lane="connections",
                sources=[f"machines/{machine_name}.yaml"], owned_keys=st["owned_keys"],
                target_file=cfg,
            ))
    return outputs


# ── claude-code ──────────────────────────────────────────────────────────────
def _plan_claude_code(reg, machine_name, spec, paths) -> list[Output]:
    outputs: list[Output] = []
    machine = reg.machines[machine_name]
    is_hermes_machine = "agents-md" in machine.get("targets", [])
    cf = spec["context_file"]
    stub_map = cf.get("stub_import") or {}
    reg_root = _reg_root_norm(reg)
    suppressed = _suppressed_examples(reg) if not is_hermes_machine else set()

    for slug, proj in reg.projects.items():
        local = _local(reg, machine_name, proj)
        if not local:
            continue
        local = local.rstrip("/")
        local_norm = local.replace("\\", "/").rstrip("/")

        pg = reg.graphs.get(slug) if not is_hermes_machine and slug not in suppressed else None

        if pg and local_norm != reg_root:
            # Non-Hermes workstation + project has a knowledge graph: emit a self-contained
            # AGENTS.md (full doc context + prose header) and a stub CLAUDE.md → @AGENTS.md.
            # The prose is resolved under the agents-md audience so that shared context
            # partials (audience: [hermes, agents-md]) are visible without requiring a
            # separate claude-code audience declaration on each partial.
            from . import graph as graphmod
            repos = [(r, _repo_basename(r)) for r in _project_repos(proj)]
            prose_src, prose = _project_prose(reg, proj, "agents-md")
            gen_body = graphmod.project_full_markdown(
                pg, repos or None, _doc_store_heading(reg, proj),
                level=2 if prose_src else 1,
                emit_heading=_connection_emit(proj, prose))
            # A project may ALSO have an agentic_tree mount — two AGENTS.md-shaped files
            # then legitimately coexist (this one: the doc/repo index; the mount: a full
            # operating tree). Name the split rather than leave a reader to guess.
            at_subdir = proj.get("agentic_tree")
            if at_subdir:
                gen_body = gen_body.rstrip("\n") + "\n\n" + render.agentic_tree_note_block(at_subdir)
            agents_path = f"{local}/AGENTS.md"
            if prose_src:
                outputs.append(_mixed_doc_output(
                    "claude-code", agents_path, prose, gen_body, prose_src, "protect"))
            else:
                outputs.append(Output(
                    target="claude-code", kind="text", deploy_path=agents_path,
                    dist_rel=f"claude-code/{safe_rel(agents_path)}",
                    content=gen_body, drift_policy="generated", sources=[],
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
            # Hermes machines, no-graph projects, or suppressed examples: emit CLAUDE.md
            # only (existing behaviour — stub_map or inlined repo context or skip).
            deploy_path = f"{local}/{cf['filename']}"
            section_bodies: list = []
            ctx = proj.get("context") or {}
            if slug in stub_map and is_hermes_machine:
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
    # per-project skills, agents, and prompts (the per-project binding design): each
    # project's manifest names the assets it uses; they deploy to that project's checkout.
    # A skill/agent/prompt is reused across projects by naming it in each manifest, never
    # copied. Only scope: project skills are read here — a scope: global skill already
    # deploys everywhere above, so a stray manifest listing for it is simply inert.
    ag = spec.get("agents") or {}
    pr = spec.get("prompts") or {}
    sk_subdir = sk.get("subdir", ".claude/skills/{name}")
    ag_subdir = ag.get("subdir", ".claude/agents")
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
        for aname in sorted(proj.get("agents") or []):
            agent = reg.agents[aname]
            deploy_path = f"{local}/{ag_subdir.rstrip('/')}/{agent.name}.md"
            outputs.append(Output(
                target="claude-code", kind="text", deploy_path=deploy_path,
                dist_rel=f"claude-code/{safe_rel(deploy_path)}",
                content=render.render_agent(agent, "claude-code"),
                drift_policy=ag.get("drift_policy", "harvest"), sources=[agent.rel],
            ))
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
    if cfg_dir:
        mc = spec["mcp_config"]
        deploy_path = f"{cfg_dir.rstrip('/')}/{mc['filename']}"
        outputs.append(Output(
            target="antigravity", kind="json", deploy_path=deploy_path,
            dist_rel=f"antigravity/{safe_rel(deploy_path)}",
            content=_json(render.antigravity_mcp_config(gws, alias)),
            drift_policy=mc.get("drift_policy", "protect"), lane="connections",
            sources=["connections/servers.yaml"],
        ))
        # config.json is the TOOL's file — surgical merge, like Hermes config.yaml.
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
