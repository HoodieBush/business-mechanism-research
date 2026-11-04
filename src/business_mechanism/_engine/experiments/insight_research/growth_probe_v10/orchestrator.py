import json
import shutil
from ..common import Pending, digest, sha, write_json
from ..growth_probe_v03.orchestrator import ResearchRun as Previous
from ..growth_probe_v05.orchestrator import ResearchRuntime
from .evidence import export_snapshot


class ResearchRun(Previous):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.runtime = ResearchRuntime(self.ws, self.model, journal=self.journal)

    def prepare_job(self, job):
        target = self.ws.record(job['target_ref'])
        if target['record_type'] != 'state' or not target.get('historical_field_reviews'):
            return super().prepare_job(job)
        directory = self.root / 'reviews' / job['ref']
        inputs = directory / 'inputs'
        if not inputs.exists():
            staging = directory / 'projection_pending'
            if staging.exists():
                if digest(target) != job['target_version']:
                    raise Pending('Field review target changed before projection recovery.')
                shutil.rmtree(staging)  # Unpaid projection only; no paid work.
            export_snapshot(self.ws, staging, job['target_ref'])
            packet = json.loads((staging / 'packet.json').read_text())
            if job['parent_review_ref']:
                packet['previous_feedback'] = self.ws.record(job['parent_review_ref'])
                packet['researcher_responses'] = [b for b in self.ws.records('review_response') if b['review_ref'] == job['parent_review_ref']]
            write_json(staging / 'packet.json', packet)
            manifest = json.loads((staging / 'manifest.json').read_text())
            manifest['files_sha256']['packet.json'] = sha(staging / 'packet.json')
            write_json(staging / 'manifest.json', manifest)
            staging.rename(inputs)
        packet = json.loads((inputs / 'packet.json').read_text())
        if packet['target_ref'] != job['target_ref'] or packet['target_version'] != job['target_version']:
            raise Pending('Field review projection target/version changed.')
        with self.ws.db:
            old = self.ws.db.execute('SELECT manifest_sha FROM review_inputs WHERE job_ref=?', (job['ref'],)).fetchone()
            if old and old[0] != sha(inputs / 'manifest.json'):
                raise Pending('Field review projection changed after receipt.')
            self.ws.db.execute('INSERT OR IGNORE INTO review_inputs VALUES (?,?,?)',
                (job['ref'], str(inputs), sha(inputs / 'manifest.json')))
        return inputs
