"""Actual sandbox and scripted full paths under the optional memory profile."""
import json
import os
from unittest.mock import patch
import test_process_integration as integration
from langgraph_migration.explicit_runtime import ExplicitRoles
from langgraph_migration.science import ScientificWorkspace
from langgraph_migration import research_memory as memory
from test_langgraph_migration import ScriptedModel
from world import OfficeWorld


class MemoryProcessTests(integration.ProcessIntegrationTests):
    def setUp(self):
        configured=os.environ.get('PROCESS_ACCEPTANCE_OUTPUT')
        if configured:
            with patch.dict(os.environ,{'PROCESS_ACCEPTANCE_OUTPUT':configured+'/memory_profile'}):super().setUp()
        else:super().setUp()
        def runtime(*args, **kwargs):
            return ExplicitRoles(*args, **kwargs, memory_profile=memory.PROFILE, recent_turns=1, max_request_bytes=65000)
        self.runtime_patch=patch.object(integration,'ExplicitRoles',side_effect=runtime)
        self.runtime_patch.start()
    def tearDown(self):
        self.runtime_patch.stop();super().tearDown()
    def test_owned_memory_files_denied_by_actual_actor_python(self):
        ws=ScientificWorkspace(self.root/'private_memory',OfficeWorld('confounding',9137,'office-business-v0.3'))
        marker='PRIVATE_WORKING_NOTE_CONTENT'
        model=ScriptedModel(sequence=[('save_working_note',{'summary':marker,'source_refs':[],
            'open_questions':['not resolved'],'next_steps':[]}),'not finished'])
        roles=ExplicitRoles(ws,None,lambda role:model,memory_profile=memory.PROFILE)
        roles.run('analyst',{'id':'privacy','question':'scripted privacy check','inputs':[],'execution_phase':'needs_analysis'})
        paths=list((ws.root/'research_memory').rglob('*.json'))+list((ws.root/'explicit_runtime_state').rglob('*.json'))
        self.assertTrue(paths)
        code='import json\nchecks=[]\nfor path in '+repr(list(map(str,paths)))+':\n try:\n  open(path).read();checks.append("LEAK")\n except PermissionError:checks.append("blocked")\nprint(json.dumps(checks))'
        result=ws.workers['verifier'].run(code)
        self.assertTrue(result['ok'],result)
        self.assertEqual(json.loads(result['stdout']),['blocked']*len(paths))
        self.assertNotIn(marker,(ws.shared/'research_history.json').read_text())
