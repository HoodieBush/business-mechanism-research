#!/bin/sh
# Explicit administrator action; does not change global AppArmor/sysctl policy.
set -eu
if [ "$(id -u)" != 0 ]; then
  echo "Administrator step: review packaging/apparmor/business-mechanism-bwrap, then run this script with sudo." >&2
  exit 2
fi
if [ ! -r /proc/sys/kernel/apparmor_restrict_unprivileged_userns ]; then
  echo "Ubuntu restricted-userns AppArmor control is not present; no profile installed."
  exit 0
fi
if [ ! -x /usr/bin/bwrap ]; then
  echo "Install the distribution bubblewrap package first." >&2
  exit 2
fi
command -v apparmor_parser >/dev/null
task_script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
task_profile_source="$task_script_dir/../packaging/apparmor/business-mechanism-bwrap"
task_profile_target=/etc/apparmor.d/business-mechanism-bwrap
if [ -e "$task_profile_target" ] && ! cmp -s "$task_profile_source" "$task_profile_target"; then
  echo "An existing local profile differs; refusing to overwrite it. Have the administrator review it." >&2
  exit 2
fi
task_before=$(cat /proc/sys/kernel/apparmor_restrict_unprivileged_userns)
install -m 0644 "$task_profile_source" "$task_profile_target"
apparmor_parser -r "$task_profile_target"
test "$(cat /proc/sys/kernel/apparmor_restrict_unprivileged_userns)" = "$task_before"
echo "Loaded an application-specific /usr/bin/bwrap profile; global userns/AppArmor restriction unchanged."
