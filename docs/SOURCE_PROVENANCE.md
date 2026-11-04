# Source provenance and code map

The public layer is src/business_mechanism. Read service.py (lifecycle), graph.py (scheduling), engine.py (workspace/runtime integration), transport.py (provider protocol and shared limits), data.py (business SQLite), sandbox.py (isolation), prompts.py (role instructions), and delivery.py (reports).

The _engine subtree contains a source-pinned execution backend developed in this project. It is included as inspectable source, not a binary dependency or a requirement to clone another repository. Existing historical module names preserve source correspondence and versioned contracts; they are not additional supported public entry points.

engine_manifest.json hashes every exported engine file and is verified on import. reuse_manifest.json retains exact bindings to ten reused foundational source files. The public version does not imply a clean rewrite of all historical modules; reducing internal inheritance remains maintenance work.

Version0.1.4 fixes the export boundary. The initial local0.1.3 package was assembled with an overly broad adjacent-file rule and included non-runtime development documentation/configuration and interface-probe records. They are excluded here. Only engine Python, runtime text prompts/contracts and the reuse manifest are exported. No paid experiment transcript, real business dataset, budget database, account key or personal absolute path is part of this public snapshot.

Engine Python is retained byte-for-byte from the local source snapshot; the public API version changes to0.1.4 and package metadata, documentation and export allowlist are updated. No scientific algorithm or opinion is rewritten by this packaging correction. New workspace identities bind the new source/export; old workspaces cannot be resumed by silently changing their identity.

Third-party libraries are normal installation dependencies, not vendored implementations. Their licenses remain in their own distributions; see requirements-tested.txt. This project's original code is under MIT. No external paper is claimed as an implemented result solely because its ideas informed the design.

## Version0.1.5 platform adaptation

The execution primitive gains a platform-command seam while retaining result/file/source-read receipts. The public worker supplies Linux bubblewrap or the macOS policy. Python uses the venv entry point, with base runtime libraries allowed separately, to avoid accidentally executing the base interpreter without installed scientific packages. The changed primitive, reuse binding and engine manifest are rehashed together; this is a deliberate new source version, not a silent change to old pinned workspaces.
