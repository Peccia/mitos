"""Mitos compiler.

Renders the canonical registry/ into each tool's native config format and deploys it
to the machines where those tools run. Small on purpose: the registry is the moat, the
compiler is disposable plumbing.
"""

REPO_ROOT = None  # set by compile.py at startup
