"""Release graph adds cooperative pause and delivery after every safe turn."""
from contextlib import contextmanager
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command
from experiments.insight_research.langgraph_release_v02.graph import ResearchGraph as Previous, export_handoff
from .delivery import export_report


class ResearchGraph(Previous):
    def select(self, state):
        pause = self.backend.root/'pause_requested.json'
        if pause.exists():
            return {'route': 'pause', 'status': 'pending', 'reason': 'operator requested pause; current paid tool batch drained'}
        result = super().select(state)
        export_handoff(self.backend, result.get('status', 'running'), result.get('reason', 'safe turn checkpoint'))
        export_report(self.backend)
        return result

    def deliver(self, state):
        result = super().deliver(state)
        export_report(self.backend)
        return result

    def invoke(self, *, resume=False):
        # Earlier reports may become obsolete after new, version-bound feedback.
        # Restart the selector with the same counters, never return a stale END.
        current = self.graph.get_state(self.config)
        if current.values.get('status') == 'completed' and not self.backend.ws.report():
            self.graph.update_state(self.config, {'status': 'running', 'reason': ''}, as_node='pause')
        result = super().invoke(resume=resume)
        export_report(self.backend)
        return result


@contextmanager
def open_graph(backend, *, thread_id, max_turns=80):
    with SqliteSaver.from_conn_string(str(backend.root/'graph_checkpoints.sqlite')) as saver:
        yield ResearchGraph(backend, saver, thread_id=thread_id, max_turns=max_turns)
