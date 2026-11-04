"""Execute teaching examples against native SQLite, sandbox, peer and report flow."""
import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
from unittest.mock import patch

from ..common import ROOT, Pending, digest, encoded, now, sha, write_json
from ..fusion_rsi_v01.acceptance import config as base_config
from ..growth_probe_v01.environment import World
from .workspace import ResearchWorkspace
from ..paired_v01.budget import SharedTokenBudget, StudyBudget
from .review import Reviewer
from ..runtime_memory import reconstruct_request
from .examples import examples, substitute
from .prompts import compose, source_identity
from .runtime import ResearchRun, ReviewerRuntime


def config():
    cfg = base_config()
    cfg.update(experience_mode='none', project_archives=[], verification_mode='independent',
               prompt_runtime_sources=source_identity(), initialization_notice='Engineering protocol fixture; no scientific discovery claim.')
    return cfg


def setup(folder, cfg=None):
    cfg = cfg or config()
    world = World(seed=19781, entry_rate=20, completion_probability=.6, recording_probability=.99)
    ws = ResearchWorkspace(folder/'actor/researcher', 'Engineering: exercise native tool submissions and versioned repair.', world, cfg)
    budget = StudyBudget(folder/'actor/common_budget.sqlite',
        {'token_allowance':cfg['limits']['token_allowance'], 'max_http_attempts':cfg['limits']['max_http_attempts'],
         'project_budget_id':'USER-20261022-CRITIC-10M', 'scope':'zero-provider engineering fixture'}, create=True)
    return ws, ResearchRun(folder/'actor', ws, cfg['model_config'], budget)


