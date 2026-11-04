"""Version identity, ambiguity rejection and real paid failed-submission recovery."""
import json,sqlite3,unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
from ..common import ROOT,sha,digest
from ..composed_world import ComposedWorld
from ..paired_v01.budget import StudyBudget,StudyJournal
from ..paired_v02 import test_interface as fixtures
from ..paired_v05.continuation import prepare
from ..test_acceptance import settings,FixtureJournal
from .references import normalize,recover_paid_submission
from .workspace import ResearchWorkspace
from .orchestrator import ResearchRun
from .review import Reviewer,ReviewerRuntime

class ReferenceTests(unittest.TestCase):
    setUp=fixtures.InterfaceTests.setUp
    tearDown=fixtures.InterfaceTests.tearDown
    call=fixtures.InterfaceTests.call
    source=fixtures.InterfaceTests.source
    assessed=fixtures.InterfaceTests.assessed
    save=fixtures.InterfaceTests.save
    budget=fixtures.InterfaceTests.budget

    def make(self,mode):
        if self.ws:self.ws.close()
        config=settings();config.update(research_profile='paired_research_v1',verification_mode=mode,model_config=fixtures.MODEL)
        config['limits'].update(token_allowance=6000000,max_http_attempts=80,max_request_bytes=524288,knowledge_context_bytes=24000)
        self.ws=ResearchWorkspace(self.folder/mode/'researcher','工程检查：唯一已登记版本引用',ComposedWorld(),config)
        return self.ws

    def test_v01_unique_alias_changes_only_reference_values_and_preserves_unknowns(self):
        db=sqlite3.connect(':memory:');self.addCleanup(db.close)
        db.execute('CREATE TABLE files(ref TEXT,path TEXT,hash TEXT)');db.execute('INSERT INTO files VALUES (?,?,?)',('file:canonical','received','a'*64))
        original={'text':'scope remains; file:'+'a'*64,'unknown':['file:'+'b'*64],'plain_hash':'a'*64}
        actual,mapping=normalize(original,(db,))
        self.assertEqual(actual,{'text':'scope remains; file:canonical','unknown':['file:'+'b'*64],'plain_hash':'a'*64})
        self.assertEqual(mapping,{'file:'+'a'*64:'file:canonical'})

    def test_v02_ambiguous_registered_versions_are_not_chosen(self):
        db=sqlite3.connect(':memory:');self.addCleanup(db.close);db.execute('CREATE TABLE files(ref TEXT,path TEXT,hash TEXT)')
        db.executemany('INSERT INTO files VALUES (?,?,?)',[('file:one','a','a'*64),('file:two','b','a'*64)])
        text='file:'+'a'*64;self.assertEqual(normalize(text,(db,)),(text,{}))

    def test_v03_self_submission_same_unique_version_normalization_and_old_contract(self):
        h,r,a=self.assessed();source=self.source();path,_=self.ws.file(source);wrong='file:'+sha(path)
        job=self.ws.jobs('pending')[0]
        body=fixtures.review(a['ref'],r['action_ref']);body['source_refs'].append(wrong)
        answer=self.call('review_claim',{'job_ref':job['ref'],'review':body})
        self.assertIn('ref',answer,answer);self.assertTrue(self.ws.clearance(a['ref']))
        record=self.ws.record(answer['ref']);self.assertIn(source,record['source_refs']);self.assertNotIn(wrong,record['source_refs'])
        self.assertEqual(len(self.ws.tool_schemas()),13)
        receipts=list((self.ws.science/'reference_normalizations').glob('*.json'));self.assertEqual(len(receipts),1)
        self.assertEqual(json.loads(receipts[0].read_text())['submitted_arguments']['review']['source_refs'][-1],wrong)

    def real_copy(self,mode,name):
        file=ROOT/'experiments/insight_research/review/paired_impl_20261023/prepared_continuation_v07'/(mode+'.json')
        manifest=json.loads(file.read_text());old=manifest['parent_identity'];config=deepcopy(old['settings'])
        config['paired_v06_sources']={'engineering':'explicit'}
        identity={**manifest['parent_budget_identity'],'study_id':'reference_engineering_'+name}
        env=old['environment_identity'];world=ComposedWorld(kind=env['kind'],seed=env['seed'],scenario_version=env['version'])
        target=self.folder/name
        prepare(target,manifest,old['question'],world,config,identity)
        ws=ResearchWorkspace(target/'researcher',old['question'],world,config,reopen=True)
        self.addCleanup(ws.close)
        return target,manifest,ws,StudyBudget(target/'common_budget.sqlite',identity)

    def test_v04_actual_failed_paid_critic_review_recovers_without_model_or_counter_change(self):
        root,manifest,ws,budget=self.real_copy('independent','actual_paid')
        before=budget.snapshot();run=ResearchRun(root,ws,fixtures.MODEL,budget)
        job=ws.jobs('running')[0]
        original_turn=sha(root/'reviews'/job['ref']/'critic/private/turns/18.json')
        with patch('experiments.insight_research.paired_v01.budget.request_model',side_effect=AssertionError('no new model request')) as model:
            run.review_job(job);self.assertEqual(model.call_count,0)
        self.assertEqual(budget.snapshot(),before);self.assertEqual(ws.job(job['ref'])['status'],'completed')
        self.assertEqual(sha(root/'reviews'/job['ref']/'critic/private/turns/18.json'),original_turn)
        self.assertEqual(len(ws.records('review')),1)
        recovery=list((root/'reviews'/job['ref']/'critic/artifacts/reference_normalizations').glob('recovery_*.json'))
        self.assertEqual(len(recovery),1);receipt=json.loads(recovery[0].read_text())
        self.assertTrue(receipt['result_ok']);self.assertEqual(receipt['new_model_calls'],0)
        self.assertEqual(len(receipt['aliases']),1)
        self.assertEqual(len(receipt['explicit_action_links']),3)
        # Re-entering the completed job cannot import duplicate opinions/actions.
        run.review_job(job);self.assertEqual(len(ws.records('review')),1);self.assertEqual(budget.snapshot(),before)

    def test_v05_finished_self_copy_returns_original_report_without_model_calls(self):
        root,manifest,ws,budget=self.real_copy('self','actual_completed')
        before=budget.snapshot();ref=ws.report()['ref']
        with patch('experiments.insight_research.paired_v01.budget.request_model',side_effect=AssertionError('no new request')):
            result=ResearchRun(root,ws,fixtures.MODEL,budget).run(80)
        self.assertEqual(result['status'],'completed');self.assertEqual(result['report_ref'],ref);self.assertEqual(budget.snapshot(),before)

    def test_v06_recomputed_issue_without_its_own_explicit_action_still_rejected(self):
        h,r,a=self.assessed();job=self.ws.jobs('pending')[0]
        issue={'issue_id':'missing','type':'methodological_disagreement','description':'工程缺失动作','affected_refs':[a['ref']],
            'basis':'recomputed','blocking':False,'evidence_locations':['No action was explicitly cited here'],'claim_impact':'工程夹具','minimal_next_step':'保持拒绝'}
        body=fixtures.review(a['ref'],r['action_ref'],issues=[issue])
        answer=self.call('review_claim',{'job_ref':job['ref'],'review':body})
        self.assertFalse(answer['ok']);self.assertIn('actual check actions',answer['error']);self.assertFalse(self.ws.clearance(a['ref']))

    def test_v07_nonexistent_explicit_action_is_not_accepted(self):
        h,r,a=self.assessed();body=fixtures.review(a['ref'],r['action_ref'])
        body['issues']=[{'issue_id':'bad','basis':'recomputed','action_refs':[],'evidence_locations':['event:999999999']}]
        corrected,changes=self.ws.normalize_submission('review_claim',{'job_ref':self.ws.jobs('pending')[0]['ref'],'review':body})
        self.assertEqual(changes['explicit_action_links'],{});self.assertEqual(corrected['review']['issues'][0]['action_refs'],[])

    def test_v08_modified_turn_cannot_be_treated_as_original_paid_work(self):
        root,manifest,ws,budget=self.real_copy('independent','modified_turn')
        run=ResearchRun(root,ws,fixtures.MODEL,budget);job=ws.jobs('running')[0];inputs=run.prepare_job(job)
        config={'research_profile':'paired_critic_v1','model_config':fixtures.MODEL,'limits':{**ws.settings['limits'],'max_http_attempts':18}}
        peer=Reviewer(root/'reviews'/job['ref']/'critic',inputs,config,reopen=True);self.addCleanup(peer.close)
        journal=StudyJournal(peer,fixtures.MODEL,budget,'critic:'+job['ref']);runtime=ReviewerRuntime(peer,fixtures.MODEL,journal=journal)
        path=peer.private/'turns/18.json';changed=json.loads(path.read_text());changed['model']='engineering_tamper';path.write_text(json.dumps(changed))
        before=budget.snapshot()
        self.assertIsNone(recover_paid_submission(runtime,'record_review'))
        self.assertFalse(peer.report());self.assertEqual(budget.snapshot(),before)

if __name__=='__main__':unittest.main()
