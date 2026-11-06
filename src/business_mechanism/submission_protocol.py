"""One authoritative review format for prompts, schema help and tool receipts."""
from copy import deepcopy
import json
import re

PROTOCOL = 'covered-review-v2'


def clean_example():
    return {'phase':'complete','target_conclusion':'consistent_in_checked_scope',
        'checked_scope':['已独立复算的具体主张；业务目标还需覆盖contract要求的全部方法组件。'],
        'unchecked_scope':['未检查的范围如实列出，不作外推。'],
        'source_refs':['A_EXAMPLE','file:EXAMPLE_DATA'],
        'checks_performed':[{'action_ref':'check:EXAMPLE_COMPUTE','finding':'教学示例：独立计算返回JSON minimum=0；替换为本任务真实检查。','artifact_refs':[]}],
        'coverage_checks':[{'component':'claim_evidence','basis':'recomputed','action_ref':'check:EXAMPLE_COMPUTE',
            'output_pointer':'/parsed_stdout/minimum','relation':'eq','expected':0}],
        'issues':[],'open_issue_ids':[],'prior_issue_updates':{},
        'next_action':'交回真实核验结果；只有本任务contract全部覆盖时才提交consistent。'}


def rewrite_examples(text):
    def replace(match):
        name=match.group(1);body=match.group(2)
        if not re.search(r'函数：\s*record_review\b',body):return match.group(0)
        if name=='review_clean':value=clean_example()
        else:
            raw=re.search(r'```json\s*(.*?)\s*```',body,re.S)
            value=json.loads(raw.group(1))
            if value.get('phase')=='complete' and value.get('target_conclusion')=='consistent_in_checked_scope':
                value['coverage_checks']=deepcopy(clean_example()['coverage_checks'])
                value['checks_performed']+=deepcopy(clean_example()['checks_performed'])
            else:value.setdefault('coverage_checks',[])
        return '<example id="'+name+'">\n函数：record_review\narguments：\n```json\n'+json.dumps(value,ensure_ascii=False,indent=2)+'\n```\n</example>'
    text=re.sub(r'<example id="([^"]+)">(.*?)</example>',replace,text,flags=re.S)
    text=text.replace('资源不足只能checkpoint，不能为结束而把未查内容说成已核验。',
        '片段结束可complete+insufficient_evidence并明确未查范围；不得因资源不足声称已核验。')
    text=text.replace('next_action、target_conclusion，完整结构见示例。',
        'next_action、target_conclusion、coverage_checks；consistent必须覆盖当前contract要求，完整结构见示例。')
    return text


def guide(contract, schema):
    methods=[]
    for component in contract.get('required_components',[]):
        if component in ('numeric_claim','claim_evidence','record_fidelity'):continue
        methods.append({'component':component,'basis':'source_inspected','action_ref':'check:EXAMPLE_SOURCE',
            'output_pointer':'/text','relation':'contains','expected':'从真实源码逐字复制至少8字符片段',
            'justification':'明确说明该实际代码片段如何实现本组件，不能复制此教学占位文字。'})
    return {'protocol':PROTOCOL,'required_fields':schema.get('required',[]),
        'required_coverage_components':contract.get('required_components',[]),
        'rules':['coverage_checks必须显式给出；consistent必须覆盖当前contract全部组件，例子中的minimum不是当前任务字段。',
            '数字来自真实query_data/read_data_result/run_python输出；源码检查不能代替数字。',
            'run_python优先只print(json.dumps({...}))，不混入日志；已完成的纯文本可用/stdout_lines/实际零基行号做eq精确整行断言。',
            'source_inspected使用/text、contains、逐字源码片段及至少20字符的具体justification。不要把解释拼进expected。',
            '只使用computation_actions列出的实际action_ref和output_pointer；不能把/parsed_stdout/minimum或/n示例直接当本任务路径。',
            '预检失败只修对应字段。草稿valid后按commit_call单独提交；不必再次重写完整意见。'],
        'complete_example':clean_example(),'method_check_examples':methods,
        'numeric_check_example':{**deepcopy(clean_example()['coverage_checks'][0]),'component':'numeric_claim'},
        'disclosure_check_example':{'component':'record_fidelity','basis':'record_checked','action_ref':'check:EXAMPLE_DISCLOSURE_AUDIT',
            'output_pointer':'/checks/all_hypotheses_disclosed','relation':'eq','expected':True},
        'example_status':'Teaching syntax only. Replace every EXAMPLE, expected value, scope and explanation using actual receipts; never infer scientific findings from a template.'}


def draft_receipt(item):
    errors=item.get('validation_errors',[])
    ready=not errors and item.get('is_head') and not item.get('commit_result')
    return {**item,'valid':not errors,'ready_to_commit':bool(ready),
        'commit_call':{'name':'commit_review','arguments':{'draft_ref':item['draft_ref'],'expected_hash':item['draft_hash']}} if ready else None,
        'next_action':'Call commit_call as the sole tool; scientific opinion remains exactly the authored draft.' if ready else 'Repair explicit validation_errors without deleting findings; reread this draft only if needed.'}
