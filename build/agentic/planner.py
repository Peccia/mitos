"""Turn the registry + a machine profile into a concrete list of Output files.

An Output is one file the compiler will materialize: rendered content, where it deploys
(POSIX path, possibly ~-rooted), its drift policy, and the registry sources that fed it
(so `adopt` can route edits back). yaml_merge outputs carry the owned-keys block to
splice into a tool's own config file at deploy time.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

import yaml

from . import render
from .io import safe_rel
from .loader import Registry, RegistryError, resolve_local_path


def _selected_prompts(reg: Registry, pr_spec: dict) -> list:
    """Prompts a target receives: those whose `targets:` includes this target."""
    tgt = pr_spec["include_target"]
    return [p for p in reg.prompts.values() if tgt in p.targets]


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
            outputs += _plan_claude_code(reg, machine_name, spec)
        elif target == "gemini":
            outputs += _plan_gemini(reg, machine_name, spec, paths)
        elif target == "claude-ai":
            outputs += _plan_claude_ai(reg, spec, paths)
        elif target == "claude-desktop":
            outputs += _plan_claude_desktop(reg, machine_name, spec, paths)
    outputs += _plan_env(reg, machine_name, paths)
    outputs += _plan_graph_tree(reg, machine_name, paths)

    # Validate output path collisions (prevent two targets/rules from deploying to the same file)
    seen: dict[str, Output] = {}
    is_win = machine.get("os") == "windows"
    for o in outputs:
        p = o.deploy_path.lower() if is_win else o.deploy_path
        if p in seen:
            other = seen[p]
            raise RegistryError(
                f"machine {machine_name}: output path collision on '{o.deploy_path}'. "
                f"Target '{o.target}' ({o.kind}) and target '{other.target}' ({other.kind}) "
                f"both plan to write to the same path. Check your machine profile and target configurations.")
        seen[p] = o

    return outputs


# ── claude-ai ────────────────────────────────────────────────────────────────
def _plan_claude_ai(reg, spec, paths) -> list[Output]:
    """Artifact deploys: claude.ai (web + Desktop) has no filesystem the compiler can
    reach, so deploy STAGES ready-to-upload skill zips (<name>/SKILL.md inside) at the
    machine's staging path. The upload is manual; a `pending` zip after a registry
    edit is the re-upload reminder."""
    outputs: list[Output] = []
    sk = spec.get("skills") or {}
    staging = paths.get(sk.get("deploy_to_key", "claude_ai_staging"))
    if not sk or not staging:
        return outputs
    for skill in _selected_skills(reg, sk):
        deploy_path = f"{staging.rstrip('/')}/{skill.name}.zip"
        outputs.append(Output(
            target="claude-ai", kind="zip", deploy_path=deploy_path,
            dist_rel=f"claude-ai/{safe_rel(deploy_path)}",
            content=render.render_skill(skill, "claude-ai"),
            drift_policy=sk.get("drift_policy", "protect"),
            sources=[skill.rel], zip_member=f"{skill.name}/SKILL.md",
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
    dest: str          # POSIX checkout dir under <agentic_context_root>/Projects/<slug>/


def _repo_basename(repo: str) -> str:
    """The checkout directory name for a git URL: the last path segment, minus `.git`.
    Handles scp-style (`git@host:owner/name.git`) and URL (`https://…/name.git`) forms."""
    s = repo.strip().rstrip("/")
    if s.endswith(".git"):
        s = s[:-4]
    # split on both ':' (scp form) and '/' so owner/name and host:owner/name both work
    return s.replace(":", "/").rsplit("/", 1)[-1] or "repo"


def plan_clones(reg: Registry, machine_name: str) -> list[CloneSpec]:
    """Repos to clone into the Agentic Context tree, on Claude Code environments only.

    One per project that declares a non-empty `repo:`. The deploy executor clones each
    only when its checkout is ABSENT — never pulling, resetting, or deleting an existing
    tree (design rule #8). Planning-only machines (no claude-code target) get nothing.
    """
    machine = reg.machines.get(machine_name) or {}
    root = (machine.get("paths") or {}).get("agentic_context_root")
    if not root or "claude-code" not in machine.get("targets", []):
        return []
    root = str(root).rstrip("/")
    out: list[CloneSpec] = []
    for slug, proj in sorted(reg.projects.items()):
        repo = str(proj.get("repo") or "").strip()
        if not repo:
            continue
        dest = f"{root}/Projects/{slug}/{_repo_basename(repo)}"
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

    def _generated(deploy_path: str, content: str) -> Output:
        return Output(
            target="agentic-graph", kind="text", deploy_path=deploy_path,
            dist_rel=f"agentic-graph/{safe_rel(deploy_path)}",
            content=content, drift_policy="generated", sources=[])

    outputs: list[Output] = [
        _generated(f"{root}/AGENTS.md",
                   graphmod.roster_markdown(list(reg.graphs.values())))]
    for slug, pg in sorted(reg.graphs.items()):
        base = f"{root}/Projects/{slug}"
        outputs.append(_generated(f"{base}/AGENTS.md",
                                  graphmod.project_index_markdown(pg)))
        outputs.append(_generated(f"{base}/{graphmod.DETAILS_FILENAME}",
                                  graphmod.project_details_markdown(pg)))
    return outputs


# ── helpers ──────────────────────────────────────────────────────────────────
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


def _selected_skills(reg: Registry, sk_spec: dict) -> list:
    """Skills a target receives. Two layers compose:
    - push: the skill's `targets:` frontmatter declares which tools it is FOR;
    - pull: the target spec's optional `include:`/`exclude:` curates that set in one
      place (names validated against the registry at load time).
    """
    tgt = sk_spec["include_target"]
    include = sk_spec.get("include")
    exclude = set(sk_spec.get("exclude") or [])
    return [s for s in reg.skills.values()
            if tgt in s.targets
            and (include is None or s.name in include)
            and s.name not in exclude]


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
def _plan_agents_md(reg, machine_name, spec, paths) -> list[Output]:
    outputs: list[Output] = []
    # tree: assistant
    for tree_name, tree in (spec.get("trees") or {}).items():
        root_key = tree["root_key"]
        if root_key not in paths:
            continue  # this machine doesn't host the tree
        root = paths[root_key]
        policy = tree.get("drift_policy", "protect")
        for rel_file, srcs in tree["files"].items():
            sections = _sections(reg, srcs, "agents-md")
            deploy_path = f"{root.rstrip('/')}/{rel_file}"
            outputs.append(Output(
                target="agents-md", kind="text", deploy_path=deploy_path,
                dist_rel=f"agents-md/{safe_rel(deploy_path)}",
                content=render.plain_document(sections), drift_policy=policy,
                sources=srcs, section_bodies=_multi(sections),
            ))
        # Dynamic per-project entries: generate "Projects/<name>/AGENTS.md" for each
        # project whose manifest declares context.<project_context_key>.
        ctx_key = tree.get("project_context_key")
        if ctx_key:
            for slug, proj in sorted(reg.projects.items()):
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
                outputs.append(Output(
                    target="agents-md", kind="text", deploy_path=deploy_path,
                    dist_rel=f"agents-md/{safe_rel(deploy_path)}",
                    content=render.plain_document(sections), drift_policy=policy,
                    sources=[src_rel], section_bodies=_multi(sections),
                ))
    # per-project root AGENTS.md (builder context)
    pa = spec.get("project_agents")
    if pa:
        for slug, proj in reg.projects.items():
            local = _local(reg, machine_name, proj)
            ctx = proj.get("context") or {}
            if not local or "builder" not in ctx:
                continue
            srcs = [(_strip_reg(ctx["builder"]) if s == "{project.context.builder}"
                     else s) for s in pa["sources"]]
            sections = _sections(reg, srcs, "agents-md")
            deploy_path = f"{local.rstrip('/')}/{pa.get('filename', 'AGENTS.md')}"
            outputs.append(Output(
                target="agents-md", kind="text", deploy_path=deploy_path,
                dist_rel=f"agents-md/{safe_rel(deploy_path)}",
                content=render.plain_document(sections),
                drift_policy=pa.get("drift_policy", "protect"), sources=srcs,
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
        for skill in _selected_skills(reg, sk):
            sub = sk["subdir"].format(category=skill.category, name=skill.name)
            deploy_path = f"{home.rstrip('/')}/{sub}/SKILL.md"
            outputs.append(Output(
                target="hermes", kind="text", deploy_path=deploy_path,
                dist_rel=f"hermes/{safe_rel(deploy_path)}",
                content=render.render_skill(skill, "hermes"),
                drift_policy=sk.get("drift_policy", "harvest"), sources=[skill.rel],
            ))
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
    return outputs


# ── claude-code ──────────────────────────────────────────────────────────────
def _plan_claude_code(reg, machine_name, spec) -> list[Output]:
    outputs: list[Output] = []
    cf = spec["context_file"]
    stub_map = cf.get("stub_import") or {}
    for slug, proj in reg.projects.items():
        local = _local(reg, machine_name, proj)
        if not local:
            continue
        deploy_path = f"{local.rstrip('/')}/{cf['filename']}"
        section_bodies: list = []
        if slug in stub_map:
            content, sources = render.stub_document(stub_map[slug]), []
        else:
            ctx = proj.get("context") or {}
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
    # per-project skills, agents, and prompts (the per-project binding design): each
    # project's manifest names the assets it uses; they deploy to that project's checkout.
    # A skill/agent/prompt is reused across projects by naming it in each manifest, never copied.
    sk = spec.get("skills") or {}
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
            if "claude-code" not in skill.targets or skill.name not in bound_skills:
                continue
            deploy_path = f"{local}/{sk_subdir.format(name=skill.name)}/SKILL.md"
            outputs.append(Output(
                target="claude-code", kind="text", deploy_path=deploy_path,
                dist_rel=f"claude-code/{safe_rel(deploy_path)}",
                content=render.render_skill(skill, "claude-code"),
                drift_policy=sk.get("drift_policy", "harvest"), sources=[skill.rel],
            ))
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


# ── gemini ───────────────────────────────────────────────────────────────────
def _plan_gemini(reg, machine_name, spec, paths) -> list[Output]:
    outputs: list[Output] = []
    alias = spec["server_alias"]
    gws = _gws(reg, machine_name)
    cfg_dir = paths.get("gemini_config")
    if cfg_dir:
        mc = spec["mcp_config"]
        deploy_path = f"{cfg_dir.rstrip('/')}/{mc['filename']}"
        outputs.append(Output(
            target="gemini", kind="json", deploy_path=deploy_path,
            dist_rel=f"gemini/{safe_rel(deploy_path)}",
            content=_json(render.gemini_mcp_config(gws, alias)),
            drift_policy=mc.get("drift_policy", "protect"), lane="connections",
            sources=["connections/servers.yaml"],
        ))
        # config.json is the TOOL's file — surgical merge, like Hermes config.yaml.
        # The compiler owns only its alias's mcp(...) entries inside the allow list;
        perm = spec["permissions"]
        deploy_path = f"{cfg_dir.rstrip('/')}/{perm['filename']}"
        outputs.append(Output(
            target="gemini", kind="json_merge", deploy_path=deploy_path,
            dist_rel=f"gemini/{safe_rel(deploy_path)}",
            content=_json(render.gemini_permission_grants(gws, alias)),
            drift_policy=perm.get("drift_policy", "protect"), lane="connections",
            sources=["connections/servers.yaml"],
            owned_keys=["userSettings.globalPermissionGrants.allow"],
            owned_prefix=f"mcp({alias}/", target_file=deploy_path,
        ))
    sk = spec.get("skills") or {}
    prompts_dir = paths.get("antigravity_skills")
    if prompts_dir and sk:
        for skill in _selected_skills(reg, sk):
            fname = sk["subdir"].format(name=skill.name)
            deploy_path = f"{prompts_dir.rstrip('/')}/{fname}"
            outputs.append(Output(
                target="gemini", kind="text", deploy_path=deploy_path,
                dist_rel=f"gemini/{safe_rel(deploy_path)}",
                content=render.render_skill(skill, "gemini"),
                drift_policy=sk.get("drift_policy", "harvest"), sources=[skill.rel],
            ))
    pr = spec.get("prompts") or {}
    if prompts_dir and pr:
        for prompt in _selected_prompts(reg, pr):
            fname = pr["subdir"].format(name=prompt.name)
            deploy_path = f"{prompts_dir.rstrip('/')}/{fname}"
            outputs.append(Output(
                target="gemini", kind="text", deploy_path=deploy_path,
                dist_rel=f"gemini/{safe_rel(deploy_path)}",
                content=render.render_prompt(prompt, "gemini"),
                drift_policy=pr.get("drift_policy", "harvest"), sources=[prompt.rel],
            ))
    return outputs


# ── claude-desktop ────────────────────────────────────────────────────────────
def _plan_claude_desktop(reg, machine_name, spec, paths) -> list[Output]:
    """Write claude_desktop_config.json to the Desktop MCP config path.

    Skipped when the machine profile has no `claude_desktop_config` path key — a
    deliberate opt-in so the target is present in the registry but doesn't deploy
    where the user hasn't configured it yet.
    """
    outputs: list[Output] = []
    mc = spec["mcp_config"]
    dest = paths.get(mc["deploy_to_key"])
    if not dest:
        return outputs
    alias = spec["server_alias"]
    gws = _gws(reg, machine_name)
    outputs.append(Output(
        target="claude-desktop", kind="json", deploy_path=dest,
        dist_rel=f"claude-desktop/{safe_rel(dest)}",
        content=_json(render.claude_desktop_mcp_config(gws, alias)),
        drift_policy=mc.get("drift_policy", "protect"), lane="connections",
        sources=["connections/servers.yaml"],
    ))
    return outputs


def _json(data: dict) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"
