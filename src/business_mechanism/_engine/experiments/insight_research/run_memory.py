"""Registered memory-profile entry; same private environment/model/total ledger."""
from .memory import MemoryWorkspace
from .runtime_memory import MemoryRuntime
from .run import main

if __name__ == '__main__': raise SystemExit(main(MemoryWorkspace, MemoryRuntime))
