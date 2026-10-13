"""Shared client factory for the ACA Sandboxes spike. All values come from env (no secrets)."""
import os
from azure.identity import DefaultAzureCredential
from azure.containerapps.sandbox import SandboxGroupClient, endpoint_for_region

SUB = os.environ["SPIKE_SUBSCRIPTION_ID"]
RG = os.environ.get("SPIKE_RG", "rg-sandbox-spike")
GROUP = os.environ.get("SPIKE_GROUP", "sbg-spike")
REGION = os.environ.get("SPIKE_REGION", "uksouth")
SBID_FILE = os.environ.get("SPIKE_SBID_FILE", "sbid")


def gc():
    return SandboxGroupClient(endpoint_for_region(REGION), DefaultAzureCredential(),
                              subscription_id=SUB, resource_group=RG, sandbox_group=GROUP)


def sandbox():
    return gc().get_sandbox_client(open(SBID_FILE).read().strip())
