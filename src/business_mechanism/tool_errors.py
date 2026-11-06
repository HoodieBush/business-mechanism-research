"""Input-reference failures are durable tool feedback, not controller crashes."""
import json
import re
from experiments.insight_research.common import digest, encoded, write_json


def reference_error(error):
    message = str(error)
    try:
        body = json.loads(message)
        message = body.get('error', message) if isinstance(body, dict) else message
    except ValueError:
        pass
    return bool(re.fullmatch(r'received (?:record|plan|hypothesis|assessment|result|file|review|knowledge|state|action|scientific record or action) reference required', message)
                or message.startswith(('referenced source version changed', 'Unknown owned draft_ref',
                                       'Active attributed prior review action required',
                                       'Prior action must be explicitly listed')))


def feedback(ws, name, args, operation, error):
    kind = {'run_test': 'plan', 'register_test': 'hypothesis', 'record_assessment': 'result'}.get(name)
    # The received reviewer projection has docs, not the owner's records table.
    # Never open or query the owner's private database to build error feedback.
    db = ws.view.db if hasattr(ws, 'view') else ws.db
    table = 'docs' if hasattr(ws, 'view') else 'records'
    rows = db.execute('SELECT ref FROM '+table+(' WHERE kind=?' if kind else '')+' ORDER BY rowid DESC LIMIT 5',
                      (kind,) if kind else ()).fetchall()
    item = {'ok': False, 'error_code': 'invalid_object_reference', 'error': str(error),
            'tool': name, 'submitted_arguments': args, 'scientific_status_changed': False,
            'retryable': False, 'received_reference_examples': [r[0] for r in rows],
            'next_action': 'Read the original successful tool receipt or search_memory for the exact received reference. Do not guess or fuzzy-match an object ID. Correct the argument in a new call; the original failure is retained.'}
    path = ws.science/'tool_errors'/(digest(operation)+'.json')
    write_json(path, {'tool': name, 'operation': operation, 'arguments': args, 'result': item})
    return item


def durable_call(ws, name, args, operation, invoke):
    """Crash replay returns the same rejection even after the registry changes."""
    signature = digest([name, args])
    row = ws.db.execute('SELECT signature,result FROM release_tool_receipts WHERE operation=?', (operation,)).fetchone()
    if row:
        if row[0] != signature: raise ValueError('tool_operation_identity_conflict')
        return json.loads(row[1])
    try:
        result = invoke()
    except ValueError as error:
        if not reference_error(error): raise
        ws.db.rollback()
        result = feedback(ws, name, args, operation, error)
    if result.get('ok') is False and reference_error(ValueError(result.get('error', ''))):
        result = {**result, **feedback(ws, name, args, operation, ValueError(result['error']))}
    with ws.db:
        ws.db.execute('INSERT INTO release_tool_receipts VALUES (?,?,?)', (operation, signature, encoded(result)))
    return result
