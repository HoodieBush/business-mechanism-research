# Linux deployment

The Linux backend uses **bubblewrap** for model-authored Python. LangGraph, model HTTP calls, SQLite and project control stay in the ordinary controller process. No Docker daemon is required. Native Windows remains unsupported; a Linux VM/WSL environment must independently satisfy these Linux checks.

## Requirements

- Python3.12 and the tested Python dependencies.
- A maintained distro bubblewrap package with `--disable-userns` support.
- Working unprivileged user, mount, PID, IPC, UTS and network namespaces. A host/container policy may disallow them even when bwrap is installed.

On Ubuntu24.04:

```sh
sudo apt-get update
sudo apt-get install bubblewrap python3.12-venv
git clone https://github.com/HoodieBush/business-mechanism-research.git
cd business-mechanism-research
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-tested.txt
python -m pip install --no-deps .
python -m pip check
python tools/check_install.py
python tests/isolation.py --output ./acceptance-isolation
python tests/acceptance.py --output ./acceptance-local
```

Use new output directories. Once these pass, follow the normal model/data/create/run commands in README.md. The ordinary application should run under a dedicated unprivileged account. Installing bwrap is an administrator step, not a reason to execute model code with sudo.

If the preflight reports `Operation not permitted`, the host's namespace or AppArmor policy may block bwrap. An administrator must configure the maintained package's application-specific policy. The program will not disable AppArmor globally, request sudo or execute unisolated code automatically. A container that blocks user namespaces is not a supported runtime merely because it is Linux.

## Boundary

The worker gets an empty mount namespace with read-only runtime dependencies and lawful data/artifacts, a private `/proc` and `/dev`, and an isolated network namespace. Only the current execution directory is writable. Installed engine source is masked even if it shares the Python environment. Controller environment/credentials are not inherited. Nested user namespaces and capabilities are disabled; timeout terminates the bwrap process tree.

The venv Python entry point is retained so worker scientific imports use the installed project environment, rather than accidentally resolving to a base Python without its dependencies. The existing result, source-read, file-version and execution receipts are retained.

These are tested filesystem/network/process boundaries, not a claim that this package certifies the Linux kernel or all hostile-code attacks. Keep the distro and bubblewrap security updates current. No `--ro-bind / /` or unsandboxed fallback is used.

References: [bubblewrap](https://github.com/containers/bubblewrap), [Ubuntu bwrap manual](https://manpages.ubuntu.com/manpages/noble/man1/bwrap.1.html), [Ubuntu user-namespace policy](https://ubuntu.com/blog/ubuntu-23-10-restricted-unprivileged-user-namespaces).
