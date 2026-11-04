import json
import sqlite3
from ..common import digest
from ..paired_v07.guard import ProgressGuard as Previous, meaningful


class ProgressGuard(Previous):
    def fingerprint(self):
        values = []
        for body, in self.owner.db.execute("SELECT body FROM events WHERE json_extract(body,'$.tool')='inspect_evidence'"):
            result = json.loads(body)['result']
            if result.get('ok') and result.get('statistics'):
                values.append(digest(meaningful(result['statistics'])))
        for path in self.root.glob('reviews/*/critic/private/critic.sqlite'):
            with sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True) as db:
                for body, in db.execute("SELECT body FROM actions WHERE json_extract(body,'$.tool')='inspect_evidence'"):
                    result = json.loads(body)['result']
                    if result.get('ok') and result.get('statistics'):
                        values.append(digest(meaningful(result['statistics'])))
        return digest([super().fingerprint(),sorted(set(values))])
