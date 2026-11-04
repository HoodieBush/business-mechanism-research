"""Process evidence only. Scientific correctness needs separate source review."""
import argparse
import json
from pathlib import Path
import sqlite3

from ..common import write_json


def summarize(study_root):
    root = Path(study_root).resolve(); rows = []
    for path in sorted((root / 'results').glob('*/critic/private/critic.sqlite')):
        private = path.parent
        with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) as db:
            reviews = [json.loads(x[0]) for x in db.execute("SELECT body FROM records WHERE kind='review'")]
            counts = dict(db.execute("SELECT json_extract(body,'$.tool'),count(*) FROM actions GROUP BY json_extract(body,'$.tool')"))
        transport = json.loads((private / 'transport.json').read_text()) if (private / 'transport.json').exists() else {}
        prior = json.loads((private / 'continuation.json').read_text()) if (private / 'continuation.json').exists() else {}
        rows.append({'run_id': path.parents[2].name, 'complete_reviews': len(reviews),
            'review_refs': [x['ref'] for x in reviews], 'actions': counts,
            'http_attempts': transport.get('attempts', 0), 'accounted_tokens': transport.get('accounted_tokens', 0),
            'new_http_attempts': transport.get('attempts', 0) - prior.get('inherited_http_attempts', 0),
            'new_accounted_tokens': transport.get('accounted_tokens', 0) - prior.get('inherited_accounted_tokens', 0),
            'inflight': bool(transport.get('inflight')), 'unacknowledged_delivery': bool(transport.get('delivery'))})
    result = {'runs': rows, 'total_http_attempts': sum(x['http_attempts'] for x in rows),
        'total_accounted_tokens': sum(x['accounted_tokens'] for x in rows),
        'total_new_http_attempts': sum(x['new_http_attempts'] for x in rows),
        'total_new_accounted_tokens': sum(x['new_accounted_tokens'] for x in rows),
        'scientific_audit_required': True, 'autonomous_discovery_tested': False, 'online_correction_tested': False}
    write_json(root / 'process_summary.json', result)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--study-root', required=True)
    print(json.dumps(summarize(parser.parse_args().study_root), ensure_ascii=False))
