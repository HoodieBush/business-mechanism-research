"""Runtime memory authority checks, without business answers or model calls."""
import json
import tempfile
import unittest
from pathlib import Path
from world import OfficeWorld
from workspace import write_json
from langgraph_migration.science import ScientificWorkspace
from langgraph_migration.runtime import FrameworkRoles, operation
from langgraph_migration.operational_memory import record


class OperationalMemoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(dir=Path(__file__).parent, prefix='unit_memory_')
        cls.ws = ScientificWorkspace(Path(cls.tmp.name)/'source', OfficeWorld('confounding',8421,'office-business-v0.3'))
        cls.roles = FrameworkRoles(cls.ws,None,lambda role:None)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_01_all_roles_can_read_own_index_and_receipt_without_evidence_promotion(self):
        for role in self.roles.role_tools:
            with self.subTest(role=role):
                index = self.ws.workers[role].directory/'framework_receipts/index.json'
                first = self.ws._tool(role,'read_artifact',{'path':str(index)})
                self.assertEqual(first['authority'],'operational_navigation_only')
                visible,_ = self.roles.execute(role,'read_history',{})
                receipt = json.loads(visible)['full_receipt']
                content = self.ws._tool(role,'read_artifact',{'path':receipt})
                self.assertTrue(json.loads(content['text'])['ok'])
                self.assertNotIn('artifact_id',content)
                self.assertNotIn(receipt,self.ws.registered_sources)
                for path in (receipt,str(index)):
                    with self.assertRaisesRegex(ValueError,'not standalone scientific evidence'):
                        self.ws.require_reviewed([path])

    def test_02_cross_role_and_tampered_memory_fail_closed(self):
        index = self.ws.workers['analyst'].directory/'framework_receipts/index.json'
        with self.assertRaisesRegex(ValueError,'another role'):
            self.ws._tool('mechanist','read_artifact',{'path':str(index)})
        original = index.read_bytes(); index.write_text('[]\n')
        try:
            with self.assertRaisesRegex(ValueError,'version changed'):
                self.ws._tool('analyst','read_artifact',{'path':str(index)})
        finally:index.write_bytes(original)

    def test_03_unreviewed_data_and_forged_names_keep_review_gate(self):
        for relative in ('unreviewed.csv','fake/framework_receipts/index.json'):
            path = self.ws.workers['mechanist'].directory/relative
            path.parent.mkdir(parents=True,exist_ok=True); path.write_text('[]\n')
            with self.assertRaisesRegex(ValueError,'no current independent review'):
                self.ws._tool('mechanist','read_artifact',{'path':str(path)})

    def test_04_legacy_migration_matches_actual_event_not_index(self):
        role='mechanist'; key='lg_legacy_memory_test'; token=operation.set(key)
        try:visible,artifact=self.roles.execute(role,'read_history',{})
        finally:operation.reset(token)
        receipt=json.loads(visible)['full_receipt']
        self.ws.event(role,'read_history',{},artifact['feedback'],operation_id=key)
        self.ws.state.pop('operational_records'); self.ws.persist()
        index=self.ws.workers[role].directory/'framework_receipts/index.json'
        write_json(index,[{'full_path':'/invented/forged.json','role':role}])
        FrameworkRoles(self.ws,None,lambda role:None)
        self.assertEqual(record(self.ws,receipt,role)['owner_role'],role)
        self.assertEqual([x['full_path']for x in json.loads(index.read_text())],[receipt])
        original=Path(receipt).read_bytes(); Path(receipt).write_text('{}\n')
        try:
            with self.assertRaisesRegex(ValueError,'hash mismatch'):
                FrameworkRoles(self.ws,None,lambda role:None)
        finally:Path(receipt).write_bytes(original)

    def test_05_continuation_rebinds_verified_records_and_preserves_data(self):
        FrameworkRoles(self.ws,None,lambda role:None)
        child=ScientificWorkspace(Path(self.tmp.name)/'child',OfficeWorld('confounding',8421,'office-business-v0.3'),resume_from=self.ws.root)
        FrameworkRoles(child,None,lambda role:None)
        old=str(self.ws.workers['mechanist'].directory/'framework_receipts/index.json')
        view=child._tool('mechanist','read_artifact',{'path':old})
        self.assertTrue(view['path'].startswith(str(child.root)))
        for name in ('business.sqlite','history.csv','data_dictionary.json'):
            self.assertEqual((child.public/name).read_bytes(),(self.ws.public/name).read_bytes())

    def test_06_event_payload_is_snapshot_not_mutable_state_alias(self):
        feedback={'ok':True,'result':{'nested':[]}}
        args={'example':[]}
        self.ws.event('mechanist','opaque',args,feedback,operation_id='immutable_event_test')
        before=json.dumps(self.ws.state['events'][-1],sort_keys=True)
        feedback['result']['nested'].append('later mutation');args['example'].append('later mutation')
        self.assertEqual(json.dumps(self.ws.state['events'][-1],sort_keys=True),before)

    def test_07_legacy_mutated_state_uses_immutable_append_journal(self):
        role='mechanist';key='lg_append_authority';token=operation.set(key)
        try:visible,artifact=self.roles.execute(role,'read_history',{})
        finally:operation.reset(token)
        receipt=json.loads(visible)['full_receipt']
        self.ws.event(role,'read_history',{},artifact['feedback'],operation_id=key)
        row={'role':role,'tool':'read_history','arguments':{},'feedback':artifact['feedback'],'operation_id':key}
        (self.ws.root/'framework_tools.jsonl').write_text(json.dumps(row)+'\n')
        self.ws.state['events'][-1]['result']['result']['artifact_reviews'].append({'later':'state-only mutation'})
        self.ws.state.pop('operational_records');self.ws.persist()
        FrameworkRoles(self.ws,None,lambda role:None)
        self.assertEqual(record(self.ws,receipt,role)['owner_role'],role)


if __name__=='__main__':unittest.main()
