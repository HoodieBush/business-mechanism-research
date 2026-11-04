"""Read-only evidence view for shared-data controls; no simulator dependency."""
import copy


class ReplayEvidence:
    def __init__(self,public_input,events):
        self.catalogs={"source":copy.deepcopy(public_input["catalog"])}
        self.cohorts=[]
        supply_checked=set();meter_checked={}
        for event in events:
            tool=event["request"]["tool"];args=event["request"]["args"];response=event["response"]
            if tool=="open_transfer":self.catalogs["adaptation"]=copy.deepcopy(response["catalog"])
            elif tool=="experiment":self.cohorts.append(copy.deepcopy(response))
            elif tool=="inspect_execution" and response["physical_opening"]>=response["n"]:
                supply_checked.add(args["experiment_id"])
            elif tool=="reconcile" and "experiment_id" in args:
                meter_checked[args["experiment_id"]]=response["verified_sales"]
        self.data=[]
        for r in self.cohorts:
            idx=r["experiment_id"]
            if (r["verified_supply"] or idx in supply_checked) and (r["verified_meter"] or idx in meter_checked):
                self.data.append((r,meter_checked.get(idx,r["observed_sales"])))
        self.transfer_open="adaptation" in self.catalogs

    def public_catalog(self,namespace):
        if namespace not in self.catalogs:raise ValueError("catalog not received in public trace")
        return copy.deepcopy(self.catalogs[namespace])

    def verified_observations(self):
        return copy.deepcopy(self.data)
