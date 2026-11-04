"""business-research: create, run/resume, inspect and cooperatively pause."""
import argparse
import json
from pathlib import Path
from .service import create_project, run_project, project_status, request_pause


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    create = sub.add_parser('create')
    create.add_argument('project', type=Path); create.add_argument('--question', required=True)
    create.add_argument('--model-config', type=Path, required=True)
    group = create.add_mutually_exclusive_group(required=True)
    group.add_argument('--data', type=Path); group.add_argument('--demo', action='store_true')
    create.add_argument('--tokens', type=int, default=2000000); create.add_argument('--requests', type=int, default=80)
    create.add_argument('--wall-seconds', type=int, default=7200); create.add_argument('--max-stages', type=int, default=2)
    run = sub.add_parser('run'); run.add_argument('project', type=Path)
    run.add_argument('--stages', type=int, default=1); run.add_argument('--resume', action='store_true')
    for name in ('status', 'pause', 'report'):
        sub.add_parser(name).add_argument('project', type=Path)
    args = parser.parse_args()
    if args.command == 'create':
        result = create_project(args.project, args.question, json.loads(args.model_config.read_text()),
            data=args.data, demo={'seed': 7349, 'entry_rate': 20, 'completion_probability': .55, 'recording_probability': .97} if args.demo else None,
            limits={'token_allowance': args.tokens, 'max_http_attempts': args.requests}, wall_seconds=args.wall_seconds, max_stages=args.max_stages)
    elif args.command == 'run':
        result = run_project(args.project, stages=args.stages, resume=args.resume)
    elif args.command == 'pause':
        request_pause(args.project); result = {'status': 'pause_requested', 'when': 'after current paid tool batch drains'}
    elif args.command == 'report':
        from .delivery import export_saved_progress
        result = {'status': 'exported', 'path': export_saved_progress(args.project),
                  'scientific_certification': False}
    else:
        result = project_status(args.project)
    print(json.dumps(result, ensure_ascii=False, default=str))
    return 3 if result.get('status') == 'pending' else 0


def entry():
    try:
        return main()
    except (ValueError, RuntimeError, OSError) as error:
        print(json.dumps({'status': 'error', 'error_type': type(error).__name__, 'reason': str(error)}, ensure_ascii=False))
        return 2


if __name__ == '__main__':
    raise SystemExit(entry())
