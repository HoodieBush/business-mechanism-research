"""Compose the complete prompt actually loaded by each role."""
import json
from pathlib import Path
from .examples import examples
from ..common import sha

HERE = Path(__file__).parent


def source_identity():
    paths = [p for p in HERE.rglob('*') if p.is_file() and p.suffix in ('.py', '.txt', '.md')
             and '__pycache__' not in p.parts]
    return {str(p.relative_to(HERE)): sha(p) for p in sorted(paths)}


def compose(role):
    core = (HERE/'prompts'/(role+'_core.txt')).read_text().rstrip()
    operations = (HERE/'prompts'/(role+'_operations.md')).read_text().rstrip()
    preface = ('\n\n## 工具调用与提交示例\n'
               '以下都是教学模板，不是当前任务的数据、科学结论或已执行动作。'
               '所有含EXAMPLE的引用、路径以及全a的64位演示版本必须换成当前真实回执；说明文字也按本次研究填写。'
               '不要把模板内容当成研究发现，不要提交演示引用。'
               '工具参数模式随请求同时提供，下面展示常见完整提交，选用所需动作即可。\n')
    parts = [core, operations, preface]
    for label, name, arguments in examples(role):
        parts.append('\n<example id="'+label+'">\n函数：'+name+'\narguments：\n```json\n'+
                     json.dumps(arguments, ensure_ascii=False, indent=2)+'\n```\n</example>')
    if role == 'researcher':
        parts.append('\n历史字段修订注意：source_version取archive原件回执的original_version，不是包装文件sha256；'
                     '当前已有修订时填写expected_prior_revision_ref，未变字段不重复提交。'
                     '修订判断用supersedes_assessment_ref，修订假说/计划保留父版本。'
                     'knowledge_updates中的supersedes_ref替代旧K；有问题的旧记录也可显式撤回/隔离。')
    return '\n\n'.join(parts)+'\n'
