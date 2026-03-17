import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


def main():
    import argparse
    parser = argparse.ArgumentParser(description="CAD drawing to STEP workflow CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    start_parser = subparsers.add_parser("start", help="Initialize a workflow from an input drawing")
    start_parser.add_argument("image_filepath", type=str, help="Path to the CAD image file")
    start_parser.add_argument("--workspace_dir", type=str, required=True, help="Directory used to store workflow artifacts")
    start_parser.add_argument("--output_filepath", type=str, default="output.step", help="Final STEP output filename")
    start_parser.add_argument("--model_type", type=str, default="gpt")
    start_parser.add_argument("--num_refinements", type=int, default=0)
    start_parser.add_argument("--auto_approve", action="store_true", help="Run without interactive confirmation")

    continue_parser = subparsers.add_parser("continue", help="Continue a workflow from saved artifacts")
    continue_parser.add_argument("--workspace_dir", type=str, required=True, help="Directory used to store workflow artifacts")
    continue_parser.add_argument("--until_stage", type=str, default="execute-code", choices=["analyze-drawing", "generate-code", "execute-code", "refine-code"])
    continue_parser.add_argument("--auto_approve", action="store_true", help="Run without interactive confirmation")

    stage_parser = subparsers.add_parser("run-step", help="Run a single workflow stage")
    stage_parser.add_argument("stage", type=str, choices=["analyze-drawing", "generate-code", "execute-code", "refine-code"])
    stage_parser.add_argument("--workspace_dir", type=str, required=True, help="Directory used to store workflow artifacts")

    legacy_parser = subparsers.add_parser("legacy-run", help="Run the full workflow end-to-end")
    legacy_parser.add_argument("image_filepath", type=str, help="Path to the CAD image file")
    legacy_parser.add_argument("--output_filepath", type=str, default="output.step", help="Path to the output STEP file")
    legacy_parser.add_argument("--workspace_dir", type=str, default=None, help="Directory used to store workflow artifacts")
    legacy_parser.add_argument("--model_type", type=str, default="gpt")
    legacy_parser.add_argument("--num_refinements", type=int, default=0)
    legacy_parser.add_argument("--auto_approve", action="store_true", help="Run without interactive confirmation")

    args = parser.parse_args()

    if args.command == "start":
        from cad3dify import generate_step_from_2d_cad_image

        generate_step_from_2d_cad_image(
            image_filepath=args.image_filepath,
            output_filepath=args.output_filepath,
            num_refinements=args.num_refinements,
            model_type=args.model_type,
            workspace_dir=args.workspace_dir,
            auto_approve=args.auto_approve,
        )
    elif args.command == "continue":
        from cad3dify import continue_workflow

        continue_workflow(
            workspace_dir=args.workspace_dir,
            auto_approve=args.auto_approve,
            until_stage=args.until_stage,
        )
    elif args.command == "run-step":
        from cad3dify import run_single_stage

        run_single_stage(args.workspace_dir, args.stage)
    elif args.command == "legacy-run":
        from cad3dify import generate_step_from_2d_cad_image

        generate_step_from_2d_cad_image(
            image_filepath=args.image_filepath,
            output_filepath=args.output_filepath,
            num_refinements=args.num_refinements,
            model_type=args.model_type,
            workspace_dir=args.workspace_dir,
            auto_approve=args.auto_approve,
        )


if __name__ == "__main__":
    main()
