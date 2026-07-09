"""The compiler verbs: compile, deploy, diff, adopt, harvest.

classify_output() is the shared three-way comparison (render vs. lockfile vs. disk).
Deploy-safety invariants (Phase 4a):
  - a drifted file is captured into inbox/ before it is ever overwritten;
  - a machine profile only deploys on a matching OS, unless sandboxed via --root;
  - env outputs merge their .local overlay at deploy time — secrets never enter dist/.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath

import yaml
from ruamel.yaml import YAML

from . import loader, lockfile, render
from .io import (dump_json, expand, safe_rel, sha256, write_bytes, write_text,
                 zip_bytes, zip_bytes_multiple)
from .loader import Registry
from .planner import Output, plan_clones, plan_machine, skill_deploy_warnings

_ruamel = YAML()
_ruamel.preserve_quotes = True
_ruamel.width = 4096


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _local_os() -> str:
    if sys.platform.startswith("win"):
        return "windows"
    return "macos" if sys.platform == "darwin" else "linux"


def _dest(deploy_path: str, root: Path | None) -> Path:
    """Sandbox-aware destination: under --root, mirror the path via safe_rel."""
    return (root / safe_rel(deploy_path)) if root is not None else expand(deploy_path)


def _machine_outputs(reg: Registry, machine: str) -> list[Output]:
    """Plan a machine's outputs with env templates materialized (overlay merged)."""
    return [(_materialize_env(reg, o) if o.kind == "env" else o)
            for o in plan_machine(reg, machine)]


def _materialize_env(reg: Registry, o: Output) -> Output:
    """Merge the `.local/` overlay over an env template, at deploy/diff time only."""
    overlay_text = None
    if o.env_local:
        p = reg.root / o.env_local
        if p.is_file():
            overlay_text = p.read_text(encoding="utf-8")
        else:
            print(f"  warn: no overlay at {o.env_local} — "
                  f"template values only for {o.deploy_path}")
    return replace(o, content=render.merge_env(o.content, overlay_text))


def _payload(o: Output) -> bytes:
    """The exact bytes this output materializes as (zip kinds derive deterministic
    archive bytes from the member text; everything else is UTF-8 text). A zip with
    `zip_members` set (a skill bundling examples/scripts) packs every member; otherwise
    it's the single-member SKILL.md-only zip."""
    if o.kind == "zip":
        if o.zip_members:
            return zip_bytes_multiple(o.zip_members)
        return zip_bytes(o.zip_member, o.content)
    return o.content.encode("utf-8")


def _live_hash(o: Output, dest: Path) -> str:
    """Compute live file hash. To prevent Git's core.autocrlf on Windows from
    falsely flagging plain-text files as drifted, we read all non-zip files as
    text (which automatically normalizes CRLF to LF) before hashing.
    """
    if o.kind == "zip":
        return sha256(dest.read_bytes())
    try:
        # read_text translates CRLF to LF automatically
        return sha256(dest.read_text(encoding="utf-8"))
    except UnicodeDecodeError:
        return sha256(dest.read_bytes())


def _filter_prior_by_machine_paths(reg: Registry, machine_name: str, prior: dict) -> dict:
    """Filter out lockfile entries that do not reside under any of the machine's
    currently configured path roots. This cleans up stale entries when a machine's
    root paths (like projects_root) change drives or locations.
    """
    from .loader import resolve_local_path

    machine_spec = reg.machines.get(machine_name) or {}
    paths = machine_spec.get("paths") or {}
    if not paths:
        return prior

    current_roots: list[Path] = []
    for key, pval in paths.items():
        if pval:
            try:
                resolved = resolve_local_path(machine_name, machine_spec, pval)
                root_path = expand(resolved).resolve()
                current_roots.append(root_path)
            except Exception:
                pass

    filtered = {}
    for p, entry in prior.items():
        try:
            p_resolved = expand(p).resolve()
        except Exception:
            continue

        is_under_root = False
        for root in current_roots:
            try:
                p_resolved.relative_to(root)
                is_under_root = True
                break
            except ValueError:
                pass

        if is_under_root:
            filtered[p] = entry

    return filtered


