# Contributor instructions

- Read README.md and docs/SOURCE_PROVENANCE.md before editing the engine.
- Public entry points are src/business_mechanism and the business-research CLI.
- Do not run external model experiments without an explicit finite authorization.
- Engineering acceptance uses a loopback fixture and zero provider calls.
- Run scripts/check_release.py, scripts/check_secrets.py --all-files and tests/acceptance.py on supported macOS/Python3.12 after relevant changes.
- Do not weaken isolation or silently fall back to unsandboxed execution.
- Keep predictions, counterevidence, rejected operations and original costs across recovery.
- A formal report, a correct scientific finding, and process availability are separate outcomes.
- Never commit credentials, workspaces, real business data, private logs or paid experiment transcripts.
- Do not spawn subagents. Keep changes focused and preserve versioned source provenance.
