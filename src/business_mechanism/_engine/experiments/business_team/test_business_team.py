"""Meaningful data, isolation, handoff and science-boundary checks."""
import json
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
import pandas as pd
from execution import PythonWorkspace
from world import OfficeWorld, operating_orders
from workspace import ResearchWorkspace
from team import validate, SCHEMAS, decode_actions, ResearchTeam
from contracts import FIELD_MEANINGS, HOURS, OPENING_HOURS
from transport import retryable, retry_delay


class BusinessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Inside project (not global /tmp, which is allowed only to the child).
        cls.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent, prefix="unit_")
        cls.root = Path(cls.temp.name)
        cls.ws = ResearchWorkspace(cls.root / "opaque", OfficeWorld("relationship", 7100),require_artifact_review=False)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_public_boundary_and_inventory_conservation(self):
        h = self.ws.history
        self.assertTrue((h.opening_stock+h.restock-h.sales==h.closing_stock).all())
        self.assertFalse({"demand", "world", "beta", "true_demand", "traffic"} & set(h.columns))
        context = json.dumps(self.ws.initial_context())
        self.assertNotIn('"relationship"', context)
        self.assertNotIn("world.py", context)

    def test_fault_is_observable_without_hidden_demand(self):
        h, _ = OfficeWorld("record_fault", 7100).generate(0, 7)
        self.assertGreater(int((h.opening_stock-h.sales!=h.closing_stock).sum()), 0)
        corrected, _ = OfficeWorld("record_fault", 7100).generate(0, 7, corrected=True)
        self.assertTrue((corrected.opening_stock-corrected.sales==corrected.closing_stock).all())

    def test_code_can_analyze_and_plot(self):
        r = self.ws.workers["analyst"].run('import os,pandas as pd,matplotlib.pyplot as plt\nd=pd.read_csv(os.environ["PUBLIC_DIR"]+"/history.csv")\nplt.plot([1,2]);plt.savefig("qa.png");print(len(d))')
        self.assertTrue(r["ok"], r)
        self.assertTrue((self.ws.workers["analyst"].directory/"qa.png").exists())

    def test_code_cannot_read_private_or_write_outside(self):
        secret = self.root / "private_sentinel.txt"
        secret.write_text("private-fixture-not-credential")
        forbidden = Path(__file__).parent / "world.py"
        r = self.ws.workers["analyst"].run(f'''import json,os
out={{}}
for k,p in {{"private":{str(secret)!r},"generator":{str(forbidden.resolve())!r}}}.items():
 try: open(p).read();out[k]="LEAK"
 except PermissionError:out[k]="blocked"
try: open({str(self.root/'outside.txt')!r},"w").write("bad");out["write"]="LEAK"
except PermissionError:out["write"]="blocked"
out["credential_env_absent"]=os.environ.get("AGI_RESEARCH_API_KEY") is None
print(json.dumps(out))''')
        self.assertTrue(r["ok"], r)
        self.assertEqual(json.loads(r["stdout"]), {"private":"blocked","generator":"blocked","write":"blocked","credential_env_absent":True})

    def test_network_is_blocked(self):
        r = self.ws.workers["analyst"].run('import socket\ntry:\n socket.create_connection(("1.1.1.1",443),timeout=2);print("LEAK")\nexcept PermissionError:print("blocked")')
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["stdout"].strip(), "blocked")

    def test_sql_readonly_and_reference_access(self):
        self.assertEqual(self.ws.query("analyst", "SELECT count(*) n FROM hourly")["preview"][0]["n"], len(self.ws.history))
        for q in ("DELETE FROM hourly", "ATTACH DATABASE '/tmp/x.db' AS x"):
            with self.assertRaises(Exception):
                self.ws.query("analyst", q)
        with self.assertRaises(ValueError):
            self.ws.readable(Path(__file__).parent/"world.py")

    def test_role_permissions_and_schema(self):
        with self.assertRaises(ValueError):
            self.ws.tool("analyst", "save_hypothesis", {})
        with self.assertRaises(ValueError):
            validate({"code":"print(1)","repair":True}, SCHEMAS["run_python"])

    def test_independent_native_batch_and_terminal_order(self):
        calls=[{"id":"one","type":"function","function":{"name":"read_context","arguments":"{}"}},
               {"id":"two","type":"function","function":{"name":"query_data","arguments":json.dumps({"sql":"SELECT 1","output_semantics":"一行常量，非业务量"})}}]
        raw={"choices":[{"finish_reason":"tool_calls","message":{"tool_calls":calls}}]}
        self.assertEqual(len(decode_actions(raw,"analyst",SCHEMAS)),2)
        calls[1]["id"]="one"
        with self.assertRaises(ValueError):decode_actions(raw,"analyst",SCHEMAS)

    def test_hypothesis_parent_and_immutable_handoff(self):
        source = self.ws.workers["analyst"].directory / "report.md"
        source.write_text("observed result")
        result = self.ws.tool("analyst", "submit_result", {"summary":"finding","evidence_files":[str(source)],"findings":[],"next_step":"review"})
        source.write_text("later analysis")
        self.assertEqual(Path(result["evidence_files"][0]).read_text(), "observed result")
        h = self.ws.tool("mechanist", "save_hypothesis", {"explanation":"test relation","scope":"received sites", "alternatives":["traffic"],"prediction":"positive effect","falsification":"no effect","evidence_files":result["evidence_files"],"change_reason":"new"})
        h2 = self.ws.tool("mechanist", "save_hypothesis", {"explanation":"conditional relation","scope":"narrower", "alternatives":["traffic"],"prediction":"conditional effect","falsification":"no effect","evidence_files":result["evidence_files"],"change_reason":"counterexample","parent_id":h["id"]})
        self.assertEqual(h2["parent_id"], h["id"])

    def test_poisson_order_limits(self):
        f = self.ws.world.features(112, 1)
        orders = operating_orders(f, [2.]*len(f))
        self.assertTrue(all(0<=q<=50 for q in orders.values()))

    def test_new_trial_plan_and_no_self_training(self):
        source = str(self.ws.public/"history.csv")
        h = self.ws.tool("mechanist", "save_hypothesis", {"explanation":"supply","scope":"S01","alternatives":["traffic"],"prediction":"positive","falsification":"zero","evidence_files":[source],"change_reason":"new"})
        before = (self.ws.public/"history.csv").read_bytes()
        args={"hypothesis_id":h["id"],"kind":"supply_trial","support_sku":"S11","product_ids":["S01"],"days":14,"prediction":"positive","controls":"same stock and price","analysis_plan":"site-day contrast"}
        result=self.ws.tool("verifier","run_experiment",args)
        self.assertTrue((Path(result["observations"]).parent/"registered_plan.json").exists())
        self.assertEqual((self.ws.public/"history.csv").read_bytes(),before)
        self.assertEqual(result["summary"]["alpha"],.025)
        self.assertGreater(result["summary"]["mean_daily_sales_difference"],0)

    def test_complete_meanings_and_business_time(self):
        definitions=json.loads((self.ws.public/"data_dictionary.json").read_text())
        self.assertEqual(set(self.ws.history.columns),set(definitions["history_csv"]["columns"]))
        for table in definitions["tables"].values():
            self.assertTrue(table["row_grain"])
            for meaning in table["columns"].values():self.assertEqual(set(meaning),{"meaning","unit","aggregation"})
        self.assertEqual(tuple(sorted(self.ws.history.hour.unique())),HOURS)
        self.assertTrue((pd.read_csv(self.ws.public/"sites.csv").opening_hours==OPENING_HOURS).all())
        self.assertIn("不能求和",FIELD_MEANINGS["opening_stock"][2])

    def test_semantics_follow_query_and_immutable_handoff(self):
        q=self.ws.query("analyst","SELECT site,SUM(opening_stock) exposure FROM hourly GROUP BY site","一行每柜点；exposure是库存小时暴露，非日开库存")
        self.assertTrue(q["aggregation_warnings"])
        result=self.ws.tool("analyst","submit_result",{"summary":"库存暴露需区分","evidence_files":[q["file"]],"findings":[],"next_step":"复核"})
        received=self.ws.tool("verifier","read_artifact",{"path":result["evidence_files"][0]})
        self.assertIn("非日开库存",received["metadata"]["output_semantics"])
        self.assertEqual(received["sha256"],received["metadata"]["artifact_sha256"])
        self.assertTrue(received["metadata"]["source_field_definitions"])

    def test_rewritten_python_output_preserved_with_meaning(self):
        a={"code":"open('meaning.csv','w').write('x\\n1\\n')","purpose":"初值","output_semantics":"一行测试计数"}
        self.ws.tool("analyst","run_python",a)
        a.update(code="open('meaning.csv','w').write('x\\n2\\n')",purpose="修订")
        r=self.ws.tool("analyst","run_python",a)
        path=str(self.ws.workers["analyst"].directory/"meaning.csv")
        self.assertIn(path,r["generated_files"])
        self.assertEqual(Path(r["replaced_versions"][path]).read_text(),'x\n1\n')
        self.assertEqual(json.loads(Path(path+".meta.json").read_text())["purpose"],"修订")

    def test_no_task_call_quota_and_manual_matches_tools(self):
        manual=json.loads((self.ws.public/"tool_manual.json").read_text())
        self.assertEqual(manual["tools"]["run_python"]["parameters"],SCHEMAS["run_python"])
        count=[0]
        def fake(config,payload):
            count[0]+=1
            action={"tool":"read_history","arguments":{}} if count[0]<=13 else {"tool":"submit_result","arguments":{
                "summary":"mock protocol completion","evidence_files":[],"findings":[],"next_step":"test only"}}
            return {"response":{"choices":[{"finish_reason":"stop","message":{"content":json.dumps(action)}}],"usage":{"total_tokens":1}}}
        team=ResearchTeam(self.ws,{"model":"unit-mock"},{"max_output_tokens":100,"round_reported_token_budget":1000000},[])
        with patch("team.request_model",fake):result=team.run_role("analyst",{"question":"protocol test","inputs":[]})
        self.assertEqual(count[0],14)
        self.assertEqual(result["summary"],"mock protocol completion")

    def test_retry_wait_and_identical_request_without_scientific_failure(self):
        before=len(self.ws.state['events']);received=[]
        def fake(config,payload):
            received.append(json.loads(json.dumps(payload)))
            if len(received)<=2:return {'request':payload,'error_type':'transport','error':'RemoteDisconnected'}
            action={'tool':'read_history','arguments':{}} if len(received)==3 else {'tool':'submit_result','arguments':{'summary':'transport recovered mock','evidence_files':[],'findings':[],'next_step':'test only'}}
            return {'request':payload,'response':{'choices':[{'finish_reason':'stop','message':{'content':json.dumps(action)}}],'usage':{'total_tokens':1}}}
        team=ResearchTeam(self.ws,{'model':'unit-mock'},{'max_output_tokens':100,'round_reported_token_budget':1000000},[])
        with patch('team.request_model',fake),patch('transport.interruptible_wait') as wait:
            team.run_role('analyst',{'id':'NET_FIXTURE','question':'mock recovery','inputs':[]})
        self.assertEqual(len(received),4);self.assertEqual(received[0],received[1]);self.assertEqual(received[1],received[2]);self.assertEqual(wait.call_count,2)
        self.assertEqual([e['tool'] for e in self.ws.state['events'][before:]],['read_history','submit_result'])
        self.assertTrue(retryable({'http_status':429,'error_type':'http'}));self.assertFalse(retryable({'http_status':401,'error_type':'http'}))
        self.assertEqual(retry_delay({'retry_after':'30'},1,{'initial_wait_seconds':3,'backoff_multiplier':2,'maximum_wait_seconds':45},jitter=0),30)

    def test_tool_replay_and_process_restart_preserve_completed_result(self):
        args={'code':'print("executed once")','purpose':'mock idempotence','output_semantics':'a test string, not business evidence'}
        worker=self.ws.workers['analyst'];before=worker.count
        one=self.ws.tool('analyst','run_python',args,operation_id='UNIT_exact_once')
        two=self.ws.tool('analyst','run_python',args,operation_id='UNIT_exact_once')
        self.assertEqual(one,two);self.assertEqual(worker.count,before+1)
        previous=json.loads((self.ws.root/'team_checkpoint.json').read_text())['frames']['analyst']
        team=ResearchTeam(self.ws,{'model':'unit-mock'},{'max_output_tokens':100,'round_reported_token_budget':1000000},[])
        with patch('team.request_model',side_effect=AssertionError('must not call API for completed task')):
            restored=team.run_role('analyst',previous['task'])
        self.assertEqual(restored,previous['result'])

    def test_unfinished_dialogue_restart_does_not_repeat_completed_analysis(self):
        args={'id':'INTERRUPT_FIXTURE','question':'checkpoint test','inputs':[]};calls=[0]
        def initial(config,payload):
            calls[0]+=1
            if calls[0]==2:raise KeyboardInterrupt()
            return {'request':payload,'response':{'choices':[{'finish_reason':'stop','message':{'content':json.dumps({'tool':'read_history','arguments':{}})}}],'usage':{'total_tokens':1}}}
        team=ResearchTeam(self.ws,{'model':'unit-mock'},{'max_output_tokens':100,'round_reported_token_budget':1000000},[])
        before=len(self.ws.state['events'])
        with patch('team.request_model',initial):
            with self.assertRaises(KeyboardInterrupt):team.run_role('analyst',args)
        checkpoint=json.loads((self.ws.root/'team_checkpoint.json').read_text())
        messages=checkpoint['frames']['analyst']['messages']
        db_before=(self.ws.public/'business.sqlite').read_bytes()
        restored_ws=ResearchWorkspace(self.ws.root,self.ws.world,reopen=True)
        self.assertEqual(db_before,(restored_ws.public/'business.sqlite').read_bytes())
        resumed=ResearchTeam(restored_ws,{'model':'unit-mock'},{'max_output_tokens':100,'round_reported_token_budget':1000000},[])
        def finish(config,payload):
            self.assertEqual(payload['messages'],messages)
            return {'request':payload,'response':{'choices':[{'finish_reason':'stop','message':{'content':json.dumps({'tool':'submit_result','arguments':{'summary':'restored mock','evidence_files':[],'findings':[],'next_step':'test only'}})}}],'usage':{'total_tokens':1}}}
        with patch('team.request_model',finish):resumed.run_role('analyst',args)
        self.assertEqual([e['tool'] for e in restored_ws.state['events'][before:]],['read_history','submit_result'])

    def test_trial_receipt_recovery_does_not_repeat_sampling(self):
        hypothesis=self.ws.state['hypotheses'][0]['id']
        args={'hypothesis_id':hypothesis,'kind':'supply_trial','support_sku':'S11','product_ids':['S01'],'days':14,'prediction':'test','controls':'fixed','analysis_plan':'site-day'}
        before=len(self.ws.state['experiments'])
        first=self.ws.tool('verifier','run_experiment',args,operation_id='UNIT_trial_once')
        receipt=self.ws.root/'tool_receipts/UNIT_trial_once.json';saved=json.loads(receipt.read_text());saved['status']='prepared';receipt.write_text(json.dumps(saved))
        with patch.object(self.ws.world,'generate',side_effect=AssertionError('must not generate observations twice')):
            second=self.ws.tool('verifier','run_experiment',args,operation_id='UNIT_trial_once')
        self.assertEqual(first,second);self.assertEqual(len(self.ws.state['experiments']),before+1)


if __name__ == "__main__":
    unittest.main()