# ── compile ──────────────────────────────────────────────────────────────────
def cmd_compile(reg: Registry, dist_dir: Path, only_target: str | None = None) -> int:
    if dist_dir.exists():
        shutil.rmtree(dist_dir)
    # Example machines are copy-templates, not a live fleet. Once your overlay defines a real
    # machine they step aside — otherwise they'd render to dist/ and tempt a deploy to real
    # paths. With no real machine yet (a fresh clone), compile them so the quick-start works.
    real = [n for n, m in reg.machines.items() if not m.get("example")]
    machine_names = real or list(reg.machines)
    skipped = [n for n in reg.machines if n not in machine_names]
    total = 0
    for machine_name in machine_names:
        outputs = plan_machine(reg, machine_name)
        if only_target:
            outputs = [o for o in outputs if o.target == only_target]
        manifest = []
        for o in outputs:
            dest = dist_dir / machine_name / o.dist_rel
            payload = _payload(o)
            if o.kind == "zip":
                write_bytes(dest, payload)
            else:
                write_text(dest, o.content)
            manifest.append({
                "deploy_path": o.deploy_path,
                "dist_rel": o.dist_rel,
                "target": o.target,
                "kind": o.kind,
                "drift_policy": o.drift_policy,
                "hash": sha256(payload),
                "sources": o.sources,
                "owned_keys": o.owned_keys,
                "target_file": o.target_file,
            })
        dump_json(dist_dir / machine_name / "manifest.json",
                  {"machine": machine_name, "compiled_at": _now(), "files": manifest})
        print(f"  {machine_name}: {len(outputs)} file(s)")
        total += len(outputs)
    print(f"compiled {total} file(s) into {dist_dir}/")
    if skipped:
        print(f"  (skipped {len(skipped)} example template(s): {', '.join(skipped)} — "
              f"copy one into registry/local/machines/ to make it your own)")
    return 0


# ── classification (shared by deploy / diff / harvest) ───────────────────────
@dataclass
class Status:
    output: Output
    state: str          # create | unchanged | resolved | pending | drift | conflict | merge
    detail: str = ""


def classify_output(reg: Registry, machine: str, o: Output, lock: dict,
                    root: Path | None = None) -> Status:
    if o.kind in ("yaml_merge", "json_merge"):
        tgt = _dest(o.target_file, root)
        return Status(o, "merge", "exists" if tgt.exists() else "target-missing")
    dest = _dest(o.deploy_path, root)
    locked = lockfile.machine_files(lock, machine).get(o.deploy_path)
    new_hash = sha256(_payload(o))
    if not dest.exists():
        return Status(o, "create")
    live_hash = _live_hash(o, dest)
    if locked is None:
        # never deployed by us, but a file is already there
        return Status(o, "unchanged" if live_hash == new_hash else "conflict",
                      "untracked existing file")
    if live_hash == new_hash:
        # convergence: disk already matches the registry (e.g. right after adopt) —
        # never demand --force for a conflict that no longer exists, just relock
        if new_hash == locked.get("source_hash") and live_hash == locked.get("deployed_hash"):
            return Status(o, "unchanged")
        return Status(o, "resolved", "live already matches registry; relock")
    # mixed prose+generated file: protect only the prose, let the generated block (graph
    # regen, or a hand-edit of it) pass through without blocking. Falls back to the
    # whole-file compare below when there is no recorded section base or an edit straddles.
    sa = _section_aware_status(o, locked, dest, new_hash)
    if sa is not None:
        return sa
    drifted = live_hash != locked.get("deployed_hash")
    pending = new_hash != locked.get("source_hash")
    if drifted and pending:
        return Status(o, "conflict", "edited in place AND registry changed")
    if drifted:
        return Status(o, "drift", f"edited in place ({o.drift_policy})")
    if pending:
        return Status(o, "pending", "registry changed")
    return Status(o, "unchanged")


def _section_aware_status(o: Output, locked: dict, dest: Path, new_hash: str) -> Status | None:
    """Drift/pending for an AGENTS.md that is user prose followed by a generated document
    block (tagged render.GENERATED_SECTION). Compares ONLY the prose sections against what
    we deployed, so:
      - a prose edit  -> drift (adoptable, protected);
      - graph regen   -> pending (redeploys, overwrites the block);
      - a hand-edit of the generated block only -> unchanged (silently regenerated).
    Returns None (fall back to whole-file compare) when there's no recorded section base,
    or an edit straddles the prose/generated boundary so it can't be attributed cleanly."""
    if o.kind != "text" or not any(render.is_generated_source(s) for s, _ in o.section_bodies):
        return None
    base = locked.get("sections")
    if not base:
        return None
    base_sections = [(s["source"], s["text"]) for s in base]
    if not any(render.is_generated_source(s) for s, _ in base_sections):
        return None
    carved = render.split_live_sections(base_sections, dest.read_text(encoding="utf-8"))
    if carved is None:
        return None
    deployed_prose = render.join_prose(base_sections)
    live_prose = "\n\n".join(carved.get(s, "") for s, _ in render.prose_sections(base_sections))
    drifted = live_prose != deployed_prose
    pending = new_hash != locked.get("source_hash")
    if drifted and pending:
        return Status(o, "conflict", "prose edited AND registry/graph changed")
    if drifted:
        return Status(o, "drift", f"prose edited ({o.drift_policy})")
    if pending:
        return Status(o, "pending", "registry or graph changed")
    return Status(o, "unchanged")


