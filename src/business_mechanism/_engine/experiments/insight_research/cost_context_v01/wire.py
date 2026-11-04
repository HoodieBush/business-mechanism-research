"""Losslessly inspectable wire layout; no generated summary or factual rewrite."""
from copy import deepcopy
import json

from ..common import Pending, digest, encoded

VIEW = 'current_research_context_v1'
REPEAT = 'identical_read_receipt_v1'
ANCHOR = {'role': 'user', 'content': encoded({
    'research_context_layout': 'stable-prefix-v1',
    'instruction': 'The versioned current_research_context_v1 user message supplies the complete latest live research view. It supersedes earlier state and eligibility views, including withdrawals, revisions, pending work and resource state. Earlier observations and conversations remain historical evidence, not automatically current facts. Original records and exact read tools remain available.'})}
def _parsed(message):
    try:
        return json.loads(message.get('content', ''))
    except (ValueError, TypeError):
        return None


def validate_pairs(messages):
    pending = {}
    names = {}
    for message in messages:
        if message['role'] == 'assistant':
            if pending:
                raise Pending('request layout cannot cross an unfinished tool batch')
            for call in message.get('tool_calls', []):
                if call['id'] in pending:
                    raise Pending('duplicate tool id within a batch')
                pending[call['id']] = call['function']['name']
                names[call['id']] = call['function']['name']
        elif message['role'] == 'tool':
            if message.get('tool_call_id') not in pending:
                raise Pending('tool receipt has no matching pending call')
            pending.pop(message['tool_call_id'])
        elif pending:
            raise Pending('non-tool message interrupts an unfinished tool batch')
    if pending:
        raise Pending('already-paid tool work must drain before request layout')
    return names


def current_context(payload):
    found = []
    for i, message in enumerate(payload['messages']):
        body = _parsed(message)
        if message['role'] == 'user' and isinstance(body, dict) and set(body) == {VIEW}:
            view = body[VIEW]
            if digest(view['context']) != view['version']:
                raise Pending('current-context version changed')
            found.append((i, view['context']))
    if len(found) != 1:
        raise Pending('exactly one complete latest context is required')
    return found[0]


def organize(payload):
    result = deepcopy(payload)
    messages = result['messages']
    if len(messages) < 2 or messages[0]['role'] != 'system' or messages[1]['role'] != 'user':
        raise Pending('explicit system and initial live context required')
    if messages[1] == ANCHOR:
        current_context(result)
        validate_pairs(messages)
        return result
    context = _parsed(messages[1])
    if not isinstance(context, dict):
        raise Pending('structured complete live context required')
    validate_pairs(messages)
    tail = deepcopy(messages[2:])
    # Corpus replay found no safe exact duplicate readonly receipt within a
    # request. Preserve all tool bodies; do not keep an unhelpful compressor.
    result['messages'] = [deepcopy(messages[0]), deepcopy(ANCHOR)] + tail + [
        {'role': 'user', 'content': encoded({VIEW: {'context': context, 'version': digest(context)}})}]
    validate_pairs(result['messages'])
    return result


def restore_logical(payload):
    """Engineering inverse; original messages and tool bodies stay complete."""
    result = deepcopy(payload)
    index, context = current_context(result)
    if result['messages'][1] != ANCHOR:
        raise Pending('unknown context-layout anchor')
    tail = [(i, deepcopy(m)) for i, m in enumerate(result['messages']) if i >= 2 and i != index]
    for original_index, message in tail:
        if message['role'] != 'tool':
            continue
        body = _parsed(message)
        if isinstance(body, dict) and set(body) == {REPEAT}:
            raise Pending('old prototype compact receipt is not part of this candidate')
    result['messages'] = [result['messages'][0], {'role': 'user', 'content': encoded(context)}] + [m for _, m in tail]
    validate_pairs(result['messages'])
    return result
