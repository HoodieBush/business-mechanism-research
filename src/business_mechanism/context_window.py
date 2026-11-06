"""Bound active navigation; exact role-owned transcripts remain paged on disk."""
from experiments.insight_research.common import Pending, digest, encoded, write_json
from token_budget import reservation_bound


def compact(runtime):
    ws = runtime.ws; cp = runtime.cp; journal = runtime.journal
    if cp.get('pending') or journal.state.get('inflight') or journal.state.get('delivery'):
        raise Pending('drain paid work before context rebuild')
    messages = cp['messages']; archive = digest(messages); folder = ws.private/'context_archives'
    write_json(folder/(archive+'.json'), messages)
    write_json(folder/'latest.json', {'archive_id': archive, 'read_ref': 'own_context:'+archive,
        'last_model_response': cp['responses'], 'no_scientific_summary_generated': True,
        'no_results_marked_incorporated': True})
    starts = [i for i,m in enumerate(messages) if i >= 2 and m['role'] == 'assistant']
    for count in range(min(len(starts), ws.settings['limits']['recent_turns']), -1, -1):
        rebuilt = runtime.initial()+(messages[starts[-count]:] if count else [])
        if not count:
            rebuilt.append({'role': 'user', 'content': encoded({'exact_previous_window': 'own_context:'+archive,
                'latest_paid_response': 'own_process:'+str(cp['responses']),
                'policy': 'All paid tools have drained. Read the exact owned window/process and artifacts by pages. No finding or counterevidence was discarded or automatically incorporated.'})})
        payload = runtime.payload(rebuilt)
        if len(encoded(payload).encode()) < ws.settings['limits']['max_request_bytes']*.80 and reservation_bound(payload) <= journal.snapshot()['remaining_admission_tokens']:
            cp['messages'] = rebuilt; cp['context_windows'] = cp.get('context_windows',0)+1
            cp['journal_recovery'] = {'archive_id': archive, 'retained_complete_recent_turns': count, 'summary_generated': False}
            runtime.save(); return
    raise Pending('bounded fixed context cannot fit; exact archive retained')
