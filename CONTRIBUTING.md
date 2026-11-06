# Contributing

Use Python3.12 on macOS arm64 or Linux with bubblewrap; see docs/LINUX.md. Install requirements-tested.txt and the source package as described in README.md. Open an issue or focused pull request explaining the problem, the changed behavior, and relevant validation.

```sh
python scripts/check_release.py
python scripts/check_secrets.py --all-files
python tools/check_install.py
python tests/isolation.py --output ./acceptance-isolation-change
python tests/acceptance.py --output ./acceptance-change
python -m unittest discover -s tests -p 'test_*.py' -v
python tests/update_compatibility.py --output ./acceptance-update-change
python tests/business_workflow.py --output ./acceptance-business-change
python tests/continuous.py --output ./acceptance-supervisor-change
python tests/continuation.py --output ./acceptance-continuation-change
```

Use a new acceptance directory. No model credential is needed. Real model tests are opt-in, incur costs, and must specify the model/configuration, inputs, all-role allowance, stop conditions and complete consumption.

Keep roles, tools, prompts, deterministic protections and evaluation criteria separate when attributing an improvement. Preserve negative results and original artifacts. Do not interpret tool success or critic agreement as scientific correctness.

The _engine subtree is a pinned source snapshot. Avoid broad refactors mixed with prompt or workflow experiments; update its manifest and explain source changes explicitly. New projects bind the source version; old workspaces require deliberate migration.

PRs should contain code and public synthetic fixtures only. Remove credentials, private data, workspace databases and local absolute paths. No contributor license agreement is required; contributions are submitted under the repository's MIT license.
