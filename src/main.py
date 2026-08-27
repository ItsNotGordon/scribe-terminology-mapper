"""Command-line entry point for the Clinical Terminology Mapper.

This file is the "front door" for local runs. It does not transcribe
audio, call an LLM, or talk to FHIR. It only:

1. Loads synthetic encounters from a JSON file.
2. Sends the manually supplied phrases through the mapping pipeline.
3. Prints structured JSON.

Run from the project folder (see README.md for Windows steps):
    python -m src.main
    python -m src.main --encounter-id SYN-001
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

# python src/main.py puts the src folder on sys.path, not the project folder.
# Adding the project folder lets both `python src/main.py` and
# `python -m src.main` import `src.pipeline`.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.pipeline import map_encounter  # noqa: E402
from src.schemas import EncounterInput, encounter_from_dict  # noqa: E402

DEFAULT_ENCOUNTERS = _PROJECT_ROOT / "evaluation" / "synthetic_encounters.json"


def load_encounters(path: Path) -> list[EncounterInput]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("The encounters file must contain a JSON array.")
    encounters = [encounter_from_dict(item) for item in raw if isinstance(item, dict)]
    if not encounters:
        raise ValueError("The encounters file did not contain any encounters.")
    return encounters


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Map synthetic clinical phrases to ICD-10-CM and RxNorm candidates."
    )
    parser.add_argument(
        "--encounters-file",
        type=Path,
        default=DEFAULT_ENCOUNTERS,
        help="JSON file of synthetic encounters (default: evaluation/synthetic_encounters.json).",
    )
    parser.add_argument(
        "--encounter-id",
        type=str,
        default=None,
        help="Optional encounter_id to run a single synthetic case.",
    )
    return parser.parse_args()


def main() -> int:
    load_dotenv(_PROJECT_ROOT / ".env")
    args = parse_args()

    if not args.encounters_file.exists():
        print(f"Could not find encounters file: {args.encounters_file}", file=sys.stderr)
        return 1

    try:
        encounters = load_encounters(args.encounters_file)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Could not read encounters file: {exc}", file=sys.stderr)
        return 1

    if args.encounter_id:
        encounters = [item for item in encounters if item.encounter_id == args.encounter_id]
        if not encounters:
            print(f"No synthetic encounter found with id {args.encounter_id}.", file=sys.stderr)
            return 1

    output = []
    for encounter in encounters:
        output.extend(result.to_dict() for result in map_encounter(encounter))

    json.dump(output, sys.stdout, indent=2)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
