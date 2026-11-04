"""Origin links are generic; labels and declarations remain fallible."""
import json
from pathlib import Path
import tempfile
import unittest
from world import OfficeWorld
from workspace import sha
from langgraph_migration.science import ScientificWorkspace
from langgraph_migration.runtime import FrameworkRoles
from langgraph_migration.object_identity import enable_object_identity


class IdentityTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=Path(__file__).parent,prefix='unit_identity_')
        self.addCleanup(self.tmp.cleanup)
        self.ws=enable_object_identity(ScientificWorkspace(Path(self.tmp.name)/'case',OfficeWorld('confounding',9917,'office-business-v0.3')))
        self.roles=FrameworkRoles(self.ws,None,lambda role:None)

    def produce(self):
        result=self.ws.tool('analyst','run_python',{'code':"open('metric.csv','w').write('method,value\\nmisleading_label,2.0\\n')",'purpose':'opaque source link fixture','output_semantics':'producer declaration only'})
        path=result['data_outputs'][0]
        packet=self.ws.packets.create(path,'constructed fixture, not LLM discovery')
        return packet

    def test_real_output_code_receipt_links_and_provided_code_are_distinct(self):
        packet=self.produce()
        result=self.ws.tool('verifier','inspect_object',{'reference':packet['id']})
        self.assertEqual(result['object']['kind'],'analysis_output')
        codes=[r['object']for r in result['related_objects']if r['relation']=='producer_code']
        self.assertEqual(len(codes),1)
        self.assertEqual(codes[0]['sha256'],sha(self.ws.readable(codes[0]['path'])))
        self.assertNotIn('text',codes[0])
        code=self.ws.tool('verifier','inspect_object',{'reference':codes[0]['reference']})
        self.assertEqual(code['object']['kind'],'producer_code')
        supplied=self.ws.tool('verifier','inspect_object',{'reference':str(self.ws.public/'baseline.py')})
        self.assertEqual(supplied['object']['kind'],'provided_input')
        self.assertEqual(supplied['related_objects'],[])
        self.assertTrue(all('not verified' in d['authority']for d in result['producer_declarations']))

    def test_existing_role_gate_and_operational_memory_authority_remain(self):
        packet=self.produce()
        with self.assertRaisesRegex(ValueError,'independent review'):
            self.ws.tool('mechanist','inspect_object',{'reference':packet['id']})
        index=self.ws.workers['verifier'].directory/'framework_receipts/index.json'
        own=self.ws.tool('verifier','inspect_object',{'reference':str(index)})
        self.assertEqual(own['authority'],'operational_navigation_only')
        self.assertNotIn('reference',own)
        with self.assertRaisesRegex(ValueError,'another role'):
            self.ws.tool('mechanist','inspect_object',{'reference':str(index)})

    def test_forged_name_does_not_create_origin_and_changed_packet_fails(self):
        fake=self.ws.workers['verifier'].directory/'producer_code_baseline.py';fake.write_text('opaque = 1\n')
        result=self.ws.tool('verifier','inspect_object',{'reference':str(fake)})
        self.assertEqual(result['object']['kind'],'unlinked_artifact')
        self.assertEqual(result['packet_bindings'],[])
        packet=self.produce();code=next(e for e in packet['attachments']if e['kind']=='producer_code')
        Path(code['path']).write_text('changed = 2\n')
        with self.assertRaisesRegex(ValueError,'version changed'):
            self.ws.tool('verifier','inspect_object',{'reference':packet['id']})

    def test_manual_all_roles_and_relocation_keep_exact_origin(self):
        manual=json.loads((self.ws.public/'tool_manual.json').read_text())
        for role in ('manager','analyst','mechanist','verifier','engineer'):
            self.assertIn('inspect_object',manual['roles'][role])
        packet=self.produce()
        child=enable_object_identity(ScientificWorkspace(Path(self.tmp.name)/'child',OfficeWorld('confounding',9917,'office-business-v0.3'),resume_from=self.ws.root))
        FrameworkRoles(child,None,lambda role:None)
        result=child.tool('verifier','inspect_object',{'reference':packet['id']})
        self.assertTrue(result['object']['path'].startswith(str(child.root)))
        self.assertEqual(result['object']['sha256'],packet['artifact']['sha256'])


if __name__=='__main__':unittest.main()
