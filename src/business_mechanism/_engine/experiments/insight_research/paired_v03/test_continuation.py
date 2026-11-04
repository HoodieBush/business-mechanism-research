"""All-role continuation controls with real DB/sandbox and fake paid transport."""
import json,unittest
from pathlib import Path
from unittest.mock import patch
from ..paired_v02 import test_interface as fixtures
from ..paired_v02.orchestrator import ResearchRun as OldRun
from ..paired_v02.review import Reviewer,ReviewerRuntime
from ..paired_v01.budget import StudyBudget,StudyJournal
from ..test_acceptance import raw_call
from ..common import Pending,digest,sha,write_json
from ..common import ROOT
from ..composed_world import ComposedWorld
from .workspace import ResearchWorkspace
from .orchestrator import ResearchRun
from .continuation import capture,prepare

MODEL,review=fixtures.MODEL,fixtures.review


class ContinuationTests(unittest.TestCase):
    setUp=fixtures.InterfaceTests.setUp
    tearDown=fixtures.InterfaceTests.tearDown
    make=fixtures.InterfaceTests.make
    call=fixtures.InterfaceTests.call
    source=fixtures.InterfaceTests.source
    assessed=fixtures.InterfaceTests.assessed
    save=fixtures.InterfaceTests.save
    def budget(self):
        return StudyBudget(self.ws.root.parent/'common_budget.sqlite',{'study_id':'engineering',
            'project_budget_id':'USER-20261022-CRITIC-10M','token_allowance':2000000,'max_http_attempts':80},create=True)

    def paid(self,message):return {'response':{**message,'usage':{'total_tokens':10}}}

    def parent(self):
        self.make('independent');budget=self.budget();root=self.folder/'independent'
        run=OldRun(root,self.ws,MODEL,budget)
        with patch('experiments.insight_research.paired_v01.budget.request_model',return_value=self.paid(raw_call('read_context',{}))):
            run.run(1)
        h,r,a=self.assessed();job=self.ws.jobs('pending')[0];inputs=run.prepare_job(job)
        settings={'research_profile':'paired_critic_v1','model_config':MODEL,'limits':{**self.ws.settings['limits'],'max_http_attempts':12}}
        peer=Reviewer(root/'reviews'/job['ref']/'critic',inputs,settings)
        journal=StudyJournal(peer,MODEL,budget,'critic:'+job['ref'])
        with patch('experiments.insight_research.paired_v01.budget.request_model',return_value=self.paid(raw_call('read_memory',{'ref':a['ref']}))):
            ReviewerRuntime(peer,MODEL,journal=journal).run(1)
        peer.close();self.ws.close();self.ws=None
        write_json(root/'root_answers.json',{'must_not_copy':True})
        return root,budget,h,r,a,job

    def fork(self,root,budget,manifest):
        settings=json.loads((root/'researcher/private/identity.json').read_text())['settings']
        settings={**settings,'continuation_binding':{'manifest':'engineering','sha256':digest(manifest)}}
        identity={**budget.identity,'study_id':'engineering_child'}
        child=self.folder/'child'
        prepare(child,manifest,'核验真实记录并持续研究',ComposedWorld(),settings,identity,base=self.folder)
        ws=ResearchWorkspace(child/'researcher','核验真实记录并持续研究',ComposedWorld(),settings,reopen=True)
        return child,ws,StudyBudget(child/'common_budget.sqlite',identity)

    def test_c01_peer_paid_work_and_all_role_costs_continue_without_resend(self):
        root,budget,h,r,a,job=self.parent();manifest=capture(root,base=self.folder)
        self.assertEqual(manifest['inherited_tokens'],20);self.assertEqual(manifest['inherited_attempts'],2)
        self.assertNotIn('root_answers.json',manifest['sha256'])
        child,ws,shared=self.fork(root,budget,manifest)
        try:
            self.assertEqual(shared.snapshot()['accounted_tokens'],20);self.assertEqual(ws.job(job['ref'])['review_http_limit'],18)
            old_body=json.loads((root/'researcher/science/records'/f"{a['ref']}.json").read_text())
            self.assertEqual(ws.record(a['ref']),old_body)
            self.assertEqual(sha(root/'researcher/private/http/1.json'),sha(child/'researcher/private/http/1.json'))
            peerpath=child/'reviews'/job['ref']/'critic/private/critic.sqlite'
            import sqlite3
            with sqlite3.connect(peerpath) as db:action=db.execute('SELECT ref FROM actions LIMIT 1').fetchone()[0]
            reply=self.paid(raw_call('record_review',review(a['ref'],action)))
            run=ResearchRun(child,ws,MODEL,shared)
            with patch('experiments.insight_research.paired_v01.budget.request_model',return_value=reply) as provider:
                run.review_job(ws.job(job['ref']))
                self.assertEqual(provider.call_count,1)
            self.assertTrue(ws.clearance(a['ref']));self.assertEqual(shared.snapshot()['accounted_tokens'],30)
            self.assertEqual(shared.snapshot()['http_attempts'],3)
            self.assertEqual(budget.snapshot()['accounted_tokens'],20)
            self.assertEqual(capture(root,base=self.folder),manifest)
            self.assertFalse((child/'root_answers.json').exists())
        finally:ws.close()

    def test_c02_reject_mutation_unsettled_work_or_budget_reset(self):
        root,budget,h,r,a,job=self.parent();manifest=capture(root,base=self.folder)
        identity={**budget.identity,'token_allowance':budget.identity['token_allowance']+1}
        settings=json.loads((root/'researcher/private/identity.json').read_text())['settings']
        with self.assertRaises(ValueError):prepare(self.folder/'bad',manifest,'核验真实记录并持续研究',ComposedWorld(),settings,identity,base=self.folder)
        transport=root/'researcher/private/transport.json';old=transport.read_bytes();x=json.loads(old);x['inflight']={'attempt':2};write_json(transport,x)
        try:
            with self.assertRaises(Pending):capture(root,base=self.folder)
        finally:transport.write_bytes(old)
        target=root/'researcher/science/records'/f"{h['ref']}.json";old=target.read_bytes();target.write_bytes(old+b' ')
        try:
            with self.assertRaises(ValueError):prepare(self.folder/'changed',manifest,'核验真实记录并持续研究',ComposedWorld(),settings,budget.identity,base=self.folder)
        finally:target.write_bytes(old)

    def test_c03_completed_arm_forks_without_extra_paid_call_or_cost_reset(self):
        h,r,a=self.assessed();self.save(evidence_refs=[r['ref']],pending_claim_refs=[a['ref']])
        budget=self.budget();root=self.folder/'self';run=OldRun(root,self.ws,MODEL,budget)
        def respond(config,payload):
            drafts=self.ws.records('report_draft');pending=self.ws.jobs('pending')
            if pending:
                job=pending[0];return self.paid(raw_call('review_claim',{'job_ref':job['ref'],'review':review(job['target_ref'],r['action_ref'])}))
            return self.paid(raw_call('finish_research',{'assessment_refs':[a['ref']],'other_hypotheses':{},'limitations':['工程范围'],'open_questions':[],'measurement_requests':[]}))
        with patch('experiments.insight_research.paired_v01.budget.request_model',side_effect=respond):
            result=run.run(8)
        self.assertEqual(result['status'],'completed');report=self.ws.report();self.ws.close();self.ws=None
        manifest=capture(root,base=self.folder);child,ws,shared=self.fork(root,budget,manifest)
        try:
            with patch('experiments.insight_research.paired_v01.budget.request_model',side_effect=AssertionError('completed arm must not resend')):
                result=ResearchRun(child,ws,MODEL,shared).run(1)
            self.assertEqual(result['status'],'completed');self.assertEqual(ws.report(),report)
            self.assertEqual(shared.snapshot()['accounted_tokens'],budget.snapshot()['accounted_tokens'])
            self.assertEqual(shared.snapshot()['http_attempts'],budget.snapshot()['http_attempts'])
        finally:ws.close()

    def test_c04_actual_stopped_pair_imports_all_records_and_cumulative_charges(self):
        import sqlite3,tempfile
        prepared=ROOT/'experiments/insight_research/review/paired_impl_20261023/prepared_continuation_v03'
        output_base=self.folder.resolve()
        if not output_base.is_relative_to(ROOT):
            temporary=tempfile.TemporaryDirectory(prefix='stopped_pair_',dir=prepared.parent)
            self.addCleanup(temporary.cleanup);output_base=Path(temporary.name)
        for mode in ('self','independent'):
            manifest=json.loads((prepared/(mode+'.json')).read_text());old=manifest['parent_identity']
            config={**old['settings'],'continuation_binding':{'manifest':'engineering_actual_parent','sha256':digest(manifest)}}
            env=old['environment_identity'];world=ComposedWorld(kind=env['kind'],seed=env['seed'],scenario_version=env['version'])
            identity={**manifest['parent_budget_identity'],'study_id':'engineering_actual_'+mode}
            output=output_base/('actual_'+mode)
            # Acceptance root lies inside the project, so the explicit project
            # paths can be checked without relocating or changing the parent.
            prepare(output,manifest,old['question'],world,config,identity)
            parent=ROOT/manifest['parent_root']
            with sqlite3.connect((parent/'researcher/private/records.sqlite').as_uri()+'?mode=ro',uri=True) as source, \
                 sqlite3.connect((output/'researcher/private/records.sqlite').as_uri()+'?mode=ro',uri=True) as child:
                for table in ('records','events','operations','memory_validity','affected','review_jobs','review_issues','clearances','self_review_clock'):
                    self.assertEqual(source.execute('SELECT * FROM '+table).fetchall(),child.execute('SELECT * FROM '+table).fetchall(),table)
            b=StudyBudget(output/'common_budget.sqlite',identity)
            self.assertEqual(b.snapshot()['accounted_tokens'],manifest['inherited_tokens'])
            self.assertEqual(b.snapshot()['http_attempts'],manifest['inherited_attempts'])
            self.assertEqual(sha(output/'parent_run/common_budget.sqlite'),manifest['sha256']['common_budget.sqlite'])
            self.assertEqual(capture(parent),manifest)


if __name__=='__main__':unittest.main()
