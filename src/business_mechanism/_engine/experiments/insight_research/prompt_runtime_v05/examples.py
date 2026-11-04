"""Schema-valid teaching examples. EXAMPLE references are never live evidence."""
from copy import deepcopy


RESEARCHER = [
    ('context', 'read_context', {}),
    ('read', 'read_artifact', {'ref': 'file:EXAMPLE_PUBLIC', 'offset': 0, 'limit': 12000}),
    ('query', 'query_data', {'sql': "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name", 'purpose': '先了解可读业务表，不猜测字段。'}),
    ('search', 'search_memory', {'query': '当前业务疑点', 'kind': 'knowledge', 'include_history': True, 'offset': 0, 'limit': 8}),
    ('read_memory', 'read_memory', {'ref': 'original:K_EXAMPLE', 'offset': 0, 'limit': 12000}),
    ('compute', 'run_python', {'code': "import csv, json\nfrom pathlib import Path\nrows=list(csv.DictReader(Path('EXAMPLE_COMPUTE_PATH').open()))\nprint(json.dumps({'row_count':len(rows),'columns':list(rows[0]) if rows else []}))", 'purpose': '读取实际回执提供的CSV路径，检查数据范围；这只是探索计算。'}),
    ('hypothesis', 'save_hypothesis', {'kind': 'data_quality', 'statement': '待检验的业务命题；按当前数据和疑点填写。', 'scope': '明确对象、时间、口径和适用条件。', 'prediction': '原始资料按照所声明口径可被分析代码复算。', 'falsification': '实际数据与所声明口径不符时应修订；未执行或证据不足则未决。', 'alternatives': ['观测差异来自业务过程。', '观测差异来自口径或记录过程。'], 'evidence_refs': ['file:EXAMPLE_DATA'], 'tags': ['example']}),
    ('plan', 'register_test', {'hypothesis_ref': 'H_EXAMPLE', 'prediction': '原始资料按照所声明口径可被分析代码复算。', 'contrast': '比较原声明与实际数据和计算；真实研究中填写可区分竞争解释的比较。', 'observation_unit': '资料中定义的观测单元', 'allocation_unit': '已有观测，无新增分配', 'analysis': '固定代码读取真实CSV并输出行数；真实研究中换成与原预测一致的分析。', 'purpose': '演示已见资料的可复算检验。', 'data_refs': ['file:EXAMPLE_DATA'], 'mode': 'observational', 'code': "import csv,json\nfrom pathlib import Path\nrows=list(csv.DictReader(Path('EXAMPLE_COMPUTE_PATH').open()))\nprint(json.dumps({'row_count':len(rows)}))"}),
    ('test', 'run_test', {'plan_ref': 'P_EXAMPLE'}),
    ('assessment', 'record_assessment', {'hypothesis_ref': 'H_EXAMPLE', 'result_refs': ['R_EXAMPLE'], 'status': 'unresolved', 'prediction_coverage': '说明实际检验覆盖了原预测哪些部分。', 'rationale': '演示未决提交；实际状态根据原预测和真实结果填写。', 'deviations': [], 'counterevidence_refs': [], 'limitations': ['代码运行成功不自动说明业务机制成立。']}),
    ('state', 'update_research_state', {'question': '当前课题的业务问题', 'why': '本次理解变化与业务问题的关系', 'understanding': '已知什么、依赖哪些证据、哪些仍是解释或未知。', 'active_hypothesis_refs': ['H_EXAMPLE'], 'alternative_refs': [], 'evidence_refs': ['R_EXAMPLE'], 'counterevidence_refs': [], 'incorporated_result_refs': ['R_EXAMPLE'], 'recent_change': '已把这个正式结果纳入当前认识。', 'open_questions': ['仍需什么证据区分竞争解释？'], 'next_action': '请求对当前判断的独立核验，或根据具体疑点继续分析。', 'next_reason': '说明下一步预期增加的信息。', 'focus_hypothesis_refs': ['H_EXAMPLE']}),
    ('knowledge', 'update_research_state', {'question': '当前课题的业务问题', 'why': '保存可供后续研究使用的认识', 'understanding': '当前理解及边界。', 'active_hypothesis_refs': ['H_EXAMPLE'], 'alternative_refs': [], 'evidence_refs': ['R_EXAMPLE'], 'counterevidence_refs': [], 'incorporated_result_refs': ['R_EXAMPLE'], 'recent_change': '新增一条有来源、暂定的方法认识。', 'open_questions': [], 'next_action': '根据当前疑点选择下一步。', 'next_reason': '必要时可继续补证或核验。', 'knowledge_updates': [{'kind': 'method', 'statement': '可能有助于未来提出假说或检验的方法认识。', 'scope': '适用条件与未验证范围。', 'status': 'tentative', 'evidence_refs': ['R_EXAMPLE'], 'hypothesis_refs': ['H_EXAMPLE'], 'research_use': '说明之后什么时候、怎样使用这条认识。'}]}),
    ('request', 'request_review', {'job_ref': 'J_EXAMPLE', 'reason': '核验原预测、证据解释与相关旧认识；请优先处理可能改变当前判断的疑点。'}),
    ('response', 'respond_to_review', {'review_ref': 'Q_EXAMPLE', 'issue_id': 'EXAMPLE_ISSUE', 'disposition': 'revise', 'rationale': '指出确认的问题与实际修改内容；不是只承诺以后修改。', 'evidence_refs': ['file:EXAMPLE_DATA'], 'replacement_refs': ['K_EXAMPLE_REVISED'], 'object_reviews': [{'target_ref': 'K_EXAMPLE', 'decision': 'quarantine', 'reason': '保留有问题的旧记忆，但不继续当作当前强事实。', 'evidence_refs': ['file:EXAMPLE_DATA']}]}),
    ('finish', 'finish_research', {'assessment_refs': ['A_EXAMPLE'], 'other_hypotheses': {}, 'limitations': ['列明适用范围、证据限制和仍有争议的部分。'], 'open_questions': ['后续仍值得研究的问题。'], 'measurement_requests': []}),
]

