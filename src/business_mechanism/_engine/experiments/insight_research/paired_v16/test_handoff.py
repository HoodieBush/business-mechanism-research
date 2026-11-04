import unittest
from . import test_delegation as fixtures


class HandoffTests(unittest.TestCase):
    setUp=fixtures.DelegationTests.setUp
    tearDown=fixtures.DelegationTests.tearDown
    make=fixtures.DelegationTests.make
    call=fixtures.DelegationTests.call
    source=fixtures.DelegationTests.source
    assessed=fixtures.DelegationTests.assessed
    save=fixtures.DelegationTests.save
    budget=fixtures.DelegationTests.budget

    def test_h01_candidate_receipt_has_exact_review_affordance_without_auto_delegation(self):
        h,r,a=self.assessed()
        self.assertEqual(a['review_choices'][0]['target_ref'],a['ref'])
        self.assertEqual(a['review_choices'][0]['job_ref'],self.ws.jobs('pending')[0]['ref'])
        self.assertEqual(self.ws.delegated_jobs(),[])
        self.assertFalse(self.ws.clearance(a['ref']))

    def stage(self,mode):
        if mode!='self':self.make(mode)
        h,r,a=self.assessed();self.save();budget=self.budget();self.ws.study_budget=budget
        with budget.connect() as db:db.execute("INSERT INTO flags VALUES ('stage_closeout','engineering finite publication')")
        oldjob=self.ws.jobs('pending')[0]
        draft=self.call('finish_research',{'assessment_refs':[],'other_hypotheses':{h['ref']:'判断尚未核验，阶段保留未决'},
            'limitations':['工程路径，不计科学能力'],'open_questions':['未决'],'measurement_requests':[],
            'deferred_review_jobs':{oldjob['ref']:'未付费且不发表该判断'}})
        self.assertEqual(draft['record_type'],'report_draft',draft)
        self.assertEqual(draft['publication_review']['status'],'scheduled')
        active=self.ws.delegated_jobs();self.assertEqual(len(active),1)
        self.assertEqual(active[0]['target_ref'],draft['ref'])
        self.assertEqual(self.ws.job(oldjob['ref'])['status'],'deferred')
        self.assertFalse(self.ws.clearance(a['ref']))
        self.assertIsNone(self.ws.report())
        self.assertEqual(budget.snapshot()['http_attempts'],0)

    def test_h02_self_submission_requests_only_report_not_unpublished_judgment(self):self.stage('self')
    def test_h03_independent_submission_requests_only_report_not_unpublished_judgment(self):self.stage('independent')


if __name__=='__main__':unittest.main()
