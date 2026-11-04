# Deployment verification

## Version0.1.5

A shared execution seam now supports macOS and Linux bubblewrap, and preserves the venv Python entry point. CI creates a real venv on macOS15 and Ubuntu24.04, installs the tested dependencies and source, then runs the actual platform isolation and two-stage integration fixtures. See the workflow status and platform acceptance receipts. Linux namespace readiness is tested before a model call; unavailable isolation does not fall back.

## Historical Version0.1.4

Version0.1.4 is a source export and packaging correction. It is tested on macOS arm64/Python3.12 with requirements-tested.txt. No provider credential is needed for engineering reproduction.

The preceding local package was first installed in a new virtual environment: all65 locked dependencies downloaded from the public PyPI index, the actual wheel installed, pip check passed, and the integration fixture passed all17 checks with45 loopback HTTP requests and0 external provider calls. The original repository was absent from sys.path; system site-packages were disabled. The Python interpreter's standard library remains supplied by its base Python installation, as with a normal venv.

The public0.1.4 source is separately built into a wheel and installed into that environment. The same actual integration fixture and new deployment/preflight commands are checked against this public source export. Final results are recorded in verification/deployment_acceptance.json and verification/engineering_acceptance_result.json.

The installation preflight exercises real sandbox launch and denied file access. Documentation command checks cover sample-data generation, refusal to overwrite an existing sample, create/status/report/pause without a model call, and rejection of placeholder endpoints, missing credentials and invalid data folders.

This is a fresh software environment on the development Mac, not a second physical company's machine. GitHub CI provides an additional hosted machine when it completes. No real-provider connectivity test is performed for recipients, no key is distributed, and no scientific discovery or24-hour availability claim follows from these deployment tests.

To reproduce from a checkout use README.md. A provider-specific real run additionally requires your own compatible service and credential. Linux/Windows are not supported by the current research isolation adapter.
