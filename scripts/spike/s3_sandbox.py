"""Step 3 setup: store the GitHub token as a group secret (from env SPIKE_GH_TOKEN, never printed) and create a node-24 sandbox with Deny default egress plus Transform rules."""
import os, base64, time, json
from common import gc
from azure.containerapps.sandbox import *
g=gc(); SID=os.environ.get("SPIKE_SECRET_ID", "githubtoken")  # "gh" is rejected: 400 secretId invalid
tok=os.environ.pop("SPIKE_GH_TOKEN")
basic=base64.b64encode(f"x-access-token:{tok}".encode()).decode()
r=g.upsert_secret(SID, {"basic": basic, "token": tok})
del tok, basic
print("secret upserted; keys:", g.list_secret_keys(SID))
hdr=lambda key,fmt: EgressHeader(operation="Set", name="Authorization", value_ref=EgressHeaderValueRef(secret_ref=EgressSecretRef(secret_id=SID, secret_key=key, format=fmt)))
pol=EgressPolicy(default_action="Deny",
  host_rules=[EgressHostRule(h,"Allow") for h in ["github.com","api.github.com","registry.npmjs.org",os.environ["SPIKE_MODEL_HOST"]]],
  rules=[EgressRule(name="gh-git", match=EgressRuleMatch(host="github.com"), action=EgressRuleAction(type="Transform", headers=[hdr("basic","Basic {value}")])),
         EgressRule(name="gh-api", match=EgressRuleMatch(host="api.github.com"), action=EgressRuleAction(type="Transform", headers=[hdr("token","Bearer {value}")]))])
t=time.time()
sb=g.begin_create_sandbox(disk="node-24", cpu="1000m", memory="2048Mi", auto_suspend_seconds=300, labels={"purpose":"sandbox-spike"}, egress_policy=pol, polling_timeout=300).result()
print("created", sb.sandbox_id, "in", round(time.time()-t,1),"s")
open(os.environ.get("SPIKE_SBID_FILE","sbid"),"w").write(sb.sandbox_id)
print(json.dumps(sb.get_egress_policy()._to_dict(), indent=1))
