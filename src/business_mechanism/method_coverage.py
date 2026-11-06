"""Output-linked coverage gates and reference transformations, not truth checks."""
import json
import operator
import re
import hashlib
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field


class CoverageCheck(BaseModel):
    model_config = ConfigDict(extra='forbid')
    component: Literal['claim_evidence', 'data_scope', 'sampling', 'grouping', 'transformation', 'estimator', 'numeric_claim', 'record_fidelity']
    action_ref: str
    output_pointer: str
    relation: Literal['eq', 'lt', 'le', 'gt', 'ge', 'contains']
    expected: Any
    basis: Literal['recomputed','source_inspected','record_checked'] = 'recomputed'
    justification: str | None = None
    method_fragment: str | None = None


class AnalysisSpec(BaseModel):
    model_config = ConfigDict(extra='forbid')
    dataset_ref: str
    filter: str
    sampling: str
    entity: list[str]
    grouping: dict[str, str]
    transformations: list[str]
    estimator: str
    uncertainty: str
    required_components: list[Literal['data_scope', 'sampling', 'grouping', 'transformation', 'estimator', 'numeric_claim']] = Field(min_length=1)
    code_ref: str
    claim_level: Literal['descriptive', 'association', 'causal'] = 'association'
    sampling_mode: Literal['census', 'sampled'] = 'sampled'
    identification_strategy: str | None = None
    identification_evidence_refs: list[str] = Field(default_factory=list)


def json_pointer(value, path):
    if not isinstance(path, str) or not path.startswith('/'):
        raise ValueError('absolute JSON pointer required')
    for raw in path[1:].split('/'):
        if re.search(r'~(?![01])', raw):
            raise ValueError('invalid JSON pointer escape')
        part = raw.replace('~1', '/').replace('~0', '~')
        if isinstance(value, list):
            if not re.fullmatch(r'0|[1-9][0-9]*', part):
                raise ValueError('JSON array pointer requires a nonnegative canonical index')
            value = value[int(part)]
        else:
            value = value[part]
    return value


def computation_output(execution):
    """Expose exact rendered output without inferring or silently parsing numbers."""
    if execution.get('ok') is False or execution.get('exit_code',0)!=0:
        raise ValueError('failed execution cannot cover a claim')
    text=execution.get('stdout','')
    if not isinstance(text,str):raise ValueError('computation stdout must be text')
    lines=text.splitlines()
    if execution.get('stdout_truncated') and not text.endswith(('\n','\r')):lines=lines[:-1]
    result={'stdout_lines':lines}
    try:
        if not execution.get('stdout_truncated'):result['parsed_stdout']=json.loads(text)
    except (ValueError,TypeError):pass
    return result