# ── inbox capture (the moat's intake valve — V2.1 candidate format) ──────────
def _slug(o: Output) -> str:
    # single-source outputs (skills) name the candidate after the source; compiled
    # multi-source documents after their deploy path (the source list would mislead)
    src = (o.sources[0] if len(o.sources) == 1 else o.deploy_path).replace("\\", "/")
    parts = PurePosixPath(src).parts
    base = "-".join(parts[-2:]) if len(parts) >= 2 else parts[-1]
    base = base.rsplit(".", 1)[0] if "." in base.rsplit("/", 1)[-1] else base
    return re.sub(r"[^A-Za-z0-9._-]+", "-", base).strip("-").lower()


def _capture_to_inbox(reg: Registry, machine: str, s: Status, lock: dict,
                      root: Path | None) -> Path:
    """Snapshot a drifted deployed file into inbox/ as a review candidate, BEFORE
    deploy overwrites it. Proposals must survive deploys — nothing vanishes silently.
    """
    o = s.output
    live = _dest(o.deploy_path, root).read_text(encoding="utf-8")
    locked = lockfile.machine_files(lock, machine).get(o.deploy_path) or {}
    ts = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H%MZ")
    inbox = loader.inbox_dir(reg, root)
    folder = inbox / f"{ts}--{machine}--{_slug(o)}"
    n = 2
    while folder.exists():
        folder = inbox / f"{ts}--{machine}--{_slug(o)}-{n}"
        n += 1
    # a mixed prose+generated file routes via `sections` (the generated half maps to no
    # partial), so its single prose source must NOT become a one-path registry_path.
    has_generated = any(render.is_generated_source(s) for s, _ in o.section_bodies)
    meta = {
        # the single registry file this wants to land in — empty for multi-source
        # documents, whose routing comes from `sections` below instead (one path
        # would misdirect an accept into the first partial)
        "registry_path": o.sources[0] if (len(o.sources) == 1 and not has_generated) else "",
        "kind": "drift",
        "source": {"machine": machine, "tool": o.target},
        "base_hash": locked.get("source_hash", ""),
        "deploy_path": o.deploy_path,
        "sources": o.sources,
        "captured_at": _now(),
        "note": f"captured by deploy before overwrite ({s.state}, "
                f"drift_policy={o.drift_policy})",
    }
    if locked.get("sections"):
        # the per-section base recorded at deploy. The lockfile is per-machine and
        # gitignored, but candidates travel via git — embed the base so a multi-source
        # candidate can be split back into its partials at review time on any machine.
        meta["sections"] = locked["sections"]
    write_text(folder / "meta.yaml",
               yaml.safe_dump(meta, sort_keys=False, allow_unicode=True))
    write_text(folder / PurePosixPath(o.deploy_path.replace("\\", "/")).name, live)
    return folder


