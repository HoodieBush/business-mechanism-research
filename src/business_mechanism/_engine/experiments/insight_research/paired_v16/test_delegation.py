import json
import unittest
from unittest.mock import patch
from ..common import digest, encoded
from ..composed_world import ComposedWorld
from ..test_acceptance import settings, state, raw_call, hypothesis
from ..paired_v02 import test_interface as fixtures
from ..paired_v11 import test_scoped as scoped
from ..paired_v01.test_pairing import MODEL, review
from .workspace import ResearchWorkspace
from .orchestrator import ResearchRun


class DelegationTests(unittest.TestCase):
    setUp = fixtures.InterfaceTests.setUp
    tearDown = fixtures.InterfaceTests.tearDown
    call = fixtures.InterfaceTests.call
    source = fixtures.InterfaceTests.source
    assessed = fixtures.InterfaceTests.assessed
    save = fixtures.InterfaceTests.save
    budget = fixtures.InterfaceTests.budget

    def make(self,mode):
        if self.ws:
            self.ws.close()
        config = settings()
        config.update(research_profile='paired_research_v1',verification_mode=mode,model_config=MODEL,
            workflow_policy={'max_lineage_reviews':4},execution_policy={'wall_seconds':7200,'warn_after_requests':8,
            'stop_after_requests':16,'review_http_limit':18,'closeout_reserve_tokens':1300000,'active_context_bytes':65536})
        config['limits'].update(token_allowance=3000000,max_http_attempts=160,max_request_bytes=524288,knowledge_context_bytes=24000)
        self.ws = ResearchWorkspace(self.folder/mode/'researcher','工程：自主安排核验并保留原证据',ComposedWorld(),config)
        return self.ws

    def request(self,target):
        job = next(j for j in self.ws.jobs('pending') if j['target_ref']==target)
        out = self.call('request_review',{'job_ref':job['ref'],'reason':'工程：当前研究需要核验这个对象'})
        self.assertEqual(out['status'],'scheduled',out)
        return job

    def test_d01_unscheduled_peer_queue_does_not_preempt_owner(self):
        self.make('independent'); h,r,a = self.assessed(); b = self.budget()
        raw = raw_call('update_research_state',state(question='研究者选择先整理认识',active_hypothesis_refs=[h['ref']],
            focus_hypothesis_refs=[h['ref']],incorporated_result_refs=[r['ref']],evidence_refs=[r['ref']]))
        raw['usage']={'total_tokens':17}
        with patch('experiments.insight_research.paired_v01.budget.request_model',return_value={'response':raw}) as provider:
            out = ResearchRun(self.folder/'independent',self.ws,MODEL,b).run(1)
        self.assertEqual(out['status'],'pending',out)
        self.assertEqual(provider.call_count,1)
        self.assertEqual(self.ws.state()['question'],'研究者选择先整理认识')
        self.assertEqual(self.ws.records('review'),[])
        self.assertEqual(b.snapshot()['accounted_tokens'],17)

    def test_d02_self_delegation_required_in_both_submission_entries(self):
        h,r,a = self.assessed(); job = self.ws.jobs('pending')[0]
        body = review(a['ref'],r['action_ref'])
        self.assertFalse(self.call('review_claim',{'job_ref':job['ref'],'review':body})['ok'])
        checkpoint = self.save(self_reviews=[{'job_ref':job['ref'],'review':body}])
        self.assertTrue(checkpoint['review_rejections'])
        self.request(a['ref'])
        q = self.call('review_claim',{'job_ref':job['ref'],'review':body})
        self.assertEqual(q['record_type'],'review',q)
        self.assertTrue(self.ws.clearance(a['ref']))

    def test_d03_independent_mode_still_cannot_submit_self_clearance(self):
        self.make('independent'); h,r,a = self.assessed(); job = self.request(a['ref'])
        out = self.call('review_claim',{'job_ref':job['ref'],'review':review(a['ref'],r['action_ref'])})
        self.assertFalse(out['ok'])
        self.assertFalse(self.ws.clearance(a['ref']))

    def test_d04_delegation_rebuild_comes_from_immutable_owner_note(self):
        h,r,a = self.assessed(); job = self.request(a['ref'])
        note = self.ws.records('review_note')[-1]; original = digest(note)
        with self.ws.db:
            self.ws.db.execute('DELETE FROM review_delegations')
        self.assertEqual(self.ws.delegated_jobs(),[])
        self.ws._rebuild_reviews()
        self.assertEqual([x['ref'] for x in self.ws.delegated_jobs()],[job['ref']])
        self.assertEqual(digest(self.ws.record(note['ref'])),original)

    def test_d05_only_one_unfinished_delegation_at_a_time(self):
        h,r,a = self.assessed(); self.request(a['ref'])
        h2,r2,a2 = self.assessed(); job = next(j for j in self.ws.jobs('pending') if j['target_ref']==a2['ref'])
        self.assertFalse(self.call('request_review',{'job_ref':job['ref'],'reason':'另一个任务'})['ok'])
        self.assertEqual(len(self.ws.delegated_jobs()),1)

    def test_d06_bounded_view_keeps_exact_long_original_and_paged_history(self):
        text = '原反证必须保留。'*15000
        h = self.call('save_hypothesis',hypothesis(falsification=text))
        for number in range(11):
            self.save(knowledge_updates=[{'kind':'method','statement':'历史方法'+str(number),'scope':'工程',
                'status':'tentative','evidence_refs':[self.source()],'research_use':'分页检索'}])
        view = self.ws.context()
        self.assertLess(len(encoded(view).encode()),65536)
        read = self.call('read_memory',{'ref':'original:'+h['ref'],'limit':12000})
        chunks = [read['text']]
        while read['next_offset'] is not None:
            read = self.call('read_memory',{'ref':'original:'+h['ref'],'offset':read['next_offset'],'limit':12000})
            chunks.append(read['text'])
        self.assertEqual(json.loads(''.join(chunks))['original']['falsification'],text)
        page = json.loads(self.call('read_memory',{'ref':'research_index:knowledge:0'})['text'])
        self.assertEqual(page['total'],11)
        self.assertTrue(page['next_ref'])
        nextpage = json.loads(self.call('read_memory',{'ref':page['next_ref']})['text'])
        self.assertEqual(len(nextpage['entries']),3)

    def test_d07_original_counterevidence_and_dispute_navigation_survive(self):
        h,r,a = self.assessed()
        self.save(counterevidence_refs=[r['ref']])
        ctx = self.ws.context()
        self.assertEqual(ctx['critical_counterevidence'][0]['ref'],r['ref'])
        record = json.loads(self.call('read_memory',{'ref':ctx['critical_counterevidence'][0]['read_ref']})['text'])
        self.assertEqual(record['original']['ref'],r['ref'])
        self.assertFalse(self.ws.clearance(a['ref']))

    def finish_cycle(self,mode):
        if mode!='self':
            self.make(mode)
        h,r,a = self.assessed(); self.save(); b = self.budget()
        root = self.folder/mode; count = {'owner':0,'peer':0}
        def provider(config,payload):
            if any(t['function']['name']=='record_review' for t in payload['tools']):
                count['peer'] += 1
                job = self.ws.jobs('running')[0]
                if count['peer'] % 2:
                    raw = raw_call('read_memory',{'ref':job['target_ref']})
                else:
                    import sqlite3
                    with sqlite3.connect(root/'reviews'/job['ref']/'critic/private/critic.sqlite') as db:
                        action = db.execute('SELECT ref FROM actions ORDER BY rowid DESC LIMIT 1').fetchone()[0]
                    raw = raw_call('record_review',review(job['target_ref'],action))
            else:
                count['owner'] += 1
                pending = self.ws.jobs('pending')
                selected = self.ws.delegated_jobs()
                if selected:
                    job = selected[0]
                    raw = raw_call('review_claim',{'job_ref':job['ref'],'review':review(job['target_ref'],r['action_ref'])})
                elif pending:
                    raw = raw_call('request_review',{'job_ref':pending[0]['ref'],'reason':'工程选择当前判断或报告核验'})
                else:
                    raw = raw_call('finish_research',{'assessment_refs':[a['ref']],'other_hypotheses':{},'limitations':['工程路径，不是科学认证'],'open_questions':[],'measurement_requests':[]})
            raw['usage'] = {'total_tokens':19}
            return {'response':raw}
        with patch('experiments.insight_research.paired_v01.budget.request_model',side_effect=provider):
            out = ResearchRun(root,self.ws,MODEL,b).run(12)
        self.assertEqual(out['status'],'completed',out)
        self.assertTrue(self.ws.report())
        self.assertEqual(len(self.ws.records('review')),2)
        self.assertEqual(b.snapshot()['accounted_tokens'],19*sum(count.values()))
        self.assertEqual(b.snapshot()['http_attempts'],sum(count.values()))
        if mode=='independent':
            self.assertEqual(count,{'owner':2,'peer':4})
        else:
            self.assertEqual(count,{'owner':4,'peer':0})

    def test_d08_realJournals_self_stage_delivery_and_shared_cost(self):
        self.finish_cycle('self')

    def test_d09_realJournals_independent_stage_delivery_and_shared_cost(self):
        self.finish_cycle('independent')

    def test_d10_paid_response_recovery_charges_once_with_new_tool_contract(self):
        h,r,a = self.assessed(); b = self.budget(); run = ResearchRun(self.folder/'self',self.ws,MODEL,b)
        payload = run.runtime.payload(run.runtime.initial())
        job = self.ws.jobs('pending')[0]
        raw = raw_call('request_review',{'job_ref':job['ref'],'reason':'工程付费恢复'}); raw['usage']={'total_tokens':23}
        with patch('experiments.insight_research.paired_v01.budget.request_model',return_value={'response':raw}) as provider:
            first = run.journal.call(payload)
            second = run.journal.call(payload)
        self.assertEqual(provider.call_count,1)
        self.assertEqual(first['response'],second['response'])
        self.assertEqual(b.snapshot()['accounted_tokens'],23)
        self.assertEqual(b.snapshot()['http_attempts'],1)
        self.assertEqual(len(self.ws.tools),16)

    def test_d11_owner_decides_after_feedback_before_other_unrequested_review(self):
        self.make('independent'); h,r,a = self.assessed(); h2,r2,a2 = self.assessed(); self.save()
        selected = self.request(a['ref']); b = self.budget(); root = self.folder/'independent'; counts={'peer':0,'owner':0}
        def provider(config,payload):
            if any(t['function']['name']=='record_review' for t in payload['tools']):
                counts['peer'] += 1
                if counts['peer']==1:
                    raw = raw_call('read_memory',{'ref':a['ref']})
                else:
                    import sqlite3
                    with sqlite3.connect(root/'reviews'/selected['ref']/'critic/private/critic.sqlite') as db:
                        action = db.execute('SELECT ref FROM actions ORDER BY rowid DESC LIMIT 1').fetchone()[0]
                    raw = raw_call('record_review',review(a['ref'],action))
            else:
                counts['owner'] += 1
                raw = raw_call('update_research_state',state(active_hypothesis_refs=[h['ref'],h2['ref']],focus_hypothesis_refs=[h2['ref']],
                    incorporated_result_refs=[r['ref'],r2['ref']],evidence_refs=[r2['ref']],question='反馈后由研究者选择下一问题'))
            raw['usage']={'total_tokens':11}
            return {'response':raw}
        with patch('experiments.insight_research.paired_v01.budget.request_model',side_effect=provider):
            out = ResearchRun(root,self.ws,MODEL,b).run(2)
        self.assertEqual(out['status'],'pending',out)
        self.assertEqual(counts,{'peer':2,'owner':1})
        self.assertEqual(self.ws.state()['question'],'反馈后由研究者选择下一问题')
        self.assertEqual(len(self.ws.jobs('pending')),1)
        self.assertEqual(self.ws.jobs('pending')[0]['target_ref'],a2['ref'])

    def test_d12_scoped_json_computation_is_counted_as_new_content(self):
        from .guard import ProgressGuard
        b = self.budget(); guard = ProgressGuard(self.folder/'self',self.ws,b)
        before = guard.fingerprint()
        ref = scoped.ScopedTests.csv(self)
        out = self.call('inspect_evidence',{'source_ref':ref,'analysis':'daily_sales_effect','product_ids':['S01']})
        self.assertTrue(out['ok'],out)
        after = guard.fingerprint()
        self.assertNotEqual(before,after)
        # A changed operation ID cannot manufacture new progress from the same statistic.
        again = self.call('inspect_evidence',{'source_ref':ref,'analysis':'daily_sales_effect','product_ids':['S01']})
        self.assertTrue(again['ok'],again)
        self.assertEqual(after,guard.fingerprint())


if __name__=='__main__':
    unittest.main()