RESEARCHER.append(('collect', 'collect_evidence', {'operation': 'observe', 'windows': 1,
    'purpose': '演示当前测量工具参数；先读实际测量目录，再选择所需的新观测。'}))
withdraw = deepcopy(RESEARCHER[10][2])
withdraw['memory_reviews'] = [{'target_ref': 'K_EXAMPLE', 'decision': 'withdraw',
    'reason': '依据原件确认旧解释不成立；保留原条目并检查下游。', 'evidence_refs': ['file:EXAMPLE_DATA']}]
RESEARCHER.append(('withdraw_memory', 'update_research_state', withdraw))
historical = deepcopy(RESEARCHER[10][2])
historical['historical_field_reviews'] = [{'source_ref': 'archive:EXAMPLE_STAGE:K_EXAMPLE',
    'source_version': 'a' * 64, 'field': 'research_use', 'decision': 'replace',
    'replacement_text': '以合法原件为依据、具有明确适用范围的修订用途。',
    'reason': '说明原字段问题和替换依据。', 'evidence_refs': ['file:EXAMPLE_DATA']}]
RESEARCHER.append(('historical_field', 'update_research_state', historical))
revision = deepcopy(RESEARCHER[9][2])
revision['supersedes_assessment_ref'] = 'A_EXAMPLE'
RESEARCHER.append(('revise_assessment', 'record_assessment', revision))


