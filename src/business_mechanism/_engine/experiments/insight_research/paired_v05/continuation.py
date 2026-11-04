"""Explicit local-allocation extension inside the unchanged project authority."""
from copy import deepcopy
import json
from pathlib import Path
from ..common import ROOT,sha,write_json,encoded
from ..paired_v03.continuation import prepare as previous_prepare
from ..paired_v01.budget import StudyBudget,SharedTokenBudget


def prepare(output,manifest,question,world,settings,identity,*,base=ROOT):
    old_limit=manifest['parent_budget_identity']['token_allowance'];new_limit=identity['token_allowance']
    if new_limit<old_limit:raise ValueError('continuation cannot remove inherited allocation')
    project=SharedTokenBudget(settings['model_config']['token_budget_pointer'])
    if identity['project_budget_id']!=project.auth['id'] or new_limit>project.auth['limit_tokens']:
        raise ValueError('local plan cannot create a new project authorization')
    old_settings=deepcopy(settings);old_settings['limits']['token_allowance']=old_limit
    old_identity={**identity,'token_allowance':old_limit}
    previous_prepare(output,manifest,question,world,old_settings,old_identity,base=base)
    output=Path(output).resolve();migrations=[]
    paths=[output/'researcher/private/identity.json',*output.glob('reviews/*/critic/private/identity.json')]
    for path in paths:
        before=json.loads(path.read_text());updated=deepcopy(before)
        if before['settings']['limits']['token_allowance']!=old_limit:raise ValueError('inherited role token ceiling differs')
        updated['settings']['limits']['token_allowance']=new_limit
        archive=path.with_name('preallocation_identity.json');write_json(archive,before);write_json(path,updated)
        migrations.append({'path':str(path.relative_to(output)),'before_sha256':sha(archive),'after_sha256':sha(path)})
    budget=StudyBudget(output/'common_budget.sqlite',old_identity);before=budget.snapshot()
    with budget.connect() as db:
        db.execute('BEGIN IMMEDIATE');attempts=db.execute('SELECT * FROM attempts').fetchall()
        db.execute('UPDATE identity SET body=?',(encoded(identity),))
        if db.execute('SELECT * FROM attempts').fetchall()!=attempts:raise ValueError('allocation migration changed charges')
    after=StudyBudget(output/'common_budget.sqlite',identity).snapshot()
    for key in ('accounted_tokens','reported_tokens','unknown_reserve','http_attempts'):
        if before[key]!=after[key]:raise ValueError('allocation migration reset '+key)
    write_json(output/'allocation_migration.json',{'old_local_cap':old_limit,'new_local_cap':new_limit,
        'same_project_id':project.auth['id'],'project_authorization_unchanged':True,'old_usage':before,'new_usage':after,
        'identity_migrations':migrations,'scope':'New frozen local plan only. Original runs, scientific records, paid work, requests and project ledger are not rewritten/reset.'})
