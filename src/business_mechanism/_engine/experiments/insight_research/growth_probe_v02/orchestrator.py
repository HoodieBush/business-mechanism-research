import json
from ..common import digest, Pending
from ..paired_v16.guard import ProgressGuard as BeforeGuard
from ..paired_v16.orchestrator import ResearchRun as BeforeRun


class ProgressGuard(BeforeGuard):
    def fingerprint(self):
        observed = []
        for ref, in self.owner.db.execute("SELECT ref FROM files WHERE nature='new_observation' AND path LIKE '%/observations.json'"):
            path, _ = self.owner.file(ref)  # Validate actual received bytes.
            rows = json.loads(path.read_text())
            if rows: observed.append(digest(rows))
        return digest([super().fingerprint(),sorted(set(observed))])


class ResearchRun(BeforeRun):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.guard = ProgressGuard(self.root,self.ws,self.budget)
        self.journal.guard = self.guard
