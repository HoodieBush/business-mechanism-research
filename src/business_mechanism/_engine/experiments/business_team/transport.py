"""Transport recovery policy; it never interprets or executes research actions."""
import json
import random
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime


def retryable(record):
    # A provider's explicit permanent routing error must not be retried as a
    # transient HTTP 503. Treat its URL as data for a separately reviewed config
    # change; never follow it automatically or forward credentials here.
    response=record.get('response')
    error=response.get('error',{}) if isinstance(response,dict) else {}
    if not error and record.get('response_body'):
        try:error=json.loads(record['response_body']).get('error',{})
        except (ValueError,TypeError,AttributeError):error={}
    if isinstance(error,dict) and error.get('code')=='entry_changed':return False
    if record.get("error_type") == "transport":
        return True
    if record.get("error_type") == "response_envelope":
        return True
    if record.get("http_status") in (408, 425, 429, 500, 502, 503, 504):
        return True
    error = record.get("response", {}).get("error", {})
    return isinstance(error,dict) and error.get("code") in (429,500,502,503,504,"rate_limit_exceeded","server_error")


def retry_delay(record, failures, policy, jitter=None):
    base = min(policy["maximum_wait_seconds"], policy["initial_wait_seconds"] * policy["backoff_multiplier"]**min(failures-1,20))
    wait = base + (random.uniform(0,base*.2) if jitter is None else jitter)
    header = record.get("retry_after")
    if header:
        try:
            requested = float(header)
        except ValueError:
            try: requested = (parsedate_to_datetime(header)-datetime.now(timezone.utc)).total_seconds()
            except (ValueError,TypeError): requested = 0
        wait = max(wait,requested)
    return max(0,wait)


def interruptible_wait(seconds):
    # Runner is a background process; one-second sleeps permit Ctrl-C safely.
    end = time.monotonic()+seconds
    while time.monotonic()<end:
        time.sleep(min(1,end-time.monotonic()))
