"""Optional continuation resource policy; no additional research agents/tools."""
from copy import deepcopy
from pathlib import Path

from .common import digest, sha
from .continuation import ContinuationWorkspace

CLOSEOUT_TOOLS = frozenset(('record_assessment', 'update_research_state', 'finish_research'))


class CloseoutWorkspace(ContinuationWorkspace):
    def __init__(self, root, question, world, settings, *, reopen=False):
        settings = deepcopy(settings)
        settings['closeout_sources'] = {n: sha(Path(__file__).parent / n) for n in
            ('closeout.py', 'runtime_closeout.py', 'run_closeout.py')}
        self.closeout_mode = False
        super().__init__(root, question, world, settings, reopen=reopen)

    def _checked_dispatch(self, name, args, key):
        if self.closeout_mode and name not in CLOSEOUT_TOOLS:
            raise ValueError('Resource closeout is active: use record_assessment, update_research_state or finish_research. Save uncertainties and needed evidence honestly; no conclusion is required.')
        if name == 'read_context':
            context = self.context()
            return {'context_location': 'The second message is the automatically refreshed full research context.',
                'refresh': 'Updated before every model request; not repeated inside this tool reply.',
                'context_sha256': digest(context), 'archive_counts': context['archive_counts'],
                'state_ref': (self.state() or {}).get('ref'),
                'unincorporated_result_refs': [r['ref'] for r in context['unincorporated_results']],
                'originals': 'Full source, scope and evidence remain in the fixed view and exact read_artifact/read_memory references.'}
        return super()._checked_dispatch(name, args, key)
