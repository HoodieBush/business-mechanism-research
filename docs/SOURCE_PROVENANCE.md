# v0 source provenance

The public implementation is `src/business_mechanism`. `service.py` manages projects, `graph.py` schedules roles, `engine.py` connects the source-pinned backend, `transport.py` handles provider requests and ledgers, `data.py` supplies business SQLite, `sandbox.py` enforces OS isolation, and `delivery.py` exports reports. Additional facade modules implement batch data work, review repair, coverage, convergence and recovery.

The `_engine` subtree is an inspectable execution backend developed in this project. Its historical module names retain source correspondence and versioned contracts; public callers use the facade. `engine_manifest.json` binds its483 files and is verified on import. The engine files are retained byte-for-byte in v0.

The public release exports runtime Python, prompts/contracts and the reuse manifest, with necessary documentation, fixtures and deployment tools. Credentials, paid transcripts, private workspaces, experiment timelines, theory drafts and unused candidate code are excluded. Third-party packages remain normal installation dependencies with their own licenses.

Workspace identities bind public source hashes as well as the pinned backend. Resume an old workspace with its exact package, or validate a drained copy migration with the actual predecessor. Changing a version string or source identity by hand is not an upgrade procedure. Scientific records and prior charges must remain intact.