CRITIC = [
    ('directory', 'read_memory', {'ref': 'directory:all', 'offset': 0, 'limit': 12000}),
    ('target', 'read_memory', {'ref': 'A_EXAMPLE', 'offset': 0, 'limit': 12000}),
    ('search', 'search_memory', {'query': '与当前主张相关的旧认识或反证', 'kind': 'knowledge', 'offset': 0, 'limit': 8}),
    ('source', 'read_artifact', {'ref': 'file:EXAMPLE_DATA', 'offset': 0, 'limit': 12000}),
    ('query', 'query_data', {'sql': "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name", 'purpose': '独立确认实际可读业务表。'}),
    ('compute', 'run_python', RESEARCHER[5][2]),
    ('review_issue', 'record_review', {'phase': 'complete', 'checked_scope': ['当前目标及相关旧知识的范围与证据'], 'unchecked_scope': ['未执行新的业务干预；未核验的范围如实列出。'], 'source_refs': ['A_EXAMPLE', 'file:EXAMPLE_DATA'], 'checks_performed': [{'action_ref': 'check:EXAMPLE_READ', 'finding': '实际读取原件后发现旧记忆范围超出已有证据。', 'artifact_refs': ['file:EXAMPLE_DATA']}], 'issues': [{'issue_id': 'EXAMPLE_ISSUE', 'affected_refs': ['K_EXAMPLE'], 'basis': 'observed', 'blocking': True, 'description': '示例：当前目标可保留，但相关旧记忆的外推缺少依据。', 'type': 'missing_evidence', 'evidence_locations': ['旧记忆scope与原数据覆盖范围'], 'action_refs': ['check:EXAMPLE_READ'], 'check_artifact_refs': [], 'claim_impact': '只影响这条旧知识的泛化使用，不自动否定当前判断。', 'minimal_next_step': '核对实际范围并修订旧记忆；如要外推，取得相应新证据。'}], 'open_issue_ids': ['EXAMPLE_ISSUE'], 'next_action': '交回研究者，由其决定修订或提供反驳证据。', 'target_conclusion': 'consistent_in_checked_scope'}),
    ('review_clean', 'record_review', {'phase': 'complete', 'checked_scope': ['已实际读取并核验的目标范围'], 'unchecked_scope': ['范围之外不作结论'], 'source_refs': ['A_EXAMPLE', 'file:EXAMPLE_DATA'], 'checks_performed': [{'action_ref': 'check:EXAMPLE_READ', 'finding': '已查范围内没有发现实质不一致。', 'artifact_refs': ['file:EXAMPLE_DATA']}], 'issues': [], 'open_issue_ids': [], 'next_action': '将实际核验范围交回研究者。', 'target_conclusion': 'consistent_in_checked_scope'}),
]


revision_knowledge = deepcopy(RESEARCHER[11][2])
revision_knowledge['knowledge_updates'][0].update(supersedes_ref='K_EXAMPLE', revision_reason='旧条目的范围超出实际证据；以有来源、窄范围的新条目替代。')
RESEARCHER.append(('revise_knowledge', 'update_research_state', revision_knowledge))
checkpoint = deepcopy(CRITIC[7][2])
checkpoint.update(phase='checkpoint',target_conclusion='insufficient_evidence',next_action='从已保存原件继续核验尚未检查的关键预测。')
CRITIC.append(('checkpoint', 'record_review', checkpoint))
recheck = deepcopy(CRITIC[7][2])
recheck.update(prior_issue_updates={'EXAMPLE_ISSUE':'resolved'},next_action='实际替代记录及其证据已核对，将核验范围交回研究者。')
CRITIC.append(('recheck', 'record_review', recheck))

RESEARCHER.append(('finish_deferred', 'finish_research', {
    'assessment_refs':[], 'other_hypotheses':{'H_EXAMPLE':'检验已有结果，但判断尚未独立核验，本阶段保留未决。'},
    'limitations':['本报告不将尚未核验判断作为已支持认识。'],
    'open_questions':['后续核验原预测、执行与解释，必要时继续取证。'], 'measurement_requests':[],
    'deferred_review_jobs':{'J_EXAMPLE':'本有限阶段暂缓未付费审查；原计划、数据、结果与判断全部保留。'}}))

def examples(role):
    return deepcopy(RESEARCHER if role == 'researcher' else CRITIC)


def substitute(value, mapping):
    if isinstance(value, dict):
        return {substitute(k, mapping): substitute(v, mapping) for k, v in value.items()}
    if isinstance(value, list):
        return [substitute(v, mapping) for v in value]
    if isinstance(value, str):
        for key in sorted(mapping, key=len, reverse=True):
            value = value.replace(key, mapping[key])
    return value
