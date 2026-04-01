# Copyright 2025 New Vector Ltd.
# Copyright 2019 The Matrix.org Foundation C.I.C.
#
# SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-Element-Commercial
# Please see LICENSE files in the repository root for full details.
#
# Originally licensed under the Apache License, Version 2.0:
# <http://www.apache.org/licenses/LICENSE-2.0>.

from typing import Any

from tests import testutils

from sygnal.exceptions import (
    NotificationDispatchException,
    TemporaryNotificationDispatchException,
)
from sygnal.notifications import Device, Notification, NotificationContext, Pushkin

DEVICE_RAISE_EXCEPTION = {
    "app_id": "com.example.spqr",
    "pushkey": "raise_exception",
    "pushkey_ts": 1234,
}

DEVICE_REMOTE_ERROR = {
    "app_id": "com.example.spqr",
    "pushkey": "remote_error",
    "pushkey_ts": 1234,
}

DEVICE_TEMPORARY_REMOTE_ERROR = {
    "app_id": "com.example.spqr",
    "pushkey": "temporary_remote_error",
    "pushkey_ts": 1234,
}

DEVICE_REJECTED = {
    "app_id": "com.example.spqr",
    "pushkey": "reject",
    "pushkey_ts": 1234,
}

DEVICE_ACCEPTED = {
    "app_id": "com.example.spqr",
    "pushkey": "accept",
    "pushkey_ts": 1234,
}


class StubPushkin(Pushkin):
    """
    A synthetic Pushkin with simple rules.
    """

    async def dispatch_notification(
        self, n: Notification, device: Device, context: NotificationContext
    ) -> list[str]:
        if device.pushkey == "raise_exception":
            raise Exception("Bad things have occurred!")
        elif device.pushkey == "remote_error":
            raise NotificationDispatchException("Synthetic failure")
        elif device.pushkey == "temporary_remote_error":
            raise TemporaryNotificationDispatchException("Synthetic failure")
        elif device.pushkey == "reject":
            return [device.pushkey]
        elif device.pushkey == "accept":
            return []
        raise Exception(f"Unexpected fall-through. {device.pushkey}")


class PushGatewayApiV1TestCase(testutils.TestCase):
    def config_setup(self, config: dict[str, Any]) -> None:
        """
        Set up a StubPushkin for the test.
        """
        super().config_setup(config)
        config["apps"]["com.example.spqr"] = {
            "type": "tests.test_pushgateway_api_v1.StubPushkin"
        }

    async def test_good_requests_give_200(self) -> None:
        """
        Test that good requests give a 200 response code.
        """
        # 200 codes cause the result to be parsed instead of returning the code
        result = await self._request(
            self._make_dummy_notification([DEVICE_ACCEPTED, DEVICE_REJECTED])
        )
        assert not isinstance(result, int)

    async def test_accepted_devices_are_not_rejected(self) -> None:
        """
        Test that devices which are accepted by the Pushkin
        do not lead to a rejection being returned to the homeserver.
        """
        assert await self._request(
            self._make_dummy_notification([DEVICE_ACCEPTED])
        ) == {"rejected": []}

    async def test_rejected_devices_are_rejected(self) -> None:
        """
        Test that devices which are rejected by the Pushkin
        DO lead to a rejection being returned to the homeserver.
        """
        assert await self._request(
            self._make_dummy_notification([DEVICE_REJECTED])
        ) == {"rejected": [DEVICE_REJECTED["pushkey"]]}

    async def test_only_rejected_devices_are_rejected(self) -> None:
        """
        Test that devices which are rejected by the Pushkin
        are the only ones to have a rejection returned to the homeserver,
        even if other devices feature in the request.
        """
        assert await self._request(
            self._make_dummy_notification([DEVICE_REJECTED, DEVICE_ACCEPTED])
        ) == {"rejected": [DEVICE_REJECTED["pushkey"]]}

    async def test_bad_requests_give_400(self) -> None:
        """
        Test that bad requests lead to a 400 Bad Request response.
        """
        assert await self._request({}) == 400

    async def test_exceptions_give_500(self) -> None:
        """
        Test that internal exceptions/errors lead to a 500 Internal Server Error
        response.
        """

        assert (
            await self._request(self._make_dummy_notification([DEVICE_RAISE_EXCEPTION]))
            == 500
        )

        # we also check that a successful device doesn't hide the exception
        assert (
            await self._request(
                self._make_dummy_notification([DEVICE_ACCEPTED, DEVICE_RAISE_EXCEPTION])
            )
            == 500
        )

        assert (
            await self._request(
                self._make_dummy_notification([DEVICE_RAISE_EXCEPTION, DEVICE_ACCEPTED])
            )
            == 500
        )

    async def test_remote_errors_give_502(self) -> None:
        """
        Test that errors caused by remote services such as GCM or APNS
        lead to a 502 Bad Gateway response.
        """

        assert (
            await self._request(self._make_dummy_notification([DEVICE_REMOTE_ERROR]))
            == 502
        )

        # we also check that a successful device doesn't hide the exception
        assert (
            await self._request(
                self._make_dummy_notification([DEVICE_ACCEPTED, DEVICE_REMOTE_ERROR])
            )
            == 502
        )

        assert (
            await self._request(
                self._make_dummy_notification([DEVICE_REMOTE_ERROR, DEVICE_ACCEPTED])
            )
            == 502
        )
