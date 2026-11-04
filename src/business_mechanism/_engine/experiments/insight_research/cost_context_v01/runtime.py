"""Opt-in researcher integration; owned checkpoint and paid delivery stay logical."""
import hashlib
import json

from ..common import Pending, encoded, write_json
from ..growth_probe_v05.orchestrator import ResearchRuntime as PreviousRuntime
from ..growth_probe_v10.orchestrator import ResearchRun as PreviousRun
from ..paired_v01.budget import StudyJournal
from .wire import organize, current_context


class ContextStudyJournal(StudyJournal):
    def persist_request(self, attempt, payload):
        if not self.memory:
            return super().persist_request(attempt, payload)
        _, context = current_context(payload)
        # Same exact message-object format and reconstruction contract as the
        # original MemoryJournal. Retrievals use the actual wire view, not index1.
        objects = self.ws.private / 'message_objects'
        objects.mkdir(exist_ok=True)
        refs = []
        for message in payload['messages']:
            raw = json.dumps(message, ensure_ascii=False, allow_nan=False).encode()
            ref = hashlib.sha256(raw).hexdigest()
            path = objects / (ref + '.json')
            if path.exists() and path.read_bytes() != raw:
                raise Pending('message archive hash collision or corruption')
            if not path.exists():
                path.write_bytes(raw)
            refs.append(ref)
        from ..common import digest
        fields = [[k, refs if k == 'messages' else v] for k, v in payload.items()]
        write_json(self.ws.private / 'requests' / (str(attempt) + '.json'), {
            'format': 'message_objects_v1', 'fields': fields, 'payload_sha256': digest(payload)})
        selection = context.get('memory_selection', {})
        with self.ws.db:
            self.ws.db.execute('INSERT OR IGNORE INTO retrievals VALUES (?,?)', (attempt, encoded({
                'attempt': attempt, 'status': 'request_prepared',
                'focus': context.get('focus_hypothesis_refs', []),
                'context_sha256': digest(context), 'context_layout': 'stable-prefix-v1', **selection})))


class ResearchRuntime(PreviousRuntime):
    def payload(self, messages=None):
        return organize(super().payload(messages))


class ResearchRun(PreviousRun):
    def __init__(self, root, workspace, model, study_budget, **kwargs):
        if kwargs.get('owner_journal') is not None:
            raise ValueError('context candidate supplies its own explicit journal')
        journal = ContextStudyJournal(workspace, model, study_budget, 'researcher', memory=True)
        super().__init__(root, workspace, model, study_budget, owner_journal=journal, **kwargs)
        self.runtime = ResearchRuntime(workspace, model, journal=self.journal)
