"""Registered study entry point. No implicit budget allocation or old-run reopen."""
from __future__ import annotations
import argparse
import importlib.util
import json
from pathlib import Path
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from experiments.insight_research.common import ROOT, write_json
from experiments.insight_research.runtime import Runtime
from experiments.insight_research.workspace import Workspace
from world import OfficeWorld


def main(workspace_class=Workspace, runtime_class=Runtime, world_factory=OfficeWorld, prepare_workspace=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--study-id', required=True)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--steps', type=int, default=8)
    args = parser.parse_args()
    module_spec = importlib.util.spec_from_file_location('study_workflow', ROOT / 'scripts/research_workflow.py')
    workflow = importlib.util.module_from_spec(module_spec); module_spec.loader.exec_module(workflow)
    plan_path, study = workflow.verify(ROOT, args.study_id)
    if (plan_path.parent / 'decision.json').exists(): raise ValueError('closed registered study cannot resume')
    run = next(r for r in study['execution']['runs'] if r['id'] == args.run_id)
    receipt = json.loads((plan_path.parent / 'executions' / (args.run_id + '.json')).read_text())
    if receipt.get('study_id') != args.study_id or receipt.get('run_id') != args.run_id:
        raise ValueError('registry launch receipt required')
    if not args.resume and receipt['status'] != 'started': raise ValueError('new entry requires a current registry launch')
    spec_path = workflow.local(ROOT, study['execution']['research_config'])
    if str(spec_path.relative_to(ROOT)) not in study['execution']['files']:
        raise ValueError('research configuration must be frozen')
    spec = json.loads(spec_path.read_text())
    model_path = workflow.local(ROOT, spec['model_config_file'])
    if str(model_path.relative_to(ROOT)) not in study['execution']['files']:
        raise ValueError('model configuration must be frozen')
    model = json.loads(model_path.read_text())
    settings = {k: spec[k] for k in ('research_profile', 'verification_mode', 'limits')}
    settings['model_config'] = model
    if 'initialization' in spec: settings['experiment_initialization'] = spec['initialization']
    if 'continuation' in spec:
        settings['continuation'] = spec['continuation']
        manifest_path = workflow.local(ROOT, spec['continuation']['manifest'])
        if str(manifest_path.relative_to(ROOT)) not in study['execution']['files']:
            raise ValueError('continuation manifest must be frozen')
        manifest = json.loads(manifest_path.read_text())
        parent = workflow.local(ROOT, manifest['parent_workspace'])
        inherited = {str(workflow.local(parent, name).relative_to(ROOT)) for name in manifest['sha256']}
        if not inherited <= set(study['execution']['files']):
            raise ValueError('every inherited snapshot input must be frozen and archived')
    output = plan_path.parent / 'results' / args.run_id
    world = world_factory(**spec['environment'])
    workspace = workspace_class(output / 'case' / 'workspace', spec['question'], world, settings, reopen=args.resume)
    try:
        if prepare_workspace: prepare_workspace(workspace, spec)
        result = runtime_class(workspace, model).run(args.steps)
        write_json(output / 'runtime_status.json', result)
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result['status'] == 'completed' else 3
    finally: workspace.close()


if __name__ == '__main__': raise SystemExit(main())
