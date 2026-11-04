from copy import deepcopy
from pathlib import Path
from ..common import digest, sha
from ..growth_probe_v09.workspace import ResearchWorkspace as Previous


def changed_sources(item):
    return {(a['source_ref'], a['source_version']) for a in item.get('historical_field_reviews', [])
            if a['decision'] in ('replace', 'withdraw')}


class ResearchWorkspace(Previous):
    def __init__(self, root, question, world, settings, **kwargs):
        settings = deepcopy(settings)
        settings['field_revision_review_source'] = sha(Path(__file__))
        super().__init__(root, question, world, settings, **kwargs)

    def _checked_dispatch(self, name, args, key):
        if name == 'update_research_state' and len(changed_sources(args)) > 1:
            raise ValueError('Split changed historical source versions into separate checkpoints so each field-review lineage remains bounded. Correct retained fields may share their source checkpoint.')
        return super()._checked_dispatch(name, args, key)

    def add(self, kind, body):
        item = super().add(kind, body)
        if kind == 'state' and changed_sources(item) and self.jobs_ready:
            key = changed_sources(item)
            prior = [j for j in self.jobs() if j['target_ref'] != item['ref']
                and self.record(j['target_ref'])['record_type'] == 'state'
                and changed_sources(self.record(j['target_ref'])) == key]
            self.enqueue(item['ref'], parent=prior[-1]['target_ref'] if prior else None,
                reason='New exact historical-field interpretation. Review the actual changed state fields against their received original and evidence; no automatic role call or scientific certification.')
        return item

    def premise(self, ref):
        super().premise(ref)
        if not ref.startswith(('file:', 'card:')):
            item = self.record(ref)
            if item['record_type'] == 'state' and changed_sources(item) and not self.clearance(ref):
                raise ValueError('Historical-field revision state is an unreviewed/disputed candidate, not a strong factual premise. Cite original data, inspect its exact review job and respond with actual field/evidence changes.')

    def field_actions(self, source_ref, version):
        actions = super().field_actions(source_ref, version)
        for action in actions.values():
            ref = action['revision_ref']
            if ref.startswith('archive:'):
                action['current_review'] = {'inherited_clearance': False,
                    'meaning': 'Prior owner interpretation remains historical, not a current review clearance.'}
            else:
                action['current_review'] = {'jobs': [j for j in self.jobs() if j['target_ref'] == ref],
                    'clearance_matches_current_version': self.clearance(ref),
                    'scientific_certification': False}
        return actions
