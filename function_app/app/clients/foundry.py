"""AzureOpenAI client + shared DefaultAzureCredential pointed at the Foundry endpoint.

The same OpenAI client works for OpenAI deployments (gpt-4-1, gpt-4o-mini)
and xAI deployments (grok-4-1-fast-reasoning) because both are OpenAI-compatible
under AIServices.
"""
from __future__ import annotations

import os
from functools import lru_cache

from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from openai import AzureOpenAI

API_VERSION = "2024-10-21"
SCOPE = "https://cognitiveservices.azure.com/.default"


@lru_cache(maxsize=1)
def get_credential() -> DefaultAzureCredential:
    return DefaultAzureCredential(
        managed_identity_client_id=os.environ.get("AZURE_CLIENT_ID"),
    )


@lru_cache(maxsize=1)
def get_openai_client() -> AzureOpenAI:
    endpoint = os.environ["FOUNDRY_ENDPOINT"].rstrip("/")
    token_provider = get_bearer_token_provider(get_credential(), SCOPE)
    return AzureOpenAI(
        azure_endpoint=endpoint,
        azure_ad_token_provider=token_provider,
        api_version=API_VERSION,
    )


def get_bearer_token() -> str:
    """One-shot bearer token for REST calls (Content Understanding, Document Translation)."""
    return get_credential().get_token(SCOPE).token
