"""Registered M0 paid entry: explicit project ledger and one finite task/run."""
import argparse
import importlib.util
import json
from pathlib import Path

from ..common import ROOT, sha, write_json
from .runtime import CriticRuntime
from .workspace import CriticWorkspace
from .continuation import prepare as prepare_continuation


def allocation(study, manifest):
    tasks = {x['id']: x for x in manifest['tasks']}
    if len(tasks) != len(manifest['tasks']): raise ValueError('duplicate M0 task IDs')
    for task in tasks.values():
        allowance = task['limits']['token_allowance']
        attempts = task['limits']['max_http_attempts']
        if type(allowance) is not int or not 0 < allowance <= 1000000:
            raise ValueError('positive bounded allowance required for every task')
        ceiling = 12 if task.get('continuation') else 6
        if type(attempts) is not int or not 0 < attempts <= ceiling:
            raise ValueError('M0 initial/continuation cumulative HTTP attempt ceiling exceeded')
    assigned = []
    total = 0
    for run in study['execution']['runs']:
        if len(run['task_ids']) != 1 or run.get('replicate_id') != 0:
            raise ValueError('M0 admits one task per run and one registered execution per task')
        task = run['task_ids'][0]
        if task not in tasks: raise ValueError('unknown M0 task')
        assigned.append(task); total += tasks[task]['limits']['token_allowance']
    if len(assigned) != len(set(assigned)) or set(assigned) != set(tasks):
        raise ValueError('each M0 task must have exactly one bounded allocation')
    if not (0 < total <= manifest['phase_token_cap'] <= 1000000):
        raise ValueError('M0 all-role phase total must fit its 1,000,000-token allocation')
    if total != manifest['all_role_allowances_sum']: raise ValueError('allocation sum disagrees')
    return tasks


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--study-id', required=True); parser.add_argument('--run-id', required=True)
    parser.add_argument('--resume', action='store_true'); parser.add_argument('--steps', type=int, default=6)
    args = parser.parse_args()
    module_spec = importlib.util.spec_from_file_location('critic_study_workflow', ROOT / 'scripts/research_workflow.py')
    workflow = importlib.util.module_from_spec(module_spec); module_spec.loader.exec_module(workflow)
    path, study = workflow.verify(ROOT, args.study_id)
    if (path.parent / 'decision.json').exists(): raise ValueError('closed M0 study cannot reopen')
    execution = study['execution']
    if execution.get('phase') not in ('M0_real_review', 'M0_review_continuation'): raise ValueError('explicit M0 phase required')
    manifest = json.loads(workflow.local(ROOT, execution['task_manifest']).read_text())
    tasks = allocation(study, manifest)
    run = next(x for x in execution['runs'] if x['id'] == args.run_id)
    receipt = json.loads((path.parent / 'executions' / (args.run_id + '.json')).read_text())
    if receipt.get('study_id') != args.study_id or receipt.get('run_id') != args.run_id:
        raise ValueError('registry launch receipt required')
    if not args.resume and receipt['status'] != 'started': raise ValueError('new registered launch required')
    task = tasks[run['task_ids'][0]]
    model_path = workflow.local(ROOT, manifest['model_config_file'])
    if manifest['model_config_file'] not in execution['files']: raise ValueError('model configuration must be frozen')
    model = json.loads(model_path.read_text())
    if model.get('token_budget_pointer') != str((ROOT / 'experiments/budgets/USER-20261022-CRITIC-10M/pointer.json').resolve()):
        raise ValueError('explicit critic project budget pointer required')
    snapshot = workflow.local(ROOT, task['snapshot'])
    declared = set(execution['files'])
    inputs = [snapshot / 'manifest.json'] + [snapshot / p for p in json.loads((snapshot / 'manifest.json').read_text())['files_sha256']]
    if not {str(p.relative_to(ROOT)) for p in inputs} <= declared: raise ValueError('every projected evidence input must be frozen')
    if sha(snapshot / 'manifest.json') != task['manifest_sha256']: raise ValueError('evidence manifest changed')
    settings = {'research_profile': 'critic_m0_v1', 'limits': task['limits'], 'model_config': model}
    output = path.parent / 'results' / args.run_id
    continuation = task.get('continuation')
    if bool(continuation) != (execution['phase'] == 'M0_review_continuation'):
        raise ValueError('continuation requires an explicit registered continuation phase')
    if continuation:
        manifest_path = workflow.local(ROOT, continuation['manifest'])
        if continuation['manifest'] not in declared or sha(manifest_path) != continuation['sha256']:
            raise ValueError('frozen critic continuation manifest required')
        parent_manifest = json.loads(manifest_path.read_text())
        parent = workflow.local(ROOT, parent_manifest['parent_root'])
        if not {str((parent / p).relative_to(ROOT)) for p in parent_manifest['sha256']} <= declared:
            raise ValueError('all inherited critic originals must be frozen')
        if not args.resume: prepare_continuation(output / 'critic', snapshot, settings, parent_manifest)
    ws = CriticWorkspace(output / 'critic', snapshot, settings, reopen=args.resume or bool(continuation))
    try:
        result = CriticRuntime(ws, model).run(args.steps)
        write_json(output / 'runtime_status.json', result)
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result['status'] == 'completed' else 3
    finally: ws.close()


if __name__ == '__main__': raise SystemExit(main())
