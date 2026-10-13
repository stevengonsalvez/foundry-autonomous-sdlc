import sys
from common import sandbox
from azure.containerapps.sandbox import EgressHostRule
sb=sandbox()
p=sb.get_egress_policy()
op,host=sys.argv[1],sys.argv[2]
if op=="add": p.host_rules.append(EgressHostRule(host,"Allow"))
else: p.host_rules=[r for r in p.host_rules if r.pattern!=host]
sb.set_egress_policy(p); print([r.pattern for r in sb.get_egress_policy().host_rules])
