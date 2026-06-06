import json
import sys

from on1y.sync.full_sync import full_sync_status, full_sync_timing_history

print("=== status ===")
print(json.dumps(full_sync_status(), indent=2, ensure_ascii=False, default=str))
print("=== history (last 3) ===")
print(json.dumps(full_sync_timing_history(limit=3), indent=2, ensure_ascii=False, default=str))
