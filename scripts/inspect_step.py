import argparse
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from cad3dify.step_inspector import inspect_step_as_json


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect STEP geometry and optionally compare it with another STEP file")
    parser.add_argument("step_filepath", type=str, help="Path to the STEP or STP file to inspect")
    parser.add_argument("--compare_to", type=str, default=None, help="Reference STEP or STP file for comparison")
    parser.add_argument("--export_views_dir", type=str, default=None, help="Optional directory for top/front/right SVG exports")
    parser.add_argument("--output", type=str, default=None, help="Optional JSON output filepath")
    args = parser.parse_args()

    result_json = inspect_step_as_json(
        step_filepath=args.step_filepath,
        compare_to=args.compare_to,
        export_views_dir=args.export_views_dir,
    )

    if args.output:
        Path(args.output).expanduser().resolve().write_text(result_json + "\n", encoding="utf-8")
    else:
        print(result_json)


if __name__ == "__main__":
    main()