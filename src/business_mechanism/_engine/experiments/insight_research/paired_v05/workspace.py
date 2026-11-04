from ..paired_v03.workspace import ResearchWorkspace as Previous


class ResearchWorkspace(Previous):
    def _checked_dispatch(self,name,args,key):
        # Tool availability is not a token reservation. Shared admission,
        # sandbox, trial limits, references and publication gates still apply.
        self.closeout_mode=False
        return super()._checked_dispatch(name,args,key)

    def context(self):
        context=super().context()
        context['resource_policy']='All original research tools remain available. Budget/HTTP admission is hard; low-resource signals request a lawful checkpoint, not a shutdown of hypothesis/test creation. Scientific uncertainty is separate from execution pause.'
        return context
