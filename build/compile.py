#!/usr/bin/env python
"""Mitos compiler CLI.

Usage:
  python build/compile.py compile [--target T]
  python build/compile.py deploy --machine M [--dry-run] [--force] [--root DIR]
  python build/compile.py diff   --machine M [--root DIR]
  python build/compile.py adopt  <deployed-path>
  python build/compile.py harvest [--machine M] [--adopt-all]
  python build/compile.py review [--port N] [--no-open]
  python build/compile.py graph  [--project SLUG] [--query NAME]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "build"))

from agentic import commands, loader  # noqa: E402
from agentic.loader import RegistryError  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    # Windows consoles default to cp1252; force UTF-8 so paths/content print cleanly.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass

    parser = argparse.ArgumentParser(prog="compile.py", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_compile = sub.add_parser("compile", help="validate + render the registry into dist/")
    p_compile.add_argument("--target", help="only emit this target")

    p_deploy = sub.add_parser("deploy", help="materialize dist/ to a machine")
    p_deploy.add_argument("--machine", required=True)
    p_deploy.add_argument("--dry-run", action="store_true")
    p_deploy.add_argument("--force", action="store_true",
                          help="overwrite protected files that have drifted "
                               "(the drifted content is captured to inbox/ first)")
    p_deploy.add_argument("--root", type=Path, default=None,
                          help="sandbox: write into DIR instead of the real "
                               "destinations (also bypasses the machine-OS guard; "
                               "lockfile and inbox land in DIR too)")
    p_deploy.add_argument("--lane", choices=["content", "connections", "all"],
                          default="all",
                          help="content = registry prose; connections = MCP wiring + "
                               "env (rotate a secret without touching content)")
    p_deploy.add_argument("--prune", action="store_true",
                          help="delete files this compiler previously deployed that "
                               "are no longer planned (deselected skills, retired "
                               "projects); drifted ones are captured to inbox/ first")
    p_deploy.add_argument("--target",
                          help="deploy only this adapter's outputs (e.g. claude-app); "
                               "other targets' files and lock entries are untouched")

    p_diff = sub.add_parser("diff", help="three-way drift report for a machine")
    p_diff.add_argument("--machine", required=True)
    p_diff.add_argument("--root", type=Path, default=None,
                        help="report against a sandbox tree created by deploy --root")
    p_diff.add_argument("--lane", choices=["content", "connections", "all"],
                        default="all")
    p_diff.add_argument("--target", help="report only this adapter's outputs")

    p_adopt = sub.add_parser("adopt", help="pull an in-place edit back into the registry")
    p_adopt.add_argument("path")

    p_harvest = sub.add_parser("harvest", help="review/adopt mutations from self-improving tools")
    p_harvest.add_argument("--machine")
    p_harvest.add_argument("--adopt-all", action="store_true",
                           help="adopt every harvest candidate into the registry")

    p_review = sub.add_parser("review", help="operator console: review inbox/ candidates "
                                             "and copy one-shot prompts (localhost)")
    p_review.add_argument("--port", type=int, default=8765)
    p_review.add_argument("--no-open", action="store_true",
                          help="don't open the browser automatically")

    p_graph = sub.add_parser("graph", help="inspect/validate a project knowledge graph "
                                           "and run a saved SPARQL query")
    p_graph.add_argument("--project", help="project slug (omit to list all graphs)")
    p_graph.add_argument("--query", default="documents",
                         help="saved query name (default: documents)")

    args = parser.parse_args(argv)

    try:
        reg = loader.load(REPO_ROOT)
    except RegistryError as e:
        print(f"registry error: {e}", file=sys.stderr)
        return 2

    if args.cmd == "compile":
        return commands.cmd_compile(reg, REPO_ROOT / "dist", args.target)
    if args.cmd == "deploy":
        return commands.cmd_deploy(reg, args.machine, args.dry_run, args.force,
                                   args.root, args.lane, args.prune, args.target)
    if args.cmd == "diff":
        return commands.cmd_diff(reg, args.machine, args.root, args.lane, args.target)
    if args.cmd == "adopt":
        return commands.cmd_adopt(reg, args.path)
    if args.cmd == "harvest":
        return commands.cmd_harvest(reg, args.machine, args.adopt_all)
    if args.cmd == "review":
        from agentic import review
        return review.cmd_review(reg, args.port, open_browser=not args.no_open)
    if args.cmd == "graph":
        return commands.cmd_graph(reg, args.project, args.query)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
