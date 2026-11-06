"""Lossless container decoding for native tools; never infer scientific fields."""
from copy import deepcopy
import fcntl
import json
import re
from experiments.insight_research.common import digest, encoded, write_json


def strict_json(text):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result: raise ValueError('duplicate JSON field: '+key)
            result[key] = value
        return result
    return json.loads(text, object_pairs_hook=unique)


def inline_schema(schema):
    definitions = schema.get('$defs', {})
    def walk(value, seen=()):
        if isinstance(value, list): return [walk(v, seen) for v in value]
        if not isinstance(value, dict): return value
        ref = value.get('$ref', '')
        if ref.startswith('#/$defs/') and ref not in seen:
            key = ref[len('#/$defs/'):].replace('~1', '/').replace('~0', '~')
            if key in definitions:
                resolved = walk(definitions[key], (*seen, ref))
                return {**resolved, **{k: walk(v, seen) for k, v in value.items() if k != '$ref'}}
        return {k: walk(v, seen) for k, v in value.items() if k != '$defs'}
    result = walk(schema)
    def has_ref(value):
        return isinstance(value, dict) and ('$ref' in value or any(has_ref(v) for v in value.values())) or isinstance(value, list) and any(has_ref(v) for v in value)
    if has_ref(result): result['$defs'] = deepcopy(definitions)
    return result


def normalize_tool_containers(raw, tools):
    normalized = deepcopy(raw); changes = []; errors = []
    try: calls = normalized['choices'][0]['message'].get('tool_calls') or []
    except (KeyError, IndexError, TypeError, AttributeError): return normalized, changes, errors
    if not isinstance(calls, list): return normalized, changes, errors
    for index, call in enumerate(calls):
        try:
            function = call['function']; name = function['name']
            if name not in tools: continue
            schema = inline_schema(tools[name][0].model_json_schema())
            original_arguments=function['arguments']
            try:args = strict_json(original_arguments)
            except ValueError:
                fence=re.fullmatch(r'```(?:json)?[ \t]*\r?\n([\s\S]*?)\r?\n```',original_arguments.strip(),re.I)
                if not fence:raise
                args=strict_json(fence.group(1))
                if not isinstance(args,dict):raise ValueError('function arguments must be a JSON object')
                changes.append({'call':index,'tool':name,'path':'','kind':'lossless_json_fence_unwrap',
                    'original_hash':digest(original_arguments),'decoded_hash':digest(args)})
            if not isinstance(args, dict): continue  # Native parser rejects the envelope.
            def convert(value, spec, path):
                variants = spec.get('anyOf', [spec])
                types = {v.get('type') for v in variants}
                selected = spec
                if name=='record_review' and path=='/coverage_checks' and isinstance(value,dict) and 'component' in value and types=={'array'}:
                    changes.append({'call':index,'tool':name,'path':path,'kind':'lossless_singleton_coverage_array',
                        'original_hash':digest(value),'decoded_hash':digest([value])})
                    value=[value]
                if isinstance(value, str) and types.intersection(('object', 'array')):
                    try: decoded = strict_json(value)
                    except ValueError: return value
                    expected = 'object' if isinstance(decoded, dict) else 'array' if isinstance(decoded, list) else None
                    if expected not in types: return value
                    changes.append({'call': index, 'tool': name, 'path': path,
                                    'kind': 'lossless_json_container_decode',
                                    'original_hash': digest(value), 'decoded_hash': digest(decoded)})
                    value = decoded
                    selected = next(v for v in variants if v.get('type') == expected)
                elif isinstance(value, dict):
                    selected = next((v for v in variants if v.get('type') == 'object'), spec)
                elif isinstance(value, list):
                    selected = next((v for v in variants if v.get('type') == 'array'), spec)
                if isinstance(value, dict):
                    fields = selected.get('properties', {})
                    return {k: convert(v, fields[k], path+'/'+k.replace('~', '~0').replace('/', '~1')) if k in fields else v for k, v in value.items()}
                if isinstance(value, list):
                    return [convert(v, selected.get('items', {}), path+'/'+str(i)) for i, v in enumerate(value)]
                return value
            corrected = convert(args, schema, '')
            if corrected != args or any(c['call']==index and c['kind']=='lossless_json_fence_unwrap' for c in changes):
                function['arguments'] = encoded(corrected)
        except (KeyError, TypeError, ValueError, AttributeError) as error:
            errors.append({'call': index, 'error_code': 'invalid_tool_json', 'message': str(error)})
    return normalized, changes, errors


