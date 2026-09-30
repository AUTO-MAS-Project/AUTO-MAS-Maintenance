"""Run with: uv run python examples/client_integration.py URL arknights"""

import argparse

from automas_api.client import check_maintenance


def main():
    parser = argparse.ArgumentParser(description="Preview the task-start maintenance decision")
    parser.add_argument("status_url", help="Configured stable URL ending in /api/v1/status.json")
    parser.add_argument("game", choices=["arknights", "endfield"])
    args = parser.parse_args()
    decision = check_maintenance(args.status_url, args.game)
    if decision.skip:
        print(f"Skip this task: planned maintenance until {decision.maintenance.end.isoformat()}")
        # In AUTO-MAS, record this occurrence as skipped and return to the
        # scheduler. Do not retry the same occurrence or disable future tasks.
        return
    print(f"Continue normal task flow ({decision.reason})")
    # Call the existing game update / execution path here. If a version check
    # is needed, the client calls official Launcher get_latest_game directly.


if __name__ == "__main__":
    main()
