"""
Backward-compatible shim for the legacy entry point:
    python -m agent.memory.rebuild_index

The implementation now lives in agent.memory.embedding.rebuild.
Prefer using `/memory rebuild-index` in chat going forward.
"""

from agent.memory.embedding.rebuild import main

if __name__ == "__main__":
    import sys

    sys.exit(main())
