"""Explicit common review-capacity migration; paid work/counters/deadline persist."""
import json,sqlite3
from pathlib import Path
from ..common import ROOT,sha,write_json
from ..paired_v05.continuation import prepare as previous_prepare
from ..paired_v01.budget import StudyBudget

def prepare(output,manifest,question,world,settings,identity,*,base=ROOT):
    previous_prepare(output,manifest,question,world,settings,identity,base=base)
    output=Path(output).resolve();parent=Path(base)/manifest['parent_root'];migrations=[]
    for path in output.glob('reviews/*/critic/private/identity.json'):
        body=json.loads(path.read_text());old=body['settings']['limits']['max_http_attempts']
        if old>18:raise ValueError('registered review capacity cannot shrink')
        before=path.with_name('pre_review_capacity_identity.json');write_json(before,body)
        body['settings']['limits']['max_http_attempts']=18;write_json(path,body)
        migrations.append({'path':str(path.relative_to(output)),'old_http_cap':old,'new_http_cap':18,'before_sha256':sha(before),'after_sha256':sha(path)})
    with sqlite3.connect((parent/'common_budget.sqlite').resolve().as_uri()+'?mode=ro',uri=True) as source,sqlite3.connect(output/'common_budget.sqlite') as dest:
        rows=source.execute('SELECT * FROM execution_control').fetchall()
        dest.execute('CREATE TABLE execution_control(id INTEGER PRIMARY KEY,started REAL,deadline REAL,fingerprint TEXT,last_progress_request INTEGER)')
        dest.executemany('INSERT INTO execution_control VALUES (?,?,?,?,?)',rows)
        if dest.execute('SELECT * FROM execution_control').fetchall()!=rows:raise ValueError('persistent control/deadline changed')
    after=StudyBudget(output/'common_budget.sqlite',identity).snapshot()
    if after['http_attempts']!=manifest['inherited_attempts'] or after['accounted_tokens']!=manifest['inherited_tokens']:raise ValueError('common cumulative usage lost')
    write_json(output/'review_capacity_migration.json',{'role_identity_migrations':migrations,'all_role_counters_unchanged':True,
        'scientific_records_and_raw_paid_work_unchanged':True,'persistent_deadline_and_progress_retained':True,'execution_control':rows,
        'no_new_project_authority':True,'same_case_not_new_sample':True})