# ── repo auto-clone (the deployed project-tree design) ───────────────────────────
def _git_clone(repo: str, dest: Path) -> tuple[int, str]:
    """Shallow-clone `repo` into `dest`. Non-interactive (GIT_TERMINAL_PROMPT=0) so a
    private repo without ambient credentials FAILS fast instead of prompting for one.
    Returns (returncode, error-tail). Module-level so tests can substitute it."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    try:
        proc = subprocess.run(["git", "clone", "--depth", "1", repo, str(dest)],
                              capture_output=True, text=True, timeout=600, env=env)
    except FileNotFoundError:
        return 1, "git not found on PATH"
    except subprocess.TimeoutExpired:
        return 1, "git clone timed out"
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()
        return proc.returncode, (tail[-1] if tail else "git clone failed")
    return 0, ""


def _checkout_present(dest: Path) -> bool:
    """A checkout we must never touch: the dir exists and is non-empty."""
    return dest.exists() and any(dest.iterdir())


# ── deploy ───────────────────────────────────────────────────────────────────
def cmd_deploy(reg: Registry, machine: str, dry_run: bool, force: bool,
               root: Path | None = None, lane: str = "all",
               prune: bool = False, target: str | None = None) -> int:
    if machine not in reg.machines:
        print(f"error: unknown machine {machine!r}")
        return 2
    # Example machines are templates: previewing (--dry-run) or sandboxing (--root) is fine,
    # but refuse a real deploy to live paths — copy it into registry/local/machines/ first.
    if reg.machines[machine].get("example") and not dry_run and root is None:
        print(f"refusing to deploy example template {machine!r} to real paths. Copy "
              f"machines/{machine}.yaml into registry/local/machines/, rename and customize "
              f"it, then deploy that. (Preview with --dry-run, or sandbox with --root <dir>.)")
        return 2
    if target and target not in reg.targets and target != "env":
        print(f"error: unknown target {target!r}")
        return 2
    machine_os = reg.machines[machine].get("os")
    if root is None and machine_os and machine_os != _local_os():
        print(f"error: machine {machine!r} is {machine_os!r} but this host is "
              f"{_local_os()!r} — refusing to write into this host's filesystem.\n"
              f"Use --root <dir> to rehearse this deploy into a sandbox tree.")
        return 2
    lock_base = root if root is not None else reg.root
    lock = lockfile.load(lock_base)

    # Filter prior entries in-place to remove any paths that do not match the current machine roots
    prior_raw = lockfile.machine_files(lock, machine)
    filtered = _filter_prior_by_machine_paths(reg, machine, prior_raw)
    prior_raw.clear()
    prior_raw.update(filtered)

    all_outputs = _machine_outputs(reg, machine)
    outputs = [o for o in all_outputs
               if lane in ("all", o.lane) and (target is None or o.target == target)]
    statuses = [classify_output(reg, machine, o, lock, root) for o in outputs]
    # orphans: previously deployed by us, no longer planned at all (a deselected
    # skill, a retired project). Lock entries are KEPT until --prune deletes the
    # files, so pruning works on any later deploy too. Computed against the FULL
    # plan, never the lane/target subset — a filtered deploy must not see false
    # orphans (and never drops the unfiltered outputs' lock entries).
    prior = lockfile.machine_files(lock, machine)
    planned = {o.deploy_path for o in all_outputs}
    orphans = sorted(p for p in prior if p not in planned)

    blocked = [s for s in statuses
               if s.state in ("drift", "conflict") and s.output.drift_policy == "protect"]
    sandbox = f", sandbox root {root}" if root is not None else ""
    lane_note = f", lane {lane}" if lane != "all" else ""
    target_note = f", target {target}" if target else ""
    print(f"deploy plan for {machine} "
          f"({'dry-run' if dry_run else 'apply'}{sandbox}{lane_note}{target_note}):")
    for s in statuses:
        flag = ""
        if s.state in ("drift", "conflict"):
            if s in blocked and not force:
                flag = "  <-- protected, blocked"
            else:
                flag = "  <-- will capture to inbox/, then overwrite"
        print(f"  [{s.state:9}] {s.output.deploy_path}{(' — ' + s.detail) if s.detail else ''}{flag}")
    if orphans:
        note = ("will delete; drifted ones captured to inbox/ first" if prune
                else "kept on disk — re-run with --prune to delete")
        print(f"  {len(orphans)} orphan(s) — previously deployed, no longer planned ({note}):")
        for p in orphans:
            print(f"  [orphan   ] {p}")
    # skill diagnostics: compatible-but-not-deployed (machine curation) and scope-ignoring
    # targets (hermes/claude-app) receiving a scope: project skill. Warn-only — nothing
    # here changes what deploys, it just makes a previously silent filter visible.
    if target is None and lane in ("all", "content"):
        skill_warnings = skill_deploy_warnings(reg, machine)
        if skill_warnings:
            print(f"  {len(skill_warnings)} skill warning(s):")
            for w in skill_warnings:
                print(f"  [warn     ] {w}")
    # repo clones into the Agentic Context tree (claude-code env only; full deploys only).
    clones = (plan_clones(reg, machine)
              if target is None and lane in ("all", "content") else [])
    if clones:
        print(f"  {len(clones)} repo clone(s) (clone-if-absent; existing checkouts left "
              f"untouched):")
        for c in clones:
            here = "present, untouched" if _checkout_present(_dest(c.dest, root)) \
                else "absent -> will clone"
            print(f"  [clone    ] {c.dest} — {here}")

    if blocked and not force:
        print(f"\nrefusing to deploy: {len(blocked)} protected file(s) drifted. "
              f"Resolve with `adopt` / `harvest`, or pass --force.")
        if dry_run:
            pass  # still allow showing the plan
        else:
            return 1
    if dry_run:
        print("\n(dry-run: nothing written)")
        return 0

    # everything not deployed in this run keeps its lock entry: the other lane's
    # files, and orphans (so a later --prune can still find and delete them)
    deploying = {o.deploy_path for o in outputs}
    files_record: dict = {p: e for p, e in prior.items() if p not in deploying}
    written = 0
    captured = 0
    pruned = 0
    if prune:
        for p in orphans:
            dest = _dest(p, root)
            entry = prior.get(p) or {}
            if dest.exists():
                is_binary = p.endswith(".zip")
                if is_binary:
                    live_hash = sha256(dest.read_bytes())
                else:
                    try:
                        live_hash = sha256(dest.read_text(encoding="utf-8"))
                    except UnicodeDecodeError:
                        live_hash = sha256(dest.read_bytes())
                if live_hash != entry.get("deployed_hash"):
                    # the tool edited it since we deployed it — a proposal is a
                    # proposal, even on a file being retired: capture before delete
                    try:
                        fake = Output(target="orphan", kind="text", deploy_path=p,
                                      dist_rel="", content="",
                                      drift_policy=entry.get("drift_policy", "protect"),
                                      sources=entry.get("sources") or [])
                        folder = _capture_to_inbox(reg, machine, Status(fake, "orphan"),
                                                   lock, root)
                        captured += 1
                        print(f"  captured -> {folder.relative_to(lock_base).as_posix()}")
                    except UnicodeDecodeError:
                        print(f"  (binary orphan not captured: {p})")
                dest.unlink()
                print(f"  pruned {p}")
            pruned += 1
            files_record.pop(p, None)
    for s in statuses:
        o = s.output
        if s.state in ("drift", "conflict") and o.drift_policy == "protect" and not force:
            # preserve existing lock entry; skip writing
            prev = lockfile.machine_files(lock, machine).get(o.deploy_path)
            if prev:
                files_record[o.deploy_path] = prev
            continue
        if (s.state in ("drift", "conflict") and o.kind not in ("env", "zip")
                and o.drift_policy != "generated"):
            # about to overwrite an in-place edit (harvest policy, or protect + --force):
            # snapshot it into inbox/ first — the proposal must survive the deploy.
            # Exempt: env files (inbox/ is tracked in git and must never hold secrets;
            # their canonical local source is the .local/ overlay), staged zips (binary
            # build artifacts), and "generated" graph-tree files (no registry partial to
            # route an edit back to — they are regenerated from registry/graph/).
            folder = _capture_to_inbox(reg, machine, s, lock, root)
            captured += 1
            print(f"  captured -> {folder.relative_to(lock_base).as_posix()}")
        if o.kind in ("yaml_merge", "json_merge"):
            ok = (_apply_yaml_merge(o, root) if o.kind == "yaml_merge"
                  else _apply_json_merge(o, root))
            if ok:
                written += 1
            continue
        payload = _payload(o)
        if o.kind == "zip":
            write_bytes(_dest(o.deploy_path, root), payload)
        else:
            dest_path = _dest(o.deploy_path, root)
            write_text(dest_path, o.content)
            if o.executable and machine_os != "windows":
                try:
                    os.chmod(dest_path, 0o755)
                except OSError:
                    pass
        written += 1
        h = sha256(payload)
        entry = {
            "source_hash": h, "deployed_hash": h,
            "drift_policy": o.drift_policy, "sources": o.sources,
        }
        if o.section_bodies:
            # multi-source doc: record the per-section base so adopt can route an edit
            # back to its partial without any provenance markers in the deployed file
            entry["sections"] = [{"source": s, "text": b} for s, b in o.section_bodies]
        files_record[o.deploy_path] = entry
    lockfile.record(lock, machine, _now(), files_record)
    lockfile.save(lock_base, lock)
    # clone repos AFTER files land. Clone-if-absent and non-destructive (design rule #8):
    # an existing checkout is never pulled, reset, or deleted. A clone failure (e.g. a
    # private repo without ambient creds) is reported, never fatal — the deploy succeeded.
    cloned = clone_failed = 0
    for c in clones:
        dest = _dest(c.dest, root)
        if _checkout_present(dest):
            continue
        rc_c, err = _git_clone(c.repo, dest)
        if rc_c == 0:
            cloned += 1
            print(f"  cloned {c.repo} -> {c.dest}")
        else:
            clone_failed += 1
            print(f"  clone failed for {c.slug} ({c.repo}): {err} — reported, not fatal")
    tail = f"; captured {captured} inbox candidate(s)" if captured else ""
    tail += f"; pruned {pruned} orphan(s)" if pruned else ""
    tail += f"; cloned {cloned} repo(s)" if cloned else ""
    tail += f"; {clone_failed} clone(s) failed (reported)" if clone_failed else ""
    print(f"\ndeployed {written} file(s); updated {lockfile.LOCK_NAME}{tail}")
    return 0


# ── graph ────────────────────────────────────────────────────────────────────
def cmd_graph(reg: Registry, project: str | None, query: str) -> int:
    """Inspect/validate the knowledge graph and run a saved SPARQL query.

    With no --project, list every loaded project graph. With one, validate it (loading
    already did, loudly), report whether it is canonically serialized, and print the
    result of the named saved query (default: its document index).
    """
    from . import graph as graphmod
    if not reg.graphs:
        print("no project graphs — add registry/graph/<slug>.jsonld "
              "(see the knowledge-graph design).")
        return 0
    if project is None:
        print(f"{len(reg.graphs)} project graph(s):")
        for slug, pg in sorted(reg.graphs.items()):
            print(f"  {slug:20} {len(pg.documents):3} doc(s)  {pg.name}")
        return 0
    pg = reg.graphs.get(project)
    if pg is None:
        print(f"error: no graph for project {project!r} "
              f"(have: {', '.join(sorted(reg.graphs)) or 'none'})")
        return 2
    canon = "canonical" if graphmod.is_canonical(pg.path, pg) else (
        "NOT canonical — run `graph` re-serialization to normalize")
    print(f"{pg.name} ({pg.slug}) — {len(pg.documents)} document(s) [{canon}]")
    if pg.description:
        print(f"  {pg.description}")
    try:
        rows = graphmod.run_query(pg, query)
    except graphmod.GraphError as e:
        print(f"error: {e}")
        return 2
    print(f"\nquery {query!r}: {len(rows)} row(s)")
    for r in rows:
        print("  " + "  ".join(f"{k}={v}" for k, v in r.items()))
    return 0


# ── diff ─────────────────────────────────────────────────────────────────────
def cmd_diff(reg: Registry, machine: str, root: Path | None = None,
             lane: str = "all", target: str | None = None) -> int:
    if machine not in reg.machines:
        print(f"error: unknown machine {machine!r}")
        return 2
    lock_base = root if root is not None else reg.root
    lock = lockfile.load(lock_base)
    statuses = [classify_output(reg, machine, o, lock, root)
                for o in _machine_outputs(reg, machine)
                if lane in ("all", o.lane) and (target is None or o.target == target)]
    order = ["conflict", "drift", "resolved", "pending", "create", "merge", "unchanged"]
    lane_note = f" (lane {lane})" if lane != "all" else ""
    print(f"drift report for {machine}{lane_note}:")
    for state in order:
        rows = [s for s in statuses if s.state == state]
        for s in rows:
            tag = f" ({s.output.drift_policy})" if state in ("drift", "conflict") else ""
            print(f"  [{state:9}]{tag} {s.output.deploy_path}"
                  f"{(' — ' + s.detail) if s.detail else ''}")
    drifted = [s for s in statuses if s.state in ("drift", "conflict")]
    harvestable = [s for s in drifted if s.output.drift_policy == "harvest"]
    if harvestable:
        print(f"\n{len(harvestable)} harvest candidate(s) — run `harvest --machine {machine}`.")
    return 0


# ── adopt ────────────────────────────────────────────────────────────────────
def cmd_adopt(reg: Registry, path: str) -> int:
    resolved = Path(path).expanduser().resolve()
    match = _find_output(reg, resolved)
    if not match:
        print(f"error: no compiled output deploys to {resolved}")
        return 2
    machine, o = match
    if o.kind == "env":
        print("env files are not adopted; edit the .local/ overlay (or the template in "
              "connections/env/) and re-deploy.")
        return 1
    if o.kind == "zip":
        print("staged claude.ai zips are build artifacts — edit the skill under "
              "registry/skills/ and recompile, then re-upload the refreshed zip.")
        return 1
    if o.drift_policy == "generated":
        print("this file is generated from the knowledge graph (non-adoptable) — edit "
              "registry/graph/<project>.jsonld and redeploy.")
        return 1
    if o.kind != "text":
        print("adopt supports text files only; JSON/YAML configs are generated from "
              "connections/servers.yaml — edit that instead.")
        return 1
    live = resolved.read_text(encoding="utf-8")

    # Prefer the recorded per-section base whenever the file has more than one section
    # (a multi-partial doc, OR prose + a generated block). Only a genuinely single-source
    # file routes the whole body to one partial.
    base = _lock_sections(reg, machine, o.deploy_path) or (o.section_bodies or None)
    if base and len(base) > 1:
        # reconstruct the per-section split (no in-file markers) using the base recorded
        # at deploy; the generated section maps to no partial and is skipped.
        changed, warnings, err = route_into_registry(reg, "", live, sections=base)
    elif len(o.sources) == 1:
        changed, warnings, err = route_into_registry(reg, o.sources[0], live)
    else:
        print("error: cannot adopt multi-source file without a lockfile section map.")
        print("To resolve, review the changes on disk and manually edit the registry partials:")
        for src in o.sources:
            print(f"  - registry/{_real_registry_rel(reg, src)}")
        return 1
    for w in warnings:
        print(f"  warn: {w}")
    if err:
        print(err)
        return 1
    print("adopted -> " + ", ".join(f"registry/{c}" for c in changed) if changed
          else "no changes detected — registry already matches.")
    return 0


def route_into_registry(reg: Registry, registry_path: str, payload_text: str,
                        sections: list[tuple[str, str]] | None = None,
                        keep_frontmatter: bool = False,
                        ) -> tuple[list[str], list[str], str | None]:
    """The accept engine — one routing core, two entrances: `adopt` (a live deployed
    file) and `review` (an inbox candidate snapshot) both end here.

    Single source: the whole body maps back to the one registry file (skills carry
    rendered frontmatter in the payload; it's stripped — the registry copy keeps its
    own). A brand-new path (`kind: new` candidates) is written verbatim.
    With `sections` (the per-section base of a multi-source document): the payload is
    split back into its partials via difflib alignment.
    With `keep_frontmatter=True` (a console structured-metadata edit, `verbatim: true`
    in its meta): the payload IS the full file — frontmatter reassembled server-side by
    `review.propose_meta_edit`, never operator-typed — so it's diffed and written whole
    instead of having its frontmatter stripped first.

    Returns (changed registry-relative paths, warnings, error). error is None on
    success; changed is empty when the payload already matches the registry.
    """
    if sections:
        mapping = render.split_live_sections(sections, payload_text)
        if mapping is None:
            srcs = "\n".join(f"  - registry/{src}" for src, _ in sections)
            return [], [], ("an edit spans a section boundary — it can't be attributed "
                            f"cleanly. Apply it by hand to the relevant partial(s):\n{srcs}")
        changed, warnings = [], []
        for src, new_body in mapping.items():
            if render.is_generated_source(src):
                continue   # a generated block routes to no registry partial — never adopted
            partial = reg.partials.get(src)
            if partial is None:
                warnings.append(f"section {src!r} maps to no registry partial; skipped")
                continue
            # Fold any expanded personalization values back into their placeholder
            # tokens BEFORE comparing — scoped to the tokens `partial.body` actually
            # contains, so a partial that never used a placeholder is never touched.
            # Doing this before the comparison (not after, in _rewrite_registry_body)
            # matters: comparing expanded `new_body` against the placeholder-bearing
            # `partial.body` directly would report a phantom change on every deploy of
            # a personalized file and bake real values into the registry.
            reversed_body = render.reverse_expand_placeholders(reg, partial.body, new_body)
            if reversed_body != partial.body:
                _rewrite_registry_body(reg, src, reversed_body)
                changed.append(partial.rel)   # the real path — overlay-aware
        return changed, warnings, None
    if not registry_path:
        return [], [], ("no registry route for this content (multi-source candidate "
                        "without a per-section base) — apply it by hand.")
    real = _real_registry_rel(reg, registry_path)   # route overlay-backed paths into local/
    dest = reg.root / "registry" / real
    if not dest.is_file():
        # a `new` proposal: the payload IS the proposed file, frontmatter and all
        write_text(dest, payload_text.rstrip("\n") + "\n")
        return [real], [], None
    if keep_frontmatter:
        new_text = payload_text.rstrip("\n") + "\n"
        if dest.read_text(encoding="utf-8") == new_text:
            return [], [], None
        write_text(dest, new_text)
        return [real], [], None
    body = (render.strip_frontmatter(payload_text)
            if real.endswith("SKILL.md") else payload_text)
    current = dest.read_text(encoding="utf-8")
    m = _FM_SPLIT.match(current)
    current_body = (m.group(2) if m else current).strip("\n")
    # Same scoped reversal as the sectioned path above, keyed off this partial's own
    # current (placeholder-bearing) body.
    reversed_body = render.reverse_expand_placeholders(reg, current_body, body.strip("\n"))
    if reversed_body == current_body:
        return [], [], None
    _rewrite_registry_body(reg, real, reversed_body)
    return [real], [], None


def _lock_sections(reg: Registry, machine: str, deploy_path: str):
    """The (source, base_text) breakdown recorded for a multi-source file at deploy,
    or None if absent (file predates the record, or was never deployed here)."""
    entry = lockfile.machine_files(lockfile.load(reg.root), machine).get(deploy_path) or {}
    secs = entry.get("sections")
    return [(s["source"], s["text"]) for s in secs] if secs else None


# ── harvest ──────────────────────────────────────────────────────────────────
def cmd_harvest(reg: Registry, machine: str | None, adopt_all: bool) -> int:
    machines = [machine] if machine else list(reg.machines)
    lock = lockfile.load(reg.root)
    candidates: list[tuple[str, object]] = []
    for m in machines:
        for s in (classify_output(reg, m, o, lock) for o in _machine_outputs(reg, m)):
            if s.state in ("drift", "conflict") and s.output.drift_policy == "harvest":
                candidates.append((m, s))
    if not candidates:
        print("no harvest candidates — no self-improving tool has edited a harvest file.")
        return 0
    print(f"{len(candidates)} harvest candidate(s) — tool edits to harvest-policy files:")
    for m, s in candidates:
        print(f"  [{m}] {s.output.deploy_path}  ({s.state})")
    if not adopt_all:
        print("\nReview each, then `adopt <path>` to pull it into the registry, "
              "or re-`deploy` to discard (registry wins). Use --adopt-all to adopt every one.")
        return 0
    print("\n--adopt-all: pulling each into the registry...")
    rc = 0
    for _m, s in candidates:
        rc |= cmd_adopt(reg, s.output.deploy_path)
    return rc


# ── registry write-back + lookup helpers ────────────────────────────────────
_FM_SPLIT = re.compile(r"^(---\n.*?\n---\n)(.*)$", re.DOTALL)


def _real_registry_rel(reg: Registry, path: str) -> str:
    """Resolve a logical registry path to the file that actually provides it. A partial
    overridden by the Mitos overlay carries a `local/` rel, so accepting a personal edit
    routes the write into registry/local/ (your private moat) instead of the public core.
    Idempotent: an already-real path (a skill rel, or a `local/...` path) returns unchanged."""
    p = reg.partials.get(path)
    return p.rel if p is not None else path


def _rewrite_registry_body(reg: Registry, rel: str, new_body: str) -> None:
    """Replace the body of a registry partial/skill file, preserving its frontmatter."""
    path = reg.root / "registry" / _real_registry_rel(reg, rel)
    text = path.read_text(encoding="utf-8")
    m = _FM_SPLIT.match(text)
    if m:
        write_text(path, m.group(1) + new_body.rstrip("\n") + "\n")
    else:
        write_text(path, new_body.rstrip("\n") + "\n")


def _find_output(reg: Registry, resolved: Path):
    for machine in reg.machines:
        for o in plan_machine(reg, machine):
            try:
                if expand(o.deploy_path).resolve() == resolved:
                    return machine, o
            except (OSError, RuntimeError):
                continue
    return None


def _apply_json_merge(o: Output, root: Path | None = None) -> bool:
    """Splice owned key paths into a tool-owned JSON file, preserving everything else.

    With `owned_prefix` set and an owned LIST value, ownership narrows further: only
    entries starting with the prefix are replaced (the compiler's own grants); all
    other entries are the user's and survive untouched.
    """
    tgt = _dest(o.target_file, root)
    new_doc = json.loads(o.content)
    if not tgt.exists():
        write_text(tgt, o.content)
        print(f"  created {o.target_file} (merge target was absent)")
        return True
    live = json.loads(tgt.read_text(encoding="utf-8"))
    for dotted in o.owned_keys:
        keys = dotted.split(".")
        new_val = new_doc
        for k in keys:
            new_val = new_val[k]
        node = live
        for k in keys[:-1]:
            node = node.setdefault(k, {})
        leaf = keys[-1]
        if o.owned_prefix and isinstance(new_val, list):
            kept = [e for e in (node.get(leaf) or [])
                    if not str(e).startswith(o.owned_prefix)]
            node[leaf] = kept + new_val
        else:
            node[leaf] = new_val
    write_text(tgt, json.dumps(live, indent=2, ensure_ascii=False) + "\n")
    print(f"  merged {o.owned_keys} into {o.target_file}")
    return True


def _apply_yaml_merge(o: Output, root: Path | None = None) -> bool:
    """Splice owned key paths into a tool-owned YAML file, preserving everything else.

    `owned_keys` entries may be dotted (e.g. `terminal.cwd`) to own a single LEAF inside
    an otherwise tool/user-owned block, without touching its siblings — a bare key (e.g.
    `mcp_servers`) still owns the whole value, same as before. A leaf string value
    starting with `~` is expanded against this box's home dir before writing, matching
    how deploy destinations themselves are resolved (`_dest`) — correct because a real
    (non-sandboxed) merge only ever runs on the machine it targets (deploy is OS-guarded).
    """
    tgt = _dest(o.target_file, root)
    if not tgt.exists():
        print(f"  skip merge: target file not present here -> {o.target_file}")
        return False
    block = _ruamel.load(o.content) or {}
    with tgt.open("r", encoding="utf-8") as fh:
        live = _ruamel.load(fh) or {}
    for dotted in o.owned_keys:
        keys = dotted.split(".")
        new_val = block
        try:
            for k in keys:
                new_val = new_val[k]
        except (KeyError, TypeError):
            continue  # this leaf wasn't in the rendered block — nothing to own yet
        if isinstance(new_val, str) and new_val.startswith("~"):
            new_val = str(expand(new_val))
        node = live
        for k in keys[:-1]:
            node = node.setdefault(k, {})
        node[keys[-1]] = new_val
    with tgt.open("w", encoding="utf-8") as fh:
        _ruamel.dump(live, fh)
    print(f"  merged {o.owned_keys} into {o.target_file}")
    return True
