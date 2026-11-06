# Business Mechanism Research v0

Persistent researcher–critic agents for evidence-led business research. Supply a question, a SQLite database and field definitions. The researcher explores, proposes testable hypotheses, computes results and revises its judgments. An independent critic reads original records and checks evidence. Negative and unresolved findings are legitimate outputs.

v0 provides a local CLI and synchronous Python API with actual LangGraph scheduling. Python3.12 is required. Linux uses bubblewrap; macOS uses sandbox-exec. Current local validation covers Linux; macOS evidence is recorded by the matching-commit CI. Scientific efficacy and uninterrupted 24-hour availability remain unverified. See [evaluation scope](docs/EVALUATION.md).

## Capabilities

- Read-only SQL and sandboxed Python, with persistent large-query results and paging.
- Attributed reviews, durable drafts, explicit field repairs and idempotent submission.
- Bounded active hypotheses, honest unresolved handoffs and finite task recovery.
- Traceable contexts/reports, cooperative pause and explicit copy-only migration retaining costs and originals.

See [interface details](docs/AGENT_REPAIRS.zh-CN.md). Tool execution, review agreement and scientific correctness are separate outcomes.

## Install and verify

Configure the OS sandbox first; Linux instructions are in [docs/LINUX.md](docs/LINUX.md).

```sh
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-tested.txt
python -m pip install --no-deps .
python -m pip check
python tools/check_install.py
python tests/acceptance.py --output ./acceptance-local
python tests/update_compatibility.py --output ./acceptance-update
```

Use new output directories. Engineering tests use a deterministic loopback fixture and make zero external model calls. See [deployment verification](DEPLOYMENT_VERIFICATION.md).

## Run a study

Copy `model.example.json` to `model.json`, configure an authorized compatible service, and keep credentials outside the repository and workspaces. See [configuration](docs/CONFIGURATION.md).

```sh
python examples/create_example_data.py --output ./example-inputs
python tools/check_install.py --model-config ./model.json --data ./example-inputs
business-research create ./work/P001 \
  --question 'Investigate differences between registered and completed counts; distinguish evidence from unverified explanations.' \
  --model-config ./model.json --data ./example-inputs \
  --tokens 2000000 --requests 80 --wall-seconds 7200 --max-stages 2
business-research run ./work/P001 --stages 1
```

Creation makes no model call. Running sends lawful inputs to the configured provider and incurs its charges. The example allowance does not guarantee report completion. Your business inputs need `business.sqlite`, `business_brief.md` and `data_dictionary.json`. Optional public-data preparation is documented in [FreshRetailNet](docs/FRESHRETAILNET.zh-CN.md).

```sh
business-research status ./work/P001
business-research report ./work/P001
business-research pause ./work/P001
business-research run ./work/P001 --resume --stages 1
```

Pause drains paid tool work first. Resume preserves costs, attempts, unknown reserves and the original deadline. Reports, handoffs, original scientific records and rejected operations remain attributable. See [operations](docs/OPERATIONS.md) for detached supervision, backups and migration.

## Documentation

[中文](README.zh-CN.md) · [System](docs/SYSTEM.md) · [Reproducibility](docs/REPRODUCIBILITY.md) · [v0 release notes](docs/releases/v0.md) · [Source provenance](docs/SOURCE_PROVENANCE.md) · [Contributing](CONTRIBUTING.md) · [Citation](CITATION.cff)

The source-pinned engine is inspectable under `src/business_mechanism/_engine`; public APIs live in `src/business_mechanism`. Private experiments, model configurations, credentials, business data and unused prototypes are excluded from release contents. Licensed under [MIT](LICENSE).
