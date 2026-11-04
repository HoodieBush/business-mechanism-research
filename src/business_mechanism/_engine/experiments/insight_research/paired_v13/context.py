from copy import deepcopy
from ..common import encoded
from ..paired_v12.journal_memory import rebuild_from_owned_journal
from token_budget import reservation_bound

def compact_with_admission(runtime,parent_compact):
    original=deepcopy(runtime.cp['messages'])
    parent_compact()
    payload=runtime.payload();remaining=runtime.journal.snapshot()['remaining_admission_tokens']
    if len(encoded(payload).encode())>runtime.ws.settings['limits']['max_request_bytes'] or reservation_bound(payload)>remaining:
        # Preserve the full pre-compaction conversation in the exact own archive.
        # No scientific record, paid count or result-incorporation state changes.
        runtime.cp['messages']=original
        rebuild_from_owned_journal(runtime)
