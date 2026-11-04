"""Migration rejection contracts; successful real checkpoint probe is separate."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from memory_continuation import manual_change,compare_bindings,migrate_checkpoints
from explicit_continuation import identity_hash


class MemoryContinuationTests(unittest.TestCase):
    def test_manual_allows_declared_changes_but_rejects_other_schema_or_role_grants(self):
        original={'roles':{'mechanist':['read_history']},'tools':{'read_history':{'parameters':{}},
            'resume_task':{'description':'old'},'record_verdict':{'parameters':{'properties':{'evidence_files':{'description':'old'}}}}}}
        target=deepcopy(original)
        target['roles']['mechanist'] += ['search_memory','read_memory','save_working_note']
        target['tools'].update({name:{} for name in ('search_memory','read_memory','save_working_note')})
        target['tools']['read_history']={'parameters':{'cursor':True}}
        target['tools']['resume_task']['description']='new help'
        target['tools']['record_verdict']['parameters']['properties']['evidence_files']['description']='exact returned refs'
        manual_change(original,target)
        bad=deepcopy(target);bad['roles']['mechanist'].append('run_python')
        with self.assertRaisesRegex(ValueError,'role permissions'):manual_change(original,bad)
        bad=deepcopy(target);bad['tools']['record_verdict']['parameters']['properties']['status']={'const':'supported'}
        with self.assertRaisesRegex(ValueError,'undeclared'):manual_change(original,bad)
    def test_bindings_allow_only_explicit_manual_and_path_relocation(self):
        a={'/parent/public/tool_manual.json':{'sha256':'old'},'/parent/public/data.csv':{'sha256':'data'},'role_prompts':{'analyst':'original'}}
        b={'/child/public/tool_manual.json':{'sha256':'new'},'/child/public/data.csv':{'sha256':'data'},'role_prompts':{'analyst':'original'}}
        compare_bindings(a,b,['/parent','/child'])
        for key in ('/child/public/data.csv','role_prompts'):
            changed=deepcopy(b);changed[key]={'changed':True}
            with self.assertRaisesRegex(ValueError,'scientific inputs'):compare_bindings(a,changed,['/parent','/child'])
    def test_pending_paid_tool_batch_is_rejected_before_checkpoint_write(self):
        old={'compaction':'none','slice_steps':8,'max_request_bytes':128000}
        new={**old,'compaction':'research_memory_v1','recent_turns':4,'request_boundary':'new'}
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);parent=root/'parent';child=root/'child';p=child/'explicit_runtime_state'/'analyst';p.mkdir(parents=True)
            identity={'task':{'id':'T1'},'runtime':old,'input_versions':{}}
            state={'identity':identity,'pending':True};path=p/(identity_hash(identity)+'.json');path.write_text(json.dumps(state));before=path.read_bytes()
            ws=SimpleNamespace(root=child,path_aliases={str(parent):str(child)})
            with self.assertRaisesRegex(ValueError,'settled paid'):migrate_checkpoints(ws,parent,SimpleNamespace(policy=new),old)
            self.assertEqual(path.read_bytes(),before)
    def test_migration_cannot_disguise_a_larger_context_limit_or_slice(self):
        old={'compaction':'none','slice_steps':8,'max_request_bytes':128000}
        for change in ({'slice_steps':99},{'max_request_bytes':900000}):
            new={**old,**change,'compaction':'research_memory_v1','recent_turns':4}
            with self.assertRaisesRegex(ValueError,'changed slices'):migrate_checkpoints(SimpleNamespace(),None,SimpleNamespace(policy=new),old)


if __name__=='__main__':unittest.main()
