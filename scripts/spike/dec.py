import json
from common import sandbox
sb=sandbox()
raw=sb._dp_get(f"{sb._sbx_path}/egress-decisions"); print(json.dumps(raw, indent=1)[:5000])