def main(output):
    output = output.resolve(); output.mkdir(parents=True, exist_ok=False)
    pointer = ROOT/'experiments/budgets/USER-20261022-CRITIC-10M/pointer.json'
    before = SharedTokenBudget(pointer).snapshot()
    checks = []
    for role, cls in [('researcher',ResearchWorkspace), ('critic',Reviewer)]:
        for label, name, args in examples(role):
            cls.tools[name][0].model_validate(args)
        checks.append({'check':role+'_schema_examples','count':len(examples(role)),'passed':True})
    ws, run = setup(output/'pipeline')
    serial = [0]
    def call(workspace, name, args):
        serial[0] += 1
        value = workspace.call(name, args, 'prompt-example-'+str(serial[0]))
        if value.get('ok') is False:
            raise AssertionError((name, value))
        return value
    templates = {key:(name,args) for key,name,args in examples('researcher')}
    mapping = {}
    def use(label, overrides=None):
        name, args = templates[label]
        body = substitute(args, mapping)
        if overrides: body.update(overrides)
        return call(ws, name, body)
    try:
        receipt = use('context')
        assert 'context_location' in receipt
        ctx = ws.context()
        public = next(x['ref'] for x in ctx['public_files'] if Path(x['path']).name=='business_brief.md')
        mapping['file:EXAMPLE_PUBLIC'] = public
        use('read')
        query = use('query'); data_ref = query['file']['ref']
        data_path = str(ws.file(data_ref)[0])
        mapping.update({'file:EXAMPLE_DATA':data_ref, 'EXAMPLE_COMPUTE_PATH':data_path})
        compute = use('compute'); assert compute['execution']['ok'], compute
        use('collect')
        h = use('hypothesis'); mapping['H_EXAMPLE'] = h['ref']
        p = use('plan'); mapping['P_EXAMPLE'] = p['ref']
        r = use('test'); assert r['ok']; mapping['R_EXAMPLE'] = r['ref']
        assert use('test')['ref']==r['ref']  # no duplicate physical observation
        a = use('assessment'); mapping['A_EXAMPLE'] = a['ref']
        use('state'); assert not ws.unincorporated()
        rejected_write=use('knowledge',{'knowledge_updates':[{**substitute(templates['knowledge'][1]['knowledge_updates'][0],mapping),'status':'supported_in_scope'}]})
        assert not rejected_write['knowledge_refs'] and rejected_write['knowledge_rejections']
        diagnostic=ws.context()['latest_memory_write_receipt']
        assert diagnostic['state_ref']==rejected_write['ref'] and not diagnostic['created_memory_refs'] and diagnostic['knowledge_rejections']
        saved = use('knowledge'); k = saved['knowledge_refs'][0]; mapping['K_EXAMPLE'] = k
        diagnostic=ws.context()['latest_memory_write_receipt']
        assert diagnostic['created_memory_refs']==[k] and not diagnostic['knowledge_rejections']
        checks.append({'check':'partial_memory_write_receipt_and_actual_recovery','passed':True,'failed_state_ref':rejected_write['ref'],'actual_new_knowledge_ref':k})
        use('search'); use('read_memory')
        job = next(j for j in ws.jobs() if j['target_ref']==a['ref'])
        mapping['J_EXAMPLE'] = job['ref']; use('request')
        inputs = run.prepare_job(job)
        peer = Reviewer(output/'pipeline/actor/reviews'/job['ref']/'critic', inputs,
                        {'research_profile':'paired_critic_v1','model_config':run.model,'limits':ws.settings['limits']})
        try:
            peer_journal = run.reviewer_journal_factory(peer, job)
            peer_runtime = ReviewerRuntime(peer, run.model, journal=peer_journal)
            peer_runtime.cp['messages'] = peer_runtime.initial()
            peer_payload = peer_runtime.payload()
            assert peer_payload['messages'][0]['content']==compose('critic')
            peer_journal.persist_request(1, peer_payload)
            assert reconstruct_request(peer.private,1)==peer_payload
            assert len(peer_payload['tools'])==7
            peer_mapping = {**mapping, 'EXAMPLE_COMPUTE_PATH':str(peer.view.file(data_ref)[0])}
            peer_templates = {key:(name,args) for key,name,args in examples('critic')}
            def peer_use(label):
                name,args=peer_templates[label]
                return call(peer,name,substitute(args,peer_mapping))
            peer_use('directory'); peer_use('target'); peer_use('search'); peer_use('source'); peer_use('query')
            assert peer_use('compute')['execution']['ok']
            read = call(peer,'read_memory',{'ref':k})
            peer_mapping['check:EXAMPLE_READ'] = read['action_ref']
            _, good = peer_templates['review_issue']
            good = substitute(good,peer_mapping)
            for invalid_kind in ('file_as_affected_object','owner_action_as_critic_action'):
                bad = deepcopy(good)
                if invalid_kind=='file_as_affected_object':
                    bad['issues'][0]['affected_refs']=[data_ref]
                else:
                    bad['issues'][0]['action_refs']=['action:1']
                serial[0] += 1
                rejected = peer.call('record_review',bad,'typed-rejection-'+str(serial[0]))
                assert rejected.get('ok') is False and 'field' in rejected['error'],rejected
                checks.append({'check':invalid_kind+'_precise_repair_feedback','passed':True,'receipt':rejected})
            assert 'ref' in peer_use('review_issue')
            run.import_feedback(job,peer)
        finally:peer.close()
        mapping['Q_EXAMPLE'] = ws.job(job['ref'])['review_ref']
        revised = use('knowledge',{'knowledge_updates':[{**substitute(templates['knowledge'][1]['knowledge_updates'][0],mapping),
             'statement':'Engineering replacement scoped to actually received data.', 'supersedes_ref':k,
             'revision_reason':'Explicitly replace the fixture object identified by the peer.'}]})
        new_k = revised['knowledge_refs'][0]; mapping['K_EXAMPLE_REVISED'] = new_k
        response = use('response'); assert response.get('ref'), response
        assert ws.review(k)['status']!='active'
        assert ws.record(new_k)['supersedes_ref']==k
        assert not ws.unanswered()
        checks.append({'check':'native_examples_research_peer_response_memory_repair','passed':True,
                       'hypothesis':h['ref'],'plan':p['ref'],'result':r['ref'],'assessment':a['ref'],
                       'old_memory':k,'new_memory':new_k,'response':response['ref']})
        checks.append({'check':'actual_critic_composition_seven_tools_and_archive','passed':True})

        # A report draft is submitted with native covered/uncovered hypothesis sets.
        draft = use('finish')
        assert draft['record_type']=='report_draft', draft
        djob = next(j for j in ws.jobs() if j['target_ref']==draft['ref'])
        inputs = run.prepare_job(djob)
        peer = Reviewer(output/'pipeline/actor/reviews'/djob['ref']/'critic',inputs,
                        {'research_profile':'paired_critic_v1','model_config':run.model,'limits':ws.settings['limits']})
        try:
            got = call(peer,'read_memory',{'ref':draft['ref']})
            name,args=next((n,a0) for label,n,a0 in examples('critic') if label=='review_clean')
            body=substitute(args,{**mapping,'A_EXAMPLE':draft['ref'],'check:EXAMPLE_READ':got['action_ref']})
            call(peer,name,body);run.import_feedback(djob,peer)
        finally:peer.close()
        with ws.db:ws.try_seal_report()
        assert ws.report(), 'native reviewed report did not seal'
        checks.append({'check':'native_report_draft_review_seal','passed':True,'report_ref':ws.report()['ref']})
    finally:ws.close()

    # The model-facing composition and persistence must be actual runtime paths.
    ws, run = setup(output/'wire')
    try:
        run.runtime.cp['messages'] = run.runtime.initial(); run.runtime.save()
        payload = run.runtime.payload()
        assert payload['messages'][0]['content']==compose('researcher')
        assert payload['max_tokens']==65536 and payload['thinking']['type']=='enabled'
        run.journal.persist_request(1,payload)
        assert reconstruct_request(ws.private,1)==payload
        checks.append({'check':'actual_composed_prompt_on_wire_and_exact_archive','passed':True,
                       'prompt_bytes':len(compose('researcher').encode()),'tools':len(payload['tools'])})
        with run.budget.connect() as db:db.execute('UPDATE execution_control SET deadline=0 WHERE id=1')
        with patch('experiments.insight_research.paired_v01.budget.request_model',side_effect=AssertionError('provider forbidden')) as transport:
            try:run.journal.call(payload)
            except Pending:pass
            else:raise AssertionError('expired deadline not enforced')
        assert transport.call_count==0
        checks.append({'check':'guarded_layout_journal_enforces_persistent_deadline','passed':True})
    finally:ws.close()
    ws, run = setup(output/'progress')
    try:
        payload=run.runtime.payload(run.runtime.initial())
        fingerprint=run.guard.fingerprint()
        with run.budget.connect() as db:
            for i in range(16):
                db.execute('INSERT INTO attempts VALUES(?,?,?,?,?,?)',
                           ('engineering-progress-'+str(i),'engineering',0,0,'engineering','settled'))
            db.execute('UPDATE execution_control SET fingerprint=?,last_progress_request=0 WHERE id=1',(fingerprint,))
        with patch('experiments.insight_research.paired_v01.budget.request_model',side_effect=AssertionError('provider forbidden')) as transport:
            try:run.journal.call(payload)
            except Pending:pass
            else:raise AssertionError('persisted no-progress guard not enforced')
        assert transport.call_count==0
        checks.append({'check':'guarded_layout_journal_enforces_no_progress','passed':True,
                       'fixture_attempts':16,'real_provider_calls':0})
    finally:ws.close()
    after = SharedTokenBudget(pointer).snapshot();assert before==after
    result={'at':now(),'status':'passed','checks':checks,'new_provider_calls':0,
            'project_budget_unchanged':before==after,'scientific_effectiveness_certified':False,
            'scope':'31 schema examples plus real native database/sandbox/review/repair/report and actual researcher wire. Scripted peer is engineering only.'}
    write_json(output/'acceptance.json',result)
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True)
    main(p.parse_args().output)