def coverage_report(checks, action, *, required=('claim_evidence',), source_file=None, record_target=None, record_packet_digest=None):
    """Read real receipts. Metadata such as row_count never proves an estimator."""
    results = []; covered = set(); assigned = {}
    for check in checks:
        item = dict(check)
        try:
            operation = action(check['action_ref'])
            tool = operation.get('tool')
            result = operation.get('result', {})
            if result.get('ok') is False or result.get('execution', {}).get('ok') is False:
                raise ValueError('failed computation cannot cover a claim')
            path = check['output_pointer']
            if check.get('basis')=='record_checked':
                if (check['component']!='record_fidelity' or tool!='inspect_report_disclosure' or not record_target
                        or result.get('target_ref')!=record_target or result.get('packet_digest')!=record_packet_digest
                        or not path.startswith('/checks/') or check['relation']!='eq' or check['expected'] is not True):
                    raise ValueError('disclosure audit only covers record_fidelity of this exact no-findings report packet')
                observed=json_pointer(result,path);passed=observed is True
                if passed:covered.add('record_fidelity')
                item.update(passed=passed,observed=observed,evidence_kind='disclosure_only_not_scientific_verification')
                results.append(item);continue
            if check['component']=='record_fidelity':raise ValueError('record_fidelity requires the explicit disclosure audit basis')
            if check.get('basis','recomputed') == 'source_inspected':
                if check['component'] in ('claim_evidence','numeric_claim'):
                    raise ValueError('source inspection cannot replace independent numeric reproduction')
                if tool not in ('read_artifact','read_memory') or not source_file:
                    raise ValueError('method inspection requires a version-validated source read receipt')
                ref=operation.get('arguments',{}).get('ref','')
                if not ref.startswith('file:') or source_file(ref).suffix.lower() not in ('.py','.sql'):
                    raise ValueError('method inspection must cite actual received Python/SQL source, not metadata')
                fragment=check['expected']; justification=check.get('justification') or ''
                if path!='/text' or check['relation']!='contains' or not isinstance(fragment,str) or len(fragment)<8 or len(justification.strip())<20:
                    raise ValueError('source check needs /text contains an exact code fragment and an explicit component-specific justification')
                text=json_pointer(result,path)
                if not isinstance(text,str): raise ValueError('actual source text required')
                passed=fragment in text
                if passed: covered.add(check['component'])
                item.update(passed=passed,observed_fragment=fragment if passed else None,
                            source_text_hash=hashlib.sha256(text.encode()).hexdigest(),
                            evidence_kind='attributed_source_inspection_not_independent_computation')
                results.append(item); continue
            if tool not in ('query_data', 'read_data_result', 'run_python', 'inspect_evidence'):
                raise ValueError('metadata cannot replace computation; method source inspection requires its explicit basis')
            if tool == 'run_python':
                result = computation_output(result['execution'])
            allowed = ('/preview/', '/rows/', '/parsed_stdout/', '/statistics/', '/stdout_lines/')
            if not path.startswith(allowed):
                raise ValueError('numeric values must point to actual computed output, not execution metadata')
            observed = json_pointer(result, path)
            if path.startswith('/stdout_lines/') and (check['relation']!='eq' or not isinstance(check['expected'],str)):
                raise ValueError('plain computed text requires exact full-line string equality; no implicit numeric extraction')
            signature = (check['action_ref'], path, check['relation'], json.dumps(check['expected'], sort_keys=True))
            prior = assigned.setdefault(signature, [])
            components={c['component'] for c in prior}
            if components and components != {check['component']} and not (components | {check['component']}) <= {'claim_evidence','numeric_claim'}:
                arguments=operation.get('arguments',{})
                executed=arguments.get('code',arguments.get('sql',''))
                def explained(c):
                    fragment=c.get('method_fragment') or ''; rationale=c.get('justification') or ''
                    return len(fragment)>=8 and fragment in executed and len(rationale.strip())>=20
                if not explained(check) or any(c['component'] not in ('claim_evidence','numeric_claim') and not explained(c) for c in prior):
                    raise ValueError('shared computation needs component-specific reasoning tied to an exact executed code/SQL fragment; relabeling one number is not coverage')
                item['method_linkage']='critic_explained_exact_executed_fragment'
            prior.append(check)
            if check['relation']=='contains': raise ValueError('contains is reserved for explicit method source inspection')
            relation = {'eq': operator.eq, 'lt': operator.lt, 'le': operator.le, 'gt': operator.gt, 'ge': operator.ge}[check['relation']]
            passed = bool(relation(observed, check['expected']))
            if passed:
                covered.add(check['component'])
            item.update(passed=passed, observed=observed)
            if path.startswith('/stdout_lines/'):item['evidence_kind']='exact_computation_text_not_numeric_parsing_or_new_observation'
        except (ValueError, KeyError, TypeError, IndexError) as error:
            item.update(passed=False, error=str(error))
        results.append(item)
    missing = sorted(set(required)-covered)
    return {'checks': results, 'required_components': list(required), 'covered_components': sorted(covered),
            'missing_components': missing, 'clearance_eligible': not missing and all(c['passed'] for c in results),
            'scientific_certification': False,
            'limits': 'Checks numeric reproduction and attributable method evidence/declared scope. Source inspection and explained reuse are critic judgments, not separate independent computations. It cannot establish correctness of arbitrary scientific code or causal identification.'}


def fixed_effects_design(frame, entity_columns, regressor_powers):
    """Expand RAW regressors first, then demean each column over full entities.

    Call on the complete declared sample, never independently per arbitrary
    chunk. Returns y-independent design columns in original regressor units.
    """
    import pandas as pd
    columns = {}
    for name, powers in regressor_powers.items():
        for power in powers:
            columns[name+'^'+str(power)] = frame[name].astype(float)**power
    raw = pd.DataFrame(columns, index=frame.index)
    keys = [frame[name] for name in entity_columns]
    return raw-raw.groupby(keys, sort=False, dropna=False).transform('mean')


def sampling_coverage(frame, sample, entity_columns, date_column):
    total_dates = frame[date_column].nunique()
    selected_dates = sample[date_column].nunique()
    return {'population_rows': len(frame), 'sample_rows': len(sample),
            'population_dates': int(total_dates), 'sample_dates': int(selected_dates),
            'population_entities': len(frame[entity_columns].drop_duplicates()),
            'sample_entities': len(sample[entity_columns].drop_duplicates()),
            'dates_omitted': bool(selected_dates < total_dates),
            'randomness_certified': False}
