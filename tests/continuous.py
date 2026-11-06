"""Exercise the real supervisor deadline, native graph and paid-batch drain locally."""
import argparse
import importlib.util
import http.server
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import threading
from acceptance import NativeFixture
from business_mechanism import create_project, project_status


def main(output):
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    data = output / 'input'
    data.mkdir()
    with sqlite3.connect(data / 'business.sqlite') as db:
        db.execute('CREATE TABLE observations(value INTEGER)')
        db.executemany('INSERT INTO observations VALUES (?)', [(i,) for i in range(1, 9)])
    (data / 'business_brief.md').write_text('Local engineering fixture only.')
    (data / 'data_dictionary.json').write_text(json.dumps({'tables': {'observations': {'columns': {'value': 'Fixture value'}}}}))
    fixture = NativeFixture()
    project = output / 'project'
    fixture.root = project

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            response = json.dumps(fixture.response(payload)).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(response)

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        model = {'model': 'local-supervisor-fixture', 'base_url': f'http://127.0.0.1:{server.server_port}/v1',
                 'request_timeout_seconds': 1, 'requires_api_key': False,
                 'generation_options': {'thinking': {'type': 'enabled'}, 'reasoning_effort': 'high', 'max_tokens': 65536}}
        create_project(project, 'Supervisor engineering fixture.', model, data=data,
                       limits={'token_allowance': 2**60, 'max_http_attempts': 2**31 - 1}, wall_seconds=120, max_stages=100)
        observation = output / 'observation'
        with (output / 'supervisor.log').open('w') as log:
            process = subprocess.run([sys.executable, '-u', str(Path(__file__).resolve().parents[1] / 'tools/run_continuous.py'),
                                      '--project', str(project), '--output', str(observation),
                                      '--duration-seconds', '8', '--heartbeat-seconds', '1', '--drain-seconds', '20'],
                                     stdout=log, stderr=subprocess.STDOUT, timeout=60)
        summary = json.loads((observation / 'summary.json').read_text())
        status = project_status(project)
        heartbeat = (observation / 'heartbeats.jsonl').read_text().splitlines()
        events = [json.loads(line) for line in (observation / 'events.jsonl').read_text().splitlines()]
        checks = {'supervisor_exit_success': process.returncode == 0,
                  'finite_observation_completed': summary['full_observation_window_completed'],
                  'real_graph_made_loopback_requests': status['execution_usage']['http_attempts'] > 0,
                  'all_reported_costs_retained': status['execution_usage']['reported_tokens'] == len(fixture.calls) * 25,
                  'multiple_heartbeats_written': len(heartbeat) >= 2,
                  'cooperative_deadline_pause_saved': (project / 'pause_requested.json').is_file(),
                  'child_drained_without_kill': not summary['forced_child_termination'],
                  'final_event_written': events[-1]['event'] == 'observation_ended'}
        spec = importlib.util.spec_from_file_location('tested_supervisor', Path(__file__).resolve().parents[1] / 'tools/run_continuous.py')
        supervisor = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(supervisor)
        event = supervisor.recovery_event_id(observation, 2)
        checks['migrated_observation_cannot_replay_old_recovery'] = (
            event != supervisor.recovery_event_id(output / 'predecessor-observation', 2)
            and event != 'supervisor-slice-2'
            and event == supervisor.recovery_event_id(observation / '.', 2)
            and event != supervisor.recovery_event_id(observation, 3)
            and len(event) <= 100)
        result = {'status': 'passed' if all(checks.values()) else 'failed', 'checks': checks,
                  'external_provider_calls': 0, 'local_fixture_http': len(fixture.calls)}
        (output / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
        print(json.dumps(result), flush=True)
        assert all(checks.values()), checks
    finally:
        server.shutdown()
        server.server_close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    main(parser.parse_args().output)
