# Copyright 2025 New Vector Ltd.
# Copyright 2019, 2020 The Matrix.org Foundation C.I.C.
#
# SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-Element-Commercial
# Please see LICENSE files in the repository root for full details.
#
# Originally licensed under the Apache License, Version 2.0:
# <http://www.apache.org/licenses/LICENSE-2.0>.

import asyncio
from typing import Any, Dict, List

from tests.testutils import TestCase

from sygnal.notifications import (
    ConcurrencyLimitedPushkin,
    Device,
    Notification,
    NotificationContext,
)

DEVICE_GCM1_EXAMPLE = {
    "app_id": "com.example.gcm",
    "pushkey": "spqrg",
    "pushkey_ts": 42,
}
DEVICE_GCM2_EXAMPLE = {
    "app_id": "com.example.gcm",
    "pushkey": "spqrh",
    "pushkey_ts": 42,
}
DEVICE_APNS_EXAMPLE = {
    "app_id": "com.example.apns",
    "pushkey": "spqra",
    "pushkey_ts": 42,
}


class SlowConcurrencyLimitedDummyPushkin(ConcurrencyLimitedPushkin):
    async def _dispatch_notification_unlimited(
        self, n: Notification, device: Device, context: NotificationContext
    ) -> List[str]:
        """
        We will deliver the notification to the mighty nobody
        and we will take one second to do it, because we are slow!
        """
        await asyncio.sleep(1.0)
        return []


class ConcurrencyLimitTestCase(TestCase):
    def config_setup(self, config: Dict[str, Any]) -> None:
        super().config_setup(config)
        config["apps"]["com.example.gcm"] = {
            "type": "tests.test_concurrency_limit.SlowConcurrencyLimitedDummyPushkin",
            "inflight_request_limit": 1,
        }
        config["apps"]["com.example.apns"] = {
            "type": "tests.test_concurrency_limit.SlowConcurrencyLimitedDummyPushkin",
            "inflight_request_limit": 1,
        }

    async def test_passes_under_limit_one(self) -> None:
        """
        Tests that a push notification succeeds if it is under the limit.
        """
        resp = await self._request(self._make_dummy_notification([DEVICE_GCM1_EXAMPLE]))

        assert resp == {"rejected": []}

    async def test_passes_under_limit_multiple_no_interfere(self) -> None:
        """
        Tests that 2 push notifications succeed if they are to different
        pushkins (so do not hit a per-pushkin limit).
        """
        resp = await self._request(
            self._make_dummy_notification([DEVICE_GCM1_EXAMPLE, DEVICE_APNS_EXAMPLE])
        )

        assert resp == {"rejected": []}

    async def test_fails_when_limit_hit(self) -> None:
        """
        Tests that 1 of 2 push notifications fail if they are to the same pushkins
        (so do hit the per-pushkin limit of 1).
        """
        resp = await self._multi_requests(
            [
                self._make_dummy_notification([DEVICE_GCM1_EXAMPLE]),
                self._make_dummy_notification([DEVICE_GCM2_EXAMPLE]),
            ]
        )

        # request 0 will succeed
        assert resp[0] == {"rejected": []}

        # request 1 will fail because request 0 has filled the limit
        assert resp[1] == 502
