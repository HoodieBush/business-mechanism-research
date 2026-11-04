"""Reference-namespace integration, private-read filtering and paid Q recovery."""
import json,sqlite3,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from ..paired_v02 import test_interface as fixtures
from ..paired_v02.review import Reviewer
from ..test_acceptance import FixtureJournal,raw_call
from ..common import ROOT,Pending,digest,sha
from ..composed_world import ComposedWorld
from ..paired_v03.continuation import prepare
from ..paired_v03.workspace import ResearchWorkspace
from ..paired_v01.budget import StudyBudget
from .orchestrator import ResearchRun

MODEL,review=fixtures.MODEL,fixtures.review


class ImportTests(unittest.TestCase):
    setUp=fixtures.InterfaceTests.setUp
    tearDown=fixtures.InterfaceTests.tearDown
    make=fixtures.InterfaceTests.make
    call=fixtures.InterfaceTests.call
    source=fixtures.InterfaceTests.source
    assessed=fixtures.InterfaceTests.assessed
    save=fixtures.InterfaceTests.save
    budget=fixtures.InterfaceTests.budget

    def prepared(self):
        self.make('independent');h,r,a=self.assessed()
        with self.ws.db:self.ws.event('private_source','read_memory',{'ref':'process:1'},{'ref':'process:1','text':'PRIVATE_THOUGHT_CANARY'})
        n=self.ws.db.execute("SELECT id FROM events WHERE operation='private_source'").fetchone()[0]
        ref='action:'+str(n)
        def factory(peer,job):
            def complete():
                action=peer.db.execute('SELECT ref FROM actions ORDER BY rowid LIMIT 1').fetchone()[0]
                body=review(a['ref'],action,source_refs=[a['ref'],ref],checked_scope=['核验来源'+ref+'已过滤'])
                return raw_call('record_review',body,identifier='finish')
            return FixtureJournal([raw_call('read_memory',{'ref':a['ref']},identifier='read'),complete])
        run=ResearchRun(self.folder/'independent',self.ws,MODEL,self.budget(),owner_journal=FixtureJournal([]),reviewer_journal_factory=factory)
        return run,a,self.ws.jobs('pending')[0],ref,n

    def test_t01_action_citation_translates_and_remains_nonfactual(self):
        run,a,job,source,n=self.prepared();run.review_job(job)
        q=self.ws.record(self.ws.job(job['ref'])['review_ref']);mapped=q['source_ref_translation'][source]
        self.ws.references(q['source_refs']);self.assertIn(mapped,q['source_refs'])
        self.assertTrue(mapped.startswith('C'));self.assertTrue(self.ws.clearance(a['ref']))
        operation=self.ws.record(mapped)['operation'];self.assertNotIn('PRIVATE_THOUGHT_CANARY',json.dumps(operation))
        self.assertTrue(operation['result']['content_omitted'])
        with self.assertRaises(ValueError):self.ws.premise(mapped)
        before=len(self.ws.records('review'));run.review_job(self.ws.job(job['ref']))
        self.assertEqual(len(self.ws.records('review')),before)

    def test_t02_projection_mismatch_pauses_and_keeps_completed_review(self):
        run,a,job,source,n=self.prepared();inputs=run.prepare_job(job)
        peer=Reviewer(self.folder/'manual_peer',inputs,{'research_profile':'paired_critic_v1','model_config':MODEL,'limits':self.ws.settings['limits']})
        try:
            action=peer.call('read_memory',{'ref':a['ref']},'read')['action_ref']
            final=peer.call('record_review',review(a['ref'],action,source_refs=[a['ref'],source]),'final')
            self.assertEqual(final['record_type'],'review')
            original=self.ws.db.execute('SELECT body FROM events WHERE id=?',(n,)).fetchone()[0]
            changed=json.loads(original);changed['arguments']['ref']='different'
            with self.ws.db:self.ws.db.execute('UPDATE events SET body=? WHERE id=?',(json.dumps(changed),n))
            with self.assertRaises(Pending):run.import_feedback(job,peer)
            self.assertEqual(self.ws.records('review'),[]);self.assertTrue(peer.report())
            with self.ws.db:self.ws.db.execute('UPDATE events SET body=? WHERE id=?',(original,n))
            run.import_feedback(job,peer);self.assertTrue(self.ws.clearance(a['ref']))
        finally:peer.close()

    def test_t03_actual_completed_paid_review_imports_without_provider_resend(self):
        parent=ROOT/'experiments/insight_research/review/paired_impl_20261023/prepared_continuation_v04/independent.json'
        manifest=json.loads(parent.read_text());old=manifest['parent_identity'];config={**old['settings'],'continuation_binding':{'manifest':'engineering','sha256':digest(manifest)}}
        identity={**manifest['parent_budget_identity'],'study_id':'engineering_import'}
        env=old['environment_identity'];world=ComposedWorld(kind=env['kind'],seed=env['seed'],scenario_version=env['version'])
        output_base=self.folder.resolve()
        if not output_base.is_relative_to(ROOT):
            tmp=tempfile.TemporaryDirectory(prefix='paid_review_import_',dir=parent.parent.parent);self.addCleanup(tmp.cleanup);output_base=Path(tmp.name)
        output=output_base/'actual'
        prepare(output,manifest,old['question'],world,config,identity)
        ws=ResearchWorkspace(output/'researcher',old['question'],world,config,reopen=True);budget=StudyBudget(output/'common_budget.sqlite',identity)
        try:
            before=budget.snapshot();job=(ws.jobs('pending')+ws.jobs('running'))[0]
            with patch('experiments.insight_research.paired_v01.budget.request_model',side_effect=AssertionError('already paid Q must not call provider')):
                ResearchRun(output,ws,MODEL,budget).review_job(job)
            self.assertEqual(budget.snapshot(),before)
            q=ws.record(ws.job(job['ref'])['review_ref']);self.assertTrue(q['source_ref_translation'])
            for original,current in q['source_ref_translation'].items():
                item=ws.record(current);self.assertEqual(item['origin_action_ref'],original)
                with self.assertRaises(ValueError):ws.premise(current)
            self.assertEqual(len(ws.records('review')),1)
            self.assertTrue(ws.clearance(job['target_ref']))
        finally:ws.close()


if __name__=='__main__':unittest.main()
