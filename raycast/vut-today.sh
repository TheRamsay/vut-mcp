#!/usr/bin/env bash

# @raycast.schemaVersion 1
# @raycast.title VUT Today
# @raycast.mode fullOutput
# @raycast.packageName VUT Studis
# @raycast.icon book
# @raycast.description Show actionable VUT Studis items for the next week.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
UV_BIN="${UV_BIN:-$(command -v uv || true)}"

if [[ -z "${UV_BIN}" && -x "${HOME}/.local/bin/uv" ]]; then
  UV_BIN="${HOME}/.local/bin/uv"
fi

if [[ -z "${UV_BIN}" && -x "/opt/homebrew/bin/uv" ]]; then
  UV_BIN="/opt/homebrew/bin/uv"
fi

if [[ -z "${UV_BIN}" ]]; then
  echo "# VUT Today"
  echo
  echo "Could not find uv. Set UV_BIN to the full uv path in this script."
  exit 1
fi

cd "${REPO_ROOT}"

"${UV_BIN}" run python - <<'PY'
import asyncio
from collections import Counter

from vut_studis.client import StudisClient
from vut_studis.errors import StudisError

HORIZON_DAYS = 7


async def main() -> None:
    try:
        actions = await StudisClient().get_pending_actions(horizon_days=HORIZON_DAYS)
    except StudisError as error:
        print("# VUT Today")
        print()
        print(f"Studis error: {error}")
        print()
        print("Try refreshing the session:")
        print("uv run vut-studis-debug login-refresh-session")
        return

    print("# VUT Today")
    print()
    print(f"Pending actions in the next {HORIZON_DAYS} days: {len(actions)}")

    if not actions:
        print()
        print("No pending VUT actions in this horizon.")
        return

    severities = Counter(action.severity for action in actions)
    print(
        "Severity: "
        f"critical {severities['critical']}, "
        f"warning {severities['warning']}, "
        f"info {severities['info']}"
    )
    print()

    for action in actions:
        when = action.due_at or action.starts_at
        when_text = when.strftime("%Y-%m-%d %H:%M") if when else "no date"
        days_left = f"{action.days_left}d left" if action.days_left is not None else "no date"
        print(f"## [{action.severity}] {action.course_code}: {action.title}")
        print(f"- When: {when_text} ({days_left})")
        print(f"- Action: {action.action_kind}")
        print(f"- Reason: {action.reason}")
        print(f"- Next: {action.suggested_next_step}")
        if action.detail_url:
            print(f"- Link: {action.detail_url}")
        print()


asyncio.run(main())
PY
