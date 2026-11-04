"""Comparable process/accounting evidence; scientific judgments are separate."""
import argparse
import json
from pathlib import Path
import sqlite3

from ..common import write_json


def summarize(study_root):
    root=Path(study_root).resolve();rows=[]
    for output in sorted((root/'results').iterdir()):
        owner=output/'researcher/private/records.sqlite';budget=output/'common_budget.sqlite'
        if not owner.exists() or not budget.exists():continue
        with sqlite3.connect(owner.as_uri()+'?mode=ro',uri=True) as db:
            counts=dict(db.execute('SELECT kind,count(*) FROM records GROUP BY kind'))
            identity=json.loads((output/'researcher/private/identity.json').read_text())
            jobs=dict(db.execute('SELECT status,count(*) FROM review_jobs GROUP BY status'))
        with sqlite3.connect(budget.as_uri()+'?mode=ro',uri=True) as db:
            roles=[{'role':role,'attempts':n,'accounted_tokens':tokens,'unknown_reserve':unknown}
                for role,n,tokens,unknown in db.execute('SELECT role,count(*),coalesce(sum(coalesce(actual,bound)),0),coalesce(sum(case when actual is null then bound else 0 end),0) FROM attempts GROUP BY role')]
        status=json.loads((output/'runtime_status.json').read_text()) if (output/'runtime_status.json').exists() else {'status':'not_recorded'}
        rows.append({'run_id':output.name,'mode':identity['settings']['verification_mode'],'runtime':status,'records':counts,'review_jobs':jobs,
            'roles':roles,'total_tokens':sum(x['accounted_tokens'] for x in roles),'total_http_attempts':sum(x['attempts'] for x in roles)})
    result={'runs':rows,'scientific_audit_required':True,'counts_are_not_quality_scores':True}
    write_json(root/'process_summary.json',result);return result


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--study-root',required=True)
    print(json.dumps(summarize(parser.parse_args().study_root),ensure_ascii=False))
