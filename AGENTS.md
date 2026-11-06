# Contributor instructions

- Read README.md and docs/SOURCE_PROVENANCE.md before editing the engine.
- Public entry points are src/business_mechanism and the business-research CLI.
- Do not run external model experiments without an explicit finite authorization.
- Engineering acceptance uses a loopback fixture and zero provider calls.
- Run scripts/check_release.py, scripts/check_secrets.py --all-files tests/isolation.py and tests/acceptance.py on supported macOS/Linux with Python3.12 after relevant changes.
- After any agent interface, prompt, output, workflow, transport, migration or version change, run tests/update_compatibility.py. Keep prompt examples, executable schemas/descriptions, output paths, validators, task views, paid-request tool filters and migrated active caches compatible. Run its deployment-copy check against the actual predecessor before starting a changed real experiment. See docs/UPDATE_COMPATIBILITY.zh-CN.md; passing individual regressions does not replace this gate.
- Do not weaken isolation or silently fall back to unsandboxed execution.
- Keep predictions, counterevidence, rejected operations and original costs across recovery.
- A formal report, a correct scientific finding, and process availability are separate outcomes.
- Never commit credentials, workspaces, real business data, private logs or paid experiment transcripts.
- Do not spawn subagents. Keep changes focused and preserve versioned source provenance.

Record public changes in CHANGELOG.md and docs/releases. Keep private dated experiment reports, paid transcripts and workspaces outside release contents.
