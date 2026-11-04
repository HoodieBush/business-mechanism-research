# Operations and troubleshooting

[中文](OPERATIONS.zh-CN.md)

## Pause and resume

```sh
business-research pause ./work/P001
business-research status ./work/P001
business-research run ./work/P001 --resume --stages 1
```

Pause takes effect at a safe scheduling boundary. An active request may wait until its timeout. Main-thread SIGTERM requests cooperative pause; forced termination can leave unknown usage, retained as a reservation. Recovery is not guaranteed to avoid duplicate provider charges. Resume clears an operator pause, not the capacity, request count or deadline.

The deadline starts when the controller first opens and persists through restarts and pauses. Capacity, attempts, stages, wall time and lack-of-progress controls may stop a run. Not every pending condition can be fixed with resume. This version has no supported automatic capacity-extension command.

## Files and backups

project.json stores configuration/source identity; researcher/ owns scientific records, processes and memory; reviews/ contains review snapshots and actions; graph_checkpoints.sqlite and graph_operations.sqlite preserve graph state; common_budget.sqlite retains shared limits, unknowns and request history; deliveries/ holds progress and archived reports.

Stop the controller and close database connections before backing up the **entire workspace**. Same-version/same-absolute-path restoration is the verified procedure. Do not copy only one graph database, delete native processes or edit source identity to bypass a mismatch. Cross-path/cross-version migration must be validated separately.

## Exit codes and common problems

CLI codes:0 command complete,2 error,3 pending. An inconclusive scientific result can still be a legitimate completed report.

| Symptom | Action |
|---|---|
| Python3.12 or CLI unavailable | Provide the correct interpreter, activate its venv and verify pip show business-mechanism-research |
| Dependency version unavailable / import failure | Check package index/network; rebuild a clean environment from the tested lock, run pip check and preflight |
| Missing credential /401/403 | Check file permissions, service access and environment-variable priority; do not print the key |
|400 unsupported thinking/max_tokens | The gateway does not match the protocol; verify configuration or adapt it explicitly |
| Timeout /502/429 | Bounded retries preserve state; inspect reason and receipts rather than repeatedly restarting blindly |
| Proxy/TLS failure | Check bypass_proxy, certificates and network; do not disable TLS verification |
| Sandbox unavailable | Run preflight; do not fall back to unsandboxed execution |
| Project already exists | Resume it with its original version; use a different directory for a new question |
| Another controller owns project | Inspect the existing task instead of starting competing controllers |
| Source version differs | Restore the pinned package or validate an explicit migration; do not edit identity |
| Shared admission insufficient | Whole-request reservation exceeds capacity; preserve work, not a scientific refutation |
| Time/no-progress ceiling | Inspect reason and research state; resume will not reset these bounds |
| No F*.md | Report review/revision is unfinished; inspect progress and unresolved responses |
| Earlier report absent from current text | Prior reports remain independently archived as F*.md |

Live turn progress is in deliveries/latest.json. status.last_execution is the last ended/paused invocation and may lag a current run. A handoff exists from creation, so file existence alone is not research completion.

Real runs send lawful research inputs to the configured provider. No company dataset/key is distributed. This is a local component; remote authentication, other OS isolation, general migration and day-long availability remain outside verified support.
