from copy import deepcopy
from ..growth_probe_v01.workspace import ResearchWorkspace as Previous


class ResearchWorkspace(Previous):
    def tool_schemas(self):
        tools=deepcopy(super().tool_schemas())
        for tool in tools:
            function=tool['function'];parameters=function['parameters'];props=parameters.get('properties',{})
            if function['name']=='save_hypothesis':
                props['effect_prediction']={'type':'null','description':
                    'This optional inventory supply-trial structure is unavailable in a service deployment. Use null; keep the full numeric prediction, units, threshold and scope in prediction/scope.'}
                parameters.get('$defs',{}).pop('EffectPrediction',None)
            if function['name']=='register_test':
                props['mode']={'type':'string','enum':['observational'], 'description':
                    'Analyze received data; collection/intervention occurs separately via collect_evidence. Preserve the actual receipt nature in scientific interpretation.'}
                props['protocol_id']={'type':'null'}
                props['outcome_product_ids']={'type':'array','items':{'type':'string'},'maxItems':0}
                props['outcome_groups']={'type':'object','additionalProperties':False,'maxProperties':0}
        return tools

    def _checked_dispatch(self,name,args,key):
        # Keep the internal legacy parser for exact already-paid submissions.
        # Unsupported arguments receive durable normal rejection; never read
        # nonexistent inventory tables or silently delete the numeric intent.
        if name=='save_hypothesis' and args.get('effect_prediction') is not None:
            raise ValueError('Inventory-specific effect_prediction is unavailable in this service deployment. Resubmit with effect_prediction=null and preserve your numeric prediction, threshold, units and scope in the prediction/scope fields. No hypothesis was saved by this rejected call.')
        if name=='register_test' and (args['mode']!='observational' or args.get('protocol_id') is not None or args.get('outcome_product_ids') or args.get('outcome_groups')):
            raise ValueError('Service research has no inventory SKU protocol or product groups. Use collect_evidence for actual new observations/interventions, then register an observational analysis of the received files; keep the source receipt nature explicit.')
        return super()._checked_dispatch(name,args,key)
