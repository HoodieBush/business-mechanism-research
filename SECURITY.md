# Security and data handling

Do not publish a vulnerability report containing an exploit against a live service, credentials, private inputs or an unredacted workspace. Use the repository's private vulnerability reporting feature where available; otherwise open a minimal issue requesting a private channel without sensitive details.

The runtime uses macOS sandbox-exec or Linux bubblewrap with user/PID/network isolation, and refuses unavailable isolation instead of falling back. Model-authored Python must remain isolated from private engine source, credentials and network access. Model calls made by the controller send research input to the configured provider; choose a service and dataset you are authorized to use.

Store keys outside the checkout and workspaces. Run `python scripts/check_secrets.py --all-files` before a commit, or `--staged` to inspect the exact staged snapshot. The check is a guard, not a guarantee against all forms of sensitive information.

Only local, same-version/same-path recovery has been verified. Back up the stopped workspace in full. The project does not include a multi-user service, network authentication layer or general-purpose cross-platform isolation adapter.
