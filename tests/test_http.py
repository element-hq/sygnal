# Copyright 2025 New Vector Ltd.
# Copyright 2019 The Matrix.org Foundation C.I.C.
#
# SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-Element-Commercial
# Please see LICENSE files in the repository root for full details.
#
# Originally licensed under the Apache License, Version 2.0:
# <http://www.apache.org/licenses/LICENSE-2.0>.
from typing import Any, Dict
from unittest.mock import MagicMock, patch

from aioapns.common import NotificationResult

from sygnal.apnspushkin import ApnsPushkin

from tests import testutils

PUSHKIN_ID_1 = "com.example.apns"
PUSHKIN_ID_2 = "*.example.*"
PUSHKIN_ID_3 = "com.example.a*"

TEST_CERTFILE_PATH = "/path/to/my/certfile.pem"

# Specific app id
DEVICE_EXAMPLE_SPECIFIC = {
    "app_id": "com.example.apns",
    "pushkey": "spqr",
    "pushkey_ts": 42,
}

# Only one time matching app id (with PUSHKIN_ID_2)
DEVICE_EXAMPLE_MATCHING = {
    "app_id": "com.example.bpns",
    "pushkey": "spqr",
    "pushkey_ts": 42,
}

# More than one times matching app id (with PUSHKIN_ID_2 and PUSHKIN_ID_3)
DEVICE_EXAMPLE_AMBIGIOUS = {
    "app_id": "com.example.apns2",
    "pushkey": "spqr",
    "pushkey_ts": 42,
}


class HttpTestCase(testutils.TestCase):
    def setUp(self) -> None:
        self.apns_mock_class = patch("sygnal.apnspushkin.APNs").start()
        self.apns_mock = MagicMock()
        self.apns_mock_class.return_value = self.apns_mock

        # pretend our certificate exists
        patch("os.path.exists", lambda x: x == TEST_CERTFILE_PATH).start()
        # Since no certificate exists, don't try to read it.
        patch("sygnal.apnspushkin.ApnsPushkin._report_certificate_expiration").start()
        self.addCleanup(patch.stopall)

        super().setUp()

        self.apns_pushkin_snotif = MagicMock()
        for key, value in self.sygnal.pushkins.items():
            assert isinstance(value, ApnsPushkin)
            # type safety: ignore is used here due to mypy not handling monkeypatching,
            # see https://github.com/python/mypy/issues/2427
            value._send_notification = self.apns_pushkin_snotif  # type: ignore[assignment] # noqa: E501

    def config_setup(self, config: Dict[str, Any]) -> None:
        super().config_setup(config)
        config["apps"][PUSHKIN_ID_1] = {"type": "apns", "certfile": TEST_CERTFILE_PATH}
        config["apps"][PUSHKIN_ID_2] = {"type": "apns", "certfile": TEST_CERTFILE_PATH}
        config["apps"][PUSHKIN_ID_3] = {"type": "apns", "certfile": TEST_CERTFILE_PATH}

    def test_with_specific_appid(self) -> None:
        """
        Tests the expected case: A specific app id must be processed.
        """
        # Arrange
        method = self.apns_pushkin_snotif
        method.side_effect = testutils.make_async_magic_mock(
            NotificationResult("notID", "200")
        )

        # Act
        resp = self._request(self._make_dummy_notification([DEVICE_EXAMPLE_SPECIFIC]))

        # Assert
        # method should be called one time
        self.assertEqual(1, method.call_count)

        self.assertEqual({"rejected": []}, resp)

    def test_with_matching_appid(self) -> None:
        """
        Tests the matching case: A matching app id (only one time) must be processed.
        """
        # Arrange
        method = self.apns_pushkin_snotif
        method.side_effect = testutils.make_async_magic_mock(
            NotificationResult("notID", "200")
        )

        # Act
        resp = self._request(self._make_dummy_notification([DEVICE_EXAMPLE_MATCHING]))

        # Assert
        # method should be called one time
        self.assertEqual(1, method.call_count)

        self.assertEqual({"rejected": []}, resp)

    def test_with_ambigious_appid(self) -> None:
        """
        Tests the rejection case: An ambigious app id should be rejected without
        processing.
        """
        # Arrange
        method = self.apns_pushkin_snotif

        # Act
        resp = self._request(self._make_dummy_notification([DEVICE_EXAMPLE_AMBIGIOUS]))

        # Assert
        # must be rejected without calling the method
        self.assertEqual(0, method.call_count)
        self.assertEqual({"rejected": ["spqr"]}, resp)
