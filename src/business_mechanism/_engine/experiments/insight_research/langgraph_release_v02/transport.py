"""Persistent bounded backoff; native journals retain errors and all charges."""
import json
import time
from ..common import Pending, write_json


def transient(record):
    return (not (record.get('response') or {}).get('choices') and
            (record.get('http_status') in (429, 500, 502, 503, 504) or
             record.get('error_type') in ('timeout', 'network', 'transport')))


class Cooldown:
    def call(self, payload):
        if not self.state.get('inflight') and not self.state.get('delivery'):
            n = self.state['attempts']
            path = self.ws.private/'http'/f'{n}.json'
            if n and path.exists() and transient(json.loads(path.read_text())):
                marker = self.ws.private/'transport_cooldown.json'
                saved = json.loads(marker.read_text()) if marker.exists() else {}
                if saved.get('after_attempt') != n:
                    streak = 1
                    for i in range(n-1, 0, -1):
                        old = self.ws.private/'http'/f'{i}.json'
                        if not old.exists() or not transient(json.loads(old.read_text())):
                            break
                        streak += 1
                    saved = {'after_attempt': n, 'failure_streak': streak,
                             'until_unix': time.time()+min(60, 30*2**min(streak-1, 1))}
                    write_json(marker, saved)
                if time.time() < saved['until_unix']:
                    raise Pending('transport_cooldown:'+str(saved['until_unix']))
        return super().call(payload)
