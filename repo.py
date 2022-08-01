import csv
import requests

from dagster import repository, load_assets_from_current_module, asset, build_op_context
from dagster_snowflake import build_snowflake_io_manager
from dagster_snowflake_pandas import SnowflakePandasTypeHandler

from dagster import repository, with_resources
import os

snowflake_io_manager = build_snowflake_io_manager([SnowflakePandasTypeHandler()])

# assets.py
import pandas as pd
import requests

ITEM_FIELD_NAMES = ["id", "type", "title", "by"]

from typing import Any, Dict, Optional

import requests

from dagster import resource


class HNAPIClient:
    """
    Hacker News client that fetches live data
    """

    def fetch_item_by_id(self, item_id: int) -> Optional[Dict[str, Any]]:
        """Fetches a single item from the Hacker News API by item id."""

        item_url = f"https://hacker-news.firebaseio.com/v0/item/{item_id}.json"
        item = requests.get(item_url, timeout=5).json()
        return item

    def fetch_max_item_id(self) -> int:
        return requests.get("https://hacker-news.firebaseio.com/v0/maxitem.json", timeout=5).json()

    @property
    def item_field_names(self):
        return ["id", "type", "title", "by"]


@resource
def hn_api_client():
    return HNAPIClient()


class StubHNClient:
    """
    Hacker News Client that returns fake data
    """

    def __init__(self):
        self.data = {
            1: {
                "id": 1,
                "type": "comment",
                "title": "the first comment",
                "by": "user1",
            },
            2: {"id": 2, "type": "story", "title": "an awesome story", "by": "user2"},
        }

    def fetch_item_by_id(self, item_id: int) -> Optional[Dict[str, Any]]:
        return self.data.get(item_id)

    def fetch_max_item_id(self) -> int:
        return 2

    @property
    def item_field_names(self):
        return ["id", "type", "title", "by"]


@resource
def stub_hn_client():
    return StubHNClient()


@asset(
    config_schema={"N": int},
    required_resource_keys={"hn_client"},
    io_manager_key="snowflake_io_manager",
)
def items(context) -> pd.DataFrame:
    """Items from the Hacker News API: each is a story or a comment on a story."""
    hn_client = context.resources.hn_client

    max_id = hn_client.fetch_max_item_id()
    rows = []
    # Hacker News API is 1-indexed, so adjust range by 1
    for item_id in range(max_id - context.op_config["N"] + 1, max_id + 1):
        rows.append(hn_client.fetch_item_by_id(item_id))

    result = pd.DataFrame(rows, columns=hn_client.item_field_names).drop_duplicates(subset=["id"])
    result.rename(columns={"by": "user_id"}, inplace=True)
    return result


@asset(
    io_manager_key="snowflake_io_manager",
)
def comments(items: pd.DataFrame) -> pd.DataFrame:
    """Comments from the Hacker News API."""
    return items[items["type"] == "comment"]


@asset(
    io_manager_key="snowflake_io_manager",
)
def stories(items: pd.DataFrame) -> pd.DataFrame:
    """Stories from the Hacker News API."""
    return items[items["type"] == "story"]


# Note that storing passwords in configuration is bad practice. It will be resolved later in the guide.
@repository
def repo():
    resource_defs = {
        "local": {
            "snowflake_io_manager": snowflake_io_manager.configured(
                {
                    "account": "na94824.us-east-1",
                    "user": "claire@elementl.com",
                    # password in config is bad practice
                    "password": {"env": "DEV_SNOWFLAKE_PASSWORD"},
                    "database": "SANDBOX",
                    "schema": "CLAIRE",
                }
            ),
            "hn_client": hn_api_client,
        },
        "production": {
            "snowflake_io_manager": snowflake_io_manager.configured(
                {
                    "account": "na94824.us-east-1",
                    "user": "BOLLINGER",
                    # password in config is bad practice
                    "password": {"env": "SYSTEM_SNOWFLAKE_PASSWORD"},
                    "database": "PRODUCTION",
                    "schema": "HACKER_NEWS",
                }
            ),
        },
    }
    deployment_name = os.getenv("DAGSTER_DEPLOYMENT", "local")

    return [
        *with_resources([items, comments, stories], resource_defs=resource_defs[deployment_name])
    ]
