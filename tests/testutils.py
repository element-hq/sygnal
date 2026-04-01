# -*- coding: utf-8 -*-
# Copyright 2025 New Vector Ltd.
# Copyright 2019, 2020 The Matrix.org Foundation C.I.C.
#
# SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-Element-Commercial
# Please see LICENSE files in the repository root for full details.
#
# Originally licensed under the Apache License, Version 2.0:
# <http://www.apache.org/licenses/LICENSE-2.0>.
import json
import pathlib
from collections.abc import AsyncGenerator
from typing import Any, Dict, List, Union

import aiohttp.test_utils
import pytest_asyncio

from sygnal.http import create_app
from sygnal.sygnal import CONFIG_DEFAULTS, Sygnal, merge_left_with_defaults

REQ_PATH = "/_matrix/push/v1/notify"


class TestCase:
    """Base class for Sygnal integration tests using aiohttp test client."""

    def config_setup(self, config: Dict[str, Any]) -> None:
        pass

    def pre_setup(self) -> None:
        """Hook called before Sygnal initialization. Override for mocking."""
        pass

    def post_setup(self) -> None:
        """Hook called after Sygnal and pushkins are initialized."""
        pass

    @pytest_asyncio.fixture(autouse=True)
    async def _setup_sygnal(
        self, aiohttp_client: Any, tmp_path: pathlib.Path
    ) -> AsyncGenerator[None]:
        logging_config = {
            "setup": {
                "disable_existing_loggers": False,
                "formatters": {
                    "normal": {
                        "format": "%(asctime)s [%(process)d] "
                        "%(levelname)-5s %(name)s %(message)s"
                    }
                },
                "handlers": {
                    "stderr": {
                        "class": "logging.StreamHandler",
                        "formatter": "normal",
                        "stream": "ext://sys.stderr",
                    },
                },
                "loggers": {
                    "sygnal": {"handlers": ["stderr"], "propagate": False},
                    "sygnal.access": {
                        "handlers": ["stderr"],
                        "level": "INFO",
                        "propagate": False,
                    },
                },
                "root": {"handlers": ["stderr"], "level": "DEBUG"},
                "version": 1,
            }
        }

        self.tmp_path = tmp_path

        config: Dict[str, Any] = {"apps": {}, "log": logging_config}
        self.config_setup(config)

        config = merge_left_with_defaults(CONFIG_DEFAULTS, config)

        self.pre_setup()

        self.sygnal = Sygnal(config)

        # Create pushkins
        for app_id, app_cfg in self.sygnal.config["apps"].items():
            self.sygnal.pushkins[app_id] = await self.sygnal._make_pushkin(
                app_id, app_cfg
            )

        self.post_setup()

        app = create_app(self.sygnal)
        self.client: aiohttp.test_utils.TestClient = await aiohttp_client(app)

        yield

        from unittest.mock import patch

        patch.stopall()

    def _make_dummy_notification(self, devices: List[Dict[str, Any]]) -> Dict[str, Any]:
        return {
            "notification": {
                "id": "$3957tyerfgewrf384",
                "room_id": "!slw48wfj34rtnrf:example.com",
                "event_id": "$qTOWWTEL48yPm3uT-gdNhFcoHxfKbZuqRVnnWWSkGBs",
                "type": "m.room.message",
                "sender": "@exampleuser:matrix.org",
                "sender_display_name": "Major Tom",
                "room_name": "Mission Control",
                "room_alias": "#exampleroom:matrix.org",
                "prio": "high",
                "content": {
                    "msgtype": "m.text",
                    "body": "I'm floating in a most peculiar way.",
                    "other": 1,
                },
                "counts": {"unread": 2, "missed_calls": 1},
                "devices": devices,
            }
        }

    def _make_dummy_notification_event_id_only(
        self, devices: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        return {
            "notification": {
                "room_id": "!slw48wfj34rtnrf:example.com",
                "event_id": "$qTOWWTEL48yPm3uT-gdNhFcoHxfKbZuqRVnnWWSkGBs",
                "counts": {"unread": 2},
                "devices": devices,
            }
        }

    def _make_dummy_notification_badge_only(
        self, devices: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        return {
            "notification": {
                "id": "",
                "type": None,
                "sender": "",
                "counts": {"unread": 2},
                "devices": devices,
            }
        }

    # NOTE: The `⚑` character (len 3 bytes) is inserted at byte position 1020 (occupying 1020-1022).
    # This will make the truncation (which is `str[: 1024 - 3]`) occur in the middle of a unicode
    # character. The truncation logic should recognize this and return the string starting before
    # the `⚑`, with a `…` appended to indicate the string was truncated.
    def _make_dummy_notification_large_fields(
        self, devices: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        return {
            "notification": {
                "id": "$3957tyerfgewrf384",
                "room_id": "!slw48wfj34rtnrf:example.com",
                "event_id": "$qTOWWTEL48yPm3uT-gdNhFcoHxfKbZuqRVnnWWSkGBs",
                "type": "m.room.message",
                "sender": "@exampleuser:matrix.org",
                "sender_display_name": "Major Tom",
                "room_name": "xxxxxxxxxxooooooooooxxxxxxxxxxooooooooooxxxxxxxxxxoooooooooo\
xxxxxxxxxxooooooooooxxxxxxxxxxooooooooooxxxxxxxxxxooooooooooxxxxxxxxxx\
ooooooooooxxxxxxxxxxooooooooooxxxxxxxxxxooooooooooxxxxxxxxxxoooooooooo\
xxxxxxxxxxooooooooooxxxxxxxxxxooooooooooxxxxxxxxxxooooooooooxxxxxxxxxx\
ooooooooooxxxxxxxxxxooooooooooxxxxxxxxxxooooooooooxxxxxxxxxxoooooooooo\
xxxxxxxxxxooooooooooxxxxxxxxxxooooooooooxxxxxxxxxxooooooooooxxxxxxxxxx\
ooooooooooxxxxxxxxxxooooooooooxxxxxxxxxxooooooooooxxxxxxxxxxoooooooooo\
xxxxxxxxxxooooooooooxxxxxxxxxxooooooooooxxxxxxxxxxooooooooooxxxxxxxxxx\
ooooooooooxxxxxxxxxxooooooooooxxxxxxxxxxooooooooooxxxxxxxxxxoooooooooo\
xxxxxxxxxxooooooooooxxxxxxxxxxooooooooooxxxxxxxxxxooooooooooxxxxxxxxxx\
ooooooooooxxxxxxxxxxooooooooooxxxxxxxxxxooooooooooxxxxxxxxxxoooooooooo\
xxxxxxxxxxooooooooooxxxxxxxxxxooooooooooxxxxxxxxxxooooooooooxxxxxxxxxx\
ooooooooooxxxxxxxxxxooooooooooxxxxxxxxxxooooooooooxxxxxxxxxxoooooooooo\
xxxxxxxxxxooooooooooxxxxxxxxxxooooooooooxxxxxxxxxxooooooooooxxxxxxxxxx\
ooooooooooxxxxxxxxxxooooooooooxxxxxxxxxxooooooooooxxxxxxxxxxoooooooooo\
xxxxxxxxxxooooooooooxxxxxxxxxxooooooooooxxxxxxxxxxooooooooooxxxxxxxxxx\
ooooooooooxxxxxxxxxxooooooooooxxxxxxxxxxooooooooooxxxxxxxxxxoooooooooo\
xxxxxxxxxxooooooooooxxxxxxxxxxooooooooooxxxxxxxxxxooooooooooxxxxxxxxxx\
ooooooooooxxxxxxxxxxooooooooooxxxxxxxxxxooooooooooxxxxxxxxxxoooooooooo\
xxxxxxxxxxooooooooooxxxxxxxxxxooooooooooxxxxxxxxxxooooooooooxxxxxxxxxx\
ooooooooooxxxxxxxxxxooooooooooxxxxxxxxxxooooooooooxxxxxxxxxxoooooooooo\
xxxxxxxxxxooooooooooxxxxxxxxxxooooooooooxxxxxxxxxxooooooooooxxxxxxxxxx\
ooooooooooxxxxxxxxxxooooooooooxxxxxxxxxxooooooooooxxxxxxxxxxoooooooooo\
xxxxxxxxxxooooooooooxxxxxxxxxxooooooooooxxxxxxxxxxooooooooooxxxxxxxxxx\
ooooooooooxxxxxxxxxxooooooooooxxxxxxxxxxooooooooooxxxxxxxxxxoooooooooo\
xxxxxxxxxxooooooooooxxxxxxxxxxooooooooooxxxxxxxxxxooooooooooxxxxxxxxxx\
ooooooooooxxxxxxxxxxooooooooooxxxxxxxxxxooooooooooxxxxxxxxxxoooooooooo\
xxxxxxxxxxooooooooooxxxxxxxxxxooooooooooxxxxxxxxxxooooooooooxxxxxxxxxx\
ooooooooooxxxxxxxxxxooooooooooxxxxxxxxxxooooooooooxxxxxxxxxxoooooooooo\
xxxxxxxxxxooooooooooxxxxxxxxxxooooooooooxxxxxxxxxxooooooooooxxxxxxxxxx\
ooooooooooxxxxxxxxxxooooooooooxxxxxxxxxxooooooooooxxxxxxxxxxoooooooooo\
xxxxxxxxxxooooooooooxxxxxxxxxxooooooooooxxxxxxxxxxooooooooooxxxxxxxxxx\
ooooooooooxxxxxxxxxxooooooooooxxxxxxxxxxooooooooooxxxxxxxxxxoooooooooo\
xxxxxxxxxxooooooooooxxxxxxxxxxooooooooooxxxxxxxxxxooooooooooxxxxxxxxxx\
ooooooooooxxxxxxxxxxooooooooooxxxxxxxxxxooooooooooxxxxxxxxxxoooooooooo",
                "room_alias": "#exampleroom:matrix.org",
                "prio": "high",
                "content": {
                    "msgtype": "m.text",
                    "body": "I'm floating in a most peculiar way.",
                    "other": "xxxxxxxxxxooooooooooxxxxxxxxxxooooooooooxxxxxxxxxxoooooooooo\
xxxxxxxxxxooooooooooxxxxxxxxxxooooooooooxxxxxxxxxxooooooooooxxxxxxxxxx\
ooooooooooxxxxxxxxxxooooooooooxxxxxxxxxxooooooooooxxxxxxxxxxoooooooooo\
xxxxxxxxxxooooooooooxxxxxxxxxxooooooooooxxxxxxxxxxooooooooooxxxxxxxxxx\
ooooooooooxxxxxxxxxxooooooooooxxxxxxxxxxooooooooooxxxxxxxxxxoooooooooo\
xxxxxxxxxxooooooooooxxxxxxxxxxooooooooooxxxxxxxxxxooooooooooxxxxxxxxxx\
ooooooooooxxxxxxxxxxooooooooooxxxxxxxxxxooooooooooxxxxxxxxxxoooooooooo\
xxxxxxxxxxooooooooooxxxxxxxxxxooooooooooxxxxxxxxxxooooooooooxxxxxxxxxx\
ooooooooooxxxxxxxxxxooooooooooxxxxxxxxxxooooooooooxxxxxxxxxxoooooooooo\
xxxxxxxxxxooooooooooxxxxxxxxxxooooooooooxxxxxxxxxxooooooooooxxxxxxxxxx\
ooooooooooxxxxxxxxxxooooooooooxxxxxxxxxxooooooooooxxxxxxxxxxoooooooooo\
xxxxxxxxxxooooooooooxxxxxxxxxxooooooooooxxxxxxxxxxooooooooooxxxxxxxxxx\
ooooooooooxxxxxxxxxxooooooooooxxxxxxxxxxooooooooooxxxxxxxxxxoooooooooo\
xxxxxxxxxxooooooooooxxxxxxxxxxooooooooooxxxxxxxxxxooooooooooxxxxxxxxxx\
ooooooooooxxxxxxxxxx🦉oooooo£xxxxxxxx☻oo🦉⚑xxxxxxxxxxoooooooooo\
xxxxxxxxxxooooooooooxxxxxxxxxxooooooooooxxxxxxxxxxooooooooooxxxxxxxxxx\
ooooooooooxxxxxxxxxxooooooooooxxxxxxxxxxooooooooooxxxxxxxxxxoooooooooo\
xxxxxxxxxxooooooooooxxxxxxxxxxooooooooooxxxxxxxxxxooooooooooxxxxxxxxxx\
ooooooooooxxxxxxxxxxooooooooooxxxxxxxxxxooooooooooxxxxxxxxxxoooooooooo\
xxxxxxxxxxooooooooooxxxxxxxxxxooooooooooxxxxxxxxxxooooooooooxxxxxxxxxx\
ooooooooooxxxxxxxxxxooooooooooxxxxxxxxxxooooooooooxxxxxxxxxxoooooooooo\
xxxxxxxxxxooooooooooxxxxxxxxxxooooooooooxxxxxxxxxxooooooooooxxxxxxxxxx\
ooooooooooxxxxxxxxxxooooooooooxxxxxxxxxxooooooooooxxxxxxxxxxoooooooooo\
xxxxxxxxxxooooooooooxxxxxxxxxxooooooooooxxxxxxxxxxooooooooooxxxxxxxxxx\
ooooooooooxxxxxxxxxxooooooooooxxxxxxxxxxooooooooooxxxxxxxxxxoooooooooo\
xxxxxxxxxxooooooooooxxxxxxxxxxooooooooooxxxxxxxxxxooooooooooxxxxxxxxxx\
ooooooooooxxxxxxxxxxooooooooooxxxxxxxxxxooooooooooxxxxxxxxxxoooooooooo\
xxxxxxxxxxooooooooooxxxxxxxxxxooooooooooxxxxxxxxxxooooooooooxxxxxxxxxx\
ooooooooooxxxxxxxxxxooooooooooxxxxxxxxxxooooooooooxxxxxxxxxxoooooooooo\
xxxxxxxxxxooooooooooxxxxxxxxxxooooooooooxxxxxxxxxxooooooooooxxxxxxxxxx\
ooooooooooxxxxxxxxxxooooooooooxxxxxxxxxxooooooooooxxxxxxxxxxoooooooooo",
                },
                "counts": {"unread": 2, "missed_calls": 1},
                "devices": devices,
            }
        }

    async def _request(self, payload: Union[str, dict]) -> Union[dict, int]:
        """
        Make a dummy request to the notify endpoint with the specified payload

        Args:
            payload: payload to be JSON encoded

        Returns (dict or int):
            If successful (200 response received), the response is JSON decoded
            and the resultant dict is returned.
            If the response code is not 200, returns the response code.
        """
        if isinstance(payload, dict):
            payload = json.dumps(payload)

        resp = await self.client.post(
            REQ_PATH,
            data=payload.encode(),
            headers={"Content-Type": "application/json"},
        )

        if resp.status != 200:
            return resp.status

        return await resp.json()  # type: ignore[no-any-return]

    async def _multi_requests(
        self, payloads: List[Union[str, dict]]
    ) -> List[Union[dict, int]]:
        """
        Make multiple dummy requests to the notify endpoint with the specified payloads.
        """
        import asyncio

        tasks = [self._request(payload) for payload in payloads]
        return await asyncio.gather(*tasks)


class DummyResponse:
    def __init__(self, code: int) -> None:
        self.status = code
        self.headers: Dict[str, str] = {}


def make_async_magic_mock(ret_val: Any) -> Any:
    async def dummy(*_args: Any, **_kwargs: Any) -> Any:
        return ret_val

    return dummy
