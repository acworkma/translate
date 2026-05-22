"""AzureOpenAI client pointed at the Foundry AIServices endpoint.

Same client works for OpenAI deployments (gpt-4-1, gpt-4o-mini) and xAI
deployments (grok-3) because both are OpenAI-compatible under AIServices.
"""
from __future__ import annotations

import os
from functools import lru_cache

from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from openai import AzureOpenAI

API_VERSION = "2024-10-21"
SCOPE = "https://cognitiveservices.azure.com/.default"


@lru_cache(maxsize=1)
def get_openai_client() -> AzureOpenAI:
    endpoint = os.environ["FOUNDRY_ENDPOINT"].rstrip("/")
    credential = DefaultAzureCredential(
        managed_identity_client_id=os.environ.get("AZURE_CLIENT_ID"),
    )
    token_provider = get_bearer_token_provider(credential, SCOPE)
    return AzureOpenAI(
        azure_endpoint=endpoint,
        azure_ad_token_provider=token_provider,
        api_version=API_VERSION,
    )


@lru_cache(maxsize=1)
def get_credential() -> DefaultAzureCredential:
    return DefaultAzureCredential(
        managed_identity_client_id=os.environ.get("AZURE_CLIENT_ID"),
    )