def recover_protocol_rejection(runtime, event_id):
    """Replay a rejected, already-paid spec registration under the new codec.

    Same response/attempt counters; durable operation key and raw hash checks.
    This is a transport-shape repair, never a new LLM or inferred analysis.
    """
    if not re.fullmatch('[A-Za-z0-9_-]{1,100}', event_id):
        raise ValueError('Safe explicit recovery event_id required')
    ws = runtime.ws; journal = runtime.journal
    path = ws.private/'protocol_recoveries'/(event_id+'.json')
    if path.exists():
        previous = json.loads(path.read_text())
        if previous.get('status') == 'completed':
            original = json.loads((ws.private/'turns'/f"{previous['source_response']}.json").read_text())
            if digest(original) != previous['original_response_hash']:
                raise ValueError('recovered_original_response_changed')
            return previous
    lock = (ws.private/'runtime.lock').open('a')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        runtime.cp = json.loads(runtime.path.read_text())
        journal.state = json.loads(journal.path.read_text())
        cp = runtime.cp
        if cp.get('pending') or journal.state.get('inflight') or journal.state.get('delivery'):
            raise ValueError('protocol_recovery_requires_drained_transport')
        number = cp['responses']; attempt = cp.get('delivered_attempt')
        if attempt != journal.state['attempts']:
            raise ValueError('protocol_recovery_latest_paid_response_required')
        raw = json.loads((ws.private/'turns'/f'{number}.json').read_text())
        http = json.loads((ws.private/'http'/f'{attempt}.json').read_text())
        if raw != http.get('response'):
            raise ValueError('protocol_recovery_original_response_mismatch')
        with journal.study.connect() as db:
            paid = db.execute('SELECT status FROM attempts WHERE key=?', (digest([journal.role, attempt]),)).fetchone()
        if not paid or paid[0] not in ('settled', 'unknown'):
            raise ValueError('protocol_recovery_paid_ledger_required')
        corrected, changes, errors = normalize_tool_containers(raw, ws.tools)
        calls = corrected['choices'][0]['message'].get('tool_calls') or []
        if errors or len(calls) != 1 or calls[0]['function']['name'] != 'register_analysis_spec' or not changes:
            raise ValueError('protocol_recovery_only_lossless_spec_container_supported')
        if raw['choices'][0].get('finish_reason') != 'tool_calls':
            raise ValueError('protocol_recovery_complete_response_required')
        # Verify the original rejection really executed zero tools. An active
        # migration notice may follow it; never manufacture a paid instruction.
        rejected = False
        for message in reversed(cp['messages']):
            if message.get('role') == 'assistant': break
            if message.get('role') != 'user': continue
            try: item = json.loads(message['content'])
            except (ValueError, TypeError): continue
            if isinstance(item, dict) and item.get('protocol_error') and item.get('executed_tools') == 0:
                rejected = True; break
        if path.exists():
            previous = json.loads(path.read_text())
            if previous['original_response_hash'] != digest(raw): raise ValueError('recovery_event_conflict')
            if previous.get('status') == 'completed': return previous
        elif not rejected:
            raise ValueError('protocol_recovery_requires_explicit_zero_tool_rejection')
        function = calls[0]['function']; args = strict_json(function['arguments'])
        args = ws.tools[function['name']][0].model_validate(args).model_dump()
        before = journal.study.snapshot()
        receipt = {'event_id': event_id, 'status': 'prepared', 'source_attempt': attempt, 'source_response': number,
                   'original_response_hash': digest(raw), 'normalized_arguments_hash': digest(args), 'changes': changes,
                   'external_provider_calls': 0, 'scientific_fields_inferred_or_deleted': False}
        if not path.exists(): write_json(path, receipt)
        ws.response_ref = 'process:'+str(number)
        result = ws.call(function['name'], args, 'protocol-recovery:'+event_id)
        if journal.study.snapshot() != before:
            raise ValueError('protocol_recovery_changed_paid_budget')
        if event_id not in cp.get('protocol_recovery_events', []):
            cp['messages'].append({'role': 'user', 'content': encoded({'protocol_recovery': receipt, 'actual_tool_result': result})})
            cp.setdefault('protocol_recovery_events', []).append(event_id); runtime.save()
        receipt.update(status='completed', result=result, execution_usage=before)
        write_json(path, receipt)
        return receipt
    finally:
        lock.close()
