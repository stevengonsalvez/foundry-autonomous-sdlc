"""Step 1: create the sandbox group (resource group and role assignment are az commands, see README)."""
import time
from azure.identity import DefaultAzureCredential
from azure.containerapps.sandbox import SandboxGroupManagementClient
from common import SUB, RG, GROUP, REGION

c = SandboxGroupManagementClient(DefaultAzureCredential(), subscription_id=SUB, resource_group=RG)
t = time.time()
g = c.begin_create_group(GROUP, REGION, tags={"purpose": "sandbox-spike"}).result()
print(round(time.time() - t, 1), g)
