"""Read-only evidence export for the method-adoption study.

It never runs Actor code, calls a model, fills a scientific grade, or changes the
frozen study. Full comparison export requires the complete terminal task matrix.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read_jsonl(path):
    if not path.exists():
        return [], False
    raw = path.read_text()
    rows = []
    lines = raw.splitlines()
    for number, line in enumerate(lines):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            if number == len(lines)-1 and not raw.endswith('\n'):
                return rows, True  # An observation race, not a repaired record.
            raise
    return rows, False


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def usage(records):
    known = []
    for record in records:
        response = record.get('response')
        value = response.get('usage') if isinstance(response, dict) else None
        if value:
            known.append(value)
    return {'returned_attempts': len(records),
            'reported_tokens': sum(u.get('total_tokens', 0) for u in known),
            'reported_prompt_tokens': sum(u.get('prompt_tokens', 0) for u in known),
            'reported_completion_tokens': sum(u.get('completion_tokens', 0) for u in known),
            'returned_without_usage': len(records)-len(known),
            'unknown_usage_estimate_not_measured': sum(r.get('admission_estimate', 0) for r in records
                if not isinstance(r.get('response'), dict) or not r['response'].get('usage')),
            'local_cache_hits': sum(bool(r.get('cache_hit')) for r in records),
            'summed_request_seconds_not_wall_clock': sum(r.get('elapsed_seconds', 0) for r in records)}


def collect(root, observe=False):
    root = Path(root).resolve()
    if not root.is_relative_to(ROOT/'experiments/business_team/results'):
        raise ValueError('study must be inside this project results directory')
    manifest = json.loads((root/'manifest.json').read_text())
    expected = manifest['specification']['execution_order']
    records = {r['id']: r for r in manifest['cases']}
    calls, partial_call = read_jsonl(root/'model_calls.jsonl')
    starts, partial_start = read_jsonl(root/'requests_started.jsonl')
    returned = {r['request_index'] for r in calls}
    pending = [r['request_index'] for r in starts if r['request_index'] not in returned]
    if not observe:
        if manifest['status'] not in ('delivered_pending_scientific_review', 'completed_with_failures'):
            raise ValueError('full comparison export requires terminal study; use --observe for protocol counts only')
        if set(records) != set(expected):
            raise ValueError('terminal record does not cover the entire preregistered matrix')
        if pending or partial_call or partial_start:
            raise ValueError('terminal accounting still has pending or incomplete journal entries')
    corrupt = []
    for filename, expected_sha in manifest['source_sha256'].items():
        if digest(root/'snapshot'/filename) != expected_sha:
            corrupt.append('source_snapshot:'+filename)
    for group in ('public_input_sha256', 'private_input_sha256'):
        for filename, expected_sha in manifest[group].items():
            if digest(root/filename) != expected_sha:
                corrupt.append(group+':'+filename)
    if corrupt:
        raise ValueError('frozen evidence changed: '+str(corrupt))
    current_source_changes = [name for name, value in manifest['source_sha256'].items()
                              if not (ROOT/name).exists() or digest(ROOT/name) != value]
    report = {'observed_at_utc': datetime.now(timezone.utc).isoformat(),
              'evidence_exporter': {'path': str(Path(__file__).resolve()), 'sha256': digest(Path(__file__))},
              'scope': 'Protocol observation only; no scientific grades or arm-effect inference.' if observe else
                       'Frozen complete evidence bundle for subsequent manual scientific review; delivery is not correctness.',
              'manifest_status': manifest['status'], 'expected_executions': len(expected),
              'recorded_execution_statuses': {name: records.get(name, {}).get('status', 'not_recorded') for name in expected},
              'usage': usage(calls), 'started_requests_not_returned': pending,
              'partial_journal_observation': partial_call or partial_start,
              'source_snapshots_checked': len(manifest['source_sha256']),
              'public_inputs_checked': len(manifest['public_input_sha256']),
              'private_inputs_checked': len(manifest['private_input_sha256']),
              'current_checkout_source_changes': current_source_changes,
              'scientific_review': 'not_performed',
              'independence_note': 'Four question types, M01/M04 share data; eight executions are not eight independent worlds.'}
    if observe:
        return report
    cases = []
    for name in expected:
        directory = root/name
        tools, partial = read_jsonl(directory/'framework_tools.jsonl')
        if partial:
            raise ValueError('incomplete terminal tool journal')
        actor_calls = [c for c in calls if (c.get('task') or {}).get('case_id') == name]
        papers, executions = [], []
        for event in tools:
            feedback = event['feedback']
            result = feedback.get('result', {})
            if event['tool'] == 'read_artifact' and feedback['ok']:
                path = Path(result['path'])
                if path.is_relative_to(directory/'public/literature'):
                    papers.append({'path': str(path), 'sha256': result['sha256'],
                                   'offset': event['arguments'].get('offset', 0),
                                   'returned_text_characters': len(result.get('text', '')),
                                   'note': 'Text exposure, not proof of comprehension or method adoption.'})
            if event['tool'] == 'run_python' and feedback['ok']:
                path = Path(result['code_file'])
                executions.append({'code_file': str(path), 'code_sha256': digest(path),
                                   'execution_id': result.get('execution_id'), 'execution_ok': result.get('ok'),
                                   'execution_receipt': result.get('execution_receipt'),
                                   'purpose': event['arguments']['purpose'],
                                   'output_semantics': event['arguments']['output_semantics'],
                                   'source_reads': result.get('source_reads', []),
                                   'note': 'Inspect actual code/outputs for ordinary Python paper reads; not all text reads are instrumented.'})
        cases.append({'id': name, 'status': records[name]['status'], 'usage': usage(actor_calls),
                      'original_task': json.loads((directory/'public/task.json').read_text()),
                      'actor_result': records[name].get('result'),
                      'failure': {k: records[name][k] for k in ('error_type', 'error') if k in records[name]},
                      'tool_counts': dict(Counter(t['tool'] for t in tools)),
                      'outer_tool_failures': [t for t in tools if not t['feedback']['ok']],
                      'python_executions': executions, 'paper_text_exposures': papers,
                      'scientific_review': {'status': 'not_reviewed', 'estimand_and_measurement': None,
                          'independent_unit_and_method_conditions': None, 'numerical_reproduction': None,
                          'conclusion_calibration': None, 'source_support_if_used': None,
                          'material_errors_and_uncertainty': None}})
    report['cases'] = cases
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', required=True)
    parser.add_argument('--observe', action='store_true')
    args = parser.parse_args()
    result = collect(args.root, args.observe)
    output = Path(args.root)/('protocol_observation.json' if args.observe else 'analysis/evidence_bundle.json')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({k: v for k, v in result.items() if k != 'cases'}, ensure_ascii=False))
