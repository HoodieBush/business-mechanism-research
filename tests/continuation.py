"""Resume-first, inherited cost accounting and unchanged deadline, loopback only."""
import argparse
import http.server
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import threading
import time
from business_mechanism import create_project, close_project_stage
from business_mechanism.service import open_project, request_pause
from experiments.insight_research.common import digest
from business_workflow import BusinessFixture


def main(output):
    output.mkdir(parents=True, exist_ok=False)
    data=output/'data';data.mkdir()
    with sqlite3.connect(data/'business.sqlite') as db:
        db.execute('CREATE TABLE observations(value INTEGER)')
        db.executemany('INSERT INTO observations VALUES (?)',[(i,) for i in range(1,9)])
    (data/'business_brief.md').write_text('Synthetic continuation fixture only.')
    (data/'data_dictionary.json').write_text('{}')
    fixture=BusinessFixture();fixture.close_before_review=True
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            raw=json.dumps(fixture.response(json.loads(self.rfile.read(int(self.headers['Content-Length']))))).encode()
            self.send_response(200);self.end_headers();self.wfile.write(raw)
        def log_message(self,*args):pass
    server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    model={'model':'continuation-fixture','base_url':f'http://127.0.0.1:{server.server_port}/v1',
           'request_timeout_seconds':1,'requires_api_key':False,'generation_options':{'max_tokens':65536}}
    project=output/'project';fixture.root=project
    try:
        create_project(project,'Synthetic continuation.',model,data=data,
            limits={'token_allowance':2**60,'max_http_attempts':2**31-1},wall_seconds=120,max_stages=100)
        _,_,ws,backend=open_project(project)
        try:
            payload={'model':'fixture','max_tokens':10,'messages':[{'role':'user','content':'Synthetic previously paid request'}]}
            backend.budget.reserve('inherited-fixture','researcher',payload)
            backend.budget.settle('inherited-fixture',digest(payload),{'total_tokens':25})
            with backend.budget.connect() as db:
                native_deadline=db.execute('SELECT deadline FROM execution_control').fetchone()[0]
        finally:ws.close()
        close_project_stage(project,reason='Known inherited fixture loop closed without new scientific clearance.',
                            unresolved_refs=[],evidence_refs=[],event_id='inherited-stage')
        request_pause(project,'fixture paused before continuation')
        deadline=time.time()+8
        observer=output/'observer'
        with (output/'supervisor.log').open('w') as log:
            process=subprocess.run([sys.executable,'-u',str(Path(__file__).resolve().parents[1]/'tools/run_continuous.py'),
                '--project',str(project),'--output',str(observer),'--resume-first','--deadline-unix',str(deadline),
                '--heartbeat-seconds','1','--drain-seconds','20','--continuation-of',str(output/'prior-run.json')],
                stdout=log,stderr=subprocess.STDOUT,timeout=60)
        manifest=json.loads((observer/'run.json').read_text());summary=json.loads((observer/'summary.json').read_text())
        with sqlite3.connect(project/'common_budget.sqlite') as db:
            after_deadline=db.execute('SELECT deadline FROM execution_control').fetchone()[0]
            inherited=db.execute("SELECT actual,status FROM attempts WHERE key='inherited-fixture'").fetchone()
        checks={'supervisor_finished':process.returncode==0,
                'first_controller_explicitly_resumed':manifest['resume_first'] and len(fixture.calls)>0,
                'inherited_requests_are_separate_from_segment':manifest['initial_snapshot']['requests']==1 and summary['segment_usage']['requests']==len(fixture.calls),
                'inherited_and_new_tokens_not_reset':summary['final_snapshot']['reported_tokens']==25*(len(fixture.calls)+1),
                'prior_paid_row_preserved':inherited==(25,'settled'),
                'outer_deadline_exact':manifest['deadline_unix']==deadline,
                'native_original_deadline_unchanged':after_deadline==native_deadline,
                'window_completed':summary['full_observation_window_completed'],
                'paid_batch_drained_without_kill':not summary['forced_child_termination']}
        assert all(checks.values()),checks
        result={'passed':True,'checks':checks,'local_fixture_http':len(fixture.calls),'external_provider_calls':0}
        (output/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
    finally:
        server.shutdown();server.server_close()


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True,type=Path)
    main(parser.parse_args().output.resolve())
