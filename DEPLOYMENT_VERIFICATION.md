# v0 deployment verification

v0 is verified locally on Linux with bubblewrap and Python3.12. This receipt covers local Linux; use the matching-commit CI results for macOS. All engineering checks use local fixtures and zero external model calls.

| Check | Count |
|---|---:|
| Regression tests | 75 |
| Linux isolation | 14 |
| Two-stage acceptance | 17 |
| Business workflow | 21 |
| Continuous supervisor | 9 |
| Continuation | 9 |
| Cross-layer update compatibility | 11 |

The75 regression cases comprise73 passes and2 optional historical-bundle skips; mandatory synthetic migration coverage passed.

The installed wheel additionally passes CLI/preflight, dependency checks and the actual two-stage fixture outside its source directory. Source archives are checked for fixed-engine integrity, necessary deployment files, version consistency and excluded private/runtime files. Machine-readable results are recorded in [verification/v0.json](verification/v0.json).

To reproduce, install the tested requirements and package in a new Python3.12 environment, then run the commands in [CONTRIBUTING.md](CONTRIBUTING.md). Output directories must not already exist. An actual deployment upgrade additionally requires a drained predecessor, explicit copy migration and the deployment-copy mode of tests/update_compatibility.py before a changed paid run.

These checks establish their engineering coverage. They do not certify the correctness of business mechanisms or completion of a continuous 24-hour experiment. See [evaluation scope](docs/EVALUATION.md).
