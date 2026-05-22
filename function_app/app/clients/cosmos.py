"""Cosmos client — DefaultAzureCredential, no keys."""
from __future__ import annotations

import os
from functools import lru_cache

from azure.cosmos import CosmosClient
from .foundry import get_credential


@lru_cache(maxsize=1)
def get_cosmos_client() -> CosmosClient:
    return CosmosClient(
        url=os.environ["COSMOS_ENDPOINT"],
        credential=get_credential(),
    )


def get_database():
    return get_cosmos_client().get_database_client(os.environ["COSMOS_DATABASE"])


def get_container(name: str):
    return get_database().get_container_client(name)
