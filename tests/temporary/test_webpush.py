# -*- coding: utf-8 -*-
# Copyright 2026 New Vector Ltd.
#
# SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-Element-Commercial
# Please see LICENSE files in the repository root for full details.
#
#
# # Temporary tests
#
# These tests are LLM-generated in order to provide some bare minimum amount of
# behaviour locking, to slightly protect us against buggy dependency upgrades
# (as otherwise we currently have nothing).
#
# Ideally, we would have nice hand-written tests with some semblance of intent
# and careful thought behind them, but WebPush support is currently a niche
# feature that we are not using ourselves and, given time constraints, not something
# we 'should' be spending much time on right now.
#
# Further, MSC4174 (native WebPush at the protocol level) would make Sygnal's implementation
# of WebPush obsolete in any case (it would instead be implemented in homeservers).
#
# But all in all:
# If these tests get in the way and hinder more than help, feel free to remove them!

import base64
import os
import tempfile
from base64 import urlsafe_b64encode
from hashlib import blake2s
from typing import Any, Dict, List, Optional, cast
from unittest.mock import Mock

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from py_vapid import Vapid
from twisted.internet.defer import ensureDeferred, succeed
from twisted.python.failure import Failure
from twisted.web.client import ResponseDone
from twisted.web.http_headers import Headers
from twisted.web.iweb import IResponse
from zope.interface import implementer

from sygnal.exceptions import PushkinSetupException
from sygnal.notifications import Device, Notification, NotificationContext
from sygnal.webpushpushkin import HttpDelayedRequest, HttpRequestFactory, WebpushPushkin

from tests import testutils

# ---------------------------------------------------------------------------
# Test infrastructure
# ---------------------------------------------------------------------------


@implementer(IResponse)
class FakeWebpushResponse:
    """Minimal IResponse that works with twisted.web.client.readBody()."""

    def __init__(
        self,
        code: int,
        body: bytes = b"",
        phrase: bytes = b"OK",
    ) -> None:
        self.code = code
        self.phrase = phrase
        self.body = body
        self.headers = Headers()
        self.length: Optional[int] = len(body)
        self.version: int = 11
        self.request: Any = None
        self.previousResponse: Any = None

    def deliverBody(self, protocol: Any) -> None:
        protocol.dataReceived(self.body)
        protocol.connectionLost(Failure(ResponseDone()))

    def setPreviousResponse(self, response: Any) -> None:
        self.previousResponse = response


class FakeHttpDelayedRequest(HttpDelayedRequest):
    """An HttpDelayedRequest whose execute() returns a canned response."""

    def __init__(
        self,
        endpoint: str,
        data: bytes,
        vapid_headers: Any,
        response: FakeWebpushResponse,
    ) -> None:
        super().__init__(endpoint, data, vapid_headers)
        self._response = response
        self.captured_low_priority: bool = False
        self.captured_topic: Any = None

    def execute(self, http_agent: Any, low_priority: bool, topic: bytes) -> Any:
        self.captured_low_priority = low_priority
        self.captured_topic = topic
        return succeed(self._response)


class FakeHttpRequestFactory(HttpRequestFactory):
    """HttpRequestFactory that creates FakeHttpDelayedRequests."""

    def __init__(self) -> None:
        self._response: FakeWebpushResponse = FakeWebpushResponse(201)
        self.num_requests: int = 0
        self.last_request: Optional[FakeHttpDelayedRequest] = None

    def set_response(self, code: int, body: bytes = b"") -> None:
        self._response = FakeWebpushResponse(code, body)

    def post(
        self,
        endpoint: str,
        data: bytes,
        headers: Any,
        timeout: int,
    ) -> FakeHttpDelayedRequest:
        req = FakeHttpDelayedRequest(endpoint, data, headers, self._response)
        self.num_requests += 1
        self.last_request = req
        return req


class TestWebpushPushkin(WebpushPushkin):
    """WebpushPushkin with the HTTP layer replaced by FakeHttpRequestFactory."""

    http_request_factory: FakeHttpRequestFactory

    def __init__(self, name: str, sygnal: Any, config: Dict[str, Any]) -> None:
        super().__init__(name, sygnal, config)
        self.http_request_factory = FakeHttpRequestFactory()


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PUSHKIN_ID = "com.example.webpush"
ENDPOINT_URL = "https://push.example.com/v1/abcd1234"


# ---------------------------------------------------------------------------
# Test case
# ---------------------------------------------------------------------------


class WebpushTestCase(testutils.TestCase):
    maxDiff = None

    # --- Setup / teardown ---------------------------------------------------

    def setUp(self) -> None:
        # Generate a VAPID key pair and write it to a temp PEM file.
        vapid = Vapid()
        vapid.generate_keys()
        fd, self.vapid_key_path = tempfile.mkstemp(suffix=".pem")
        os.close(fd)
        vapid.save_key(self.vapid_key_path)

        # Generate an ECDH subscription key-pair (p256dh) and auth secret.
        private_key = ec.generate_private_key(ec.SECP256R1())
        pub_raw = private_key.public_key().public_bytes(
            Encoding.X962, PublicFormat.UncompressedPoint
        )
        self.subscription_p256dh: str = base64.urlsafe_b64encode(pub_raw).decode(
            "utf-8"
        )
        self.subscription_auth: str = base64.urlsafe_b64encode(os.urandom(16)).decode(
            "utf-8"
        )

        super().setUp()

    def tearDown(self) -> None:
        os.unlink(self.vapid_key_path)

    def config_setup(self, config: Dict[str, Any]) -> None:
        config["apps"][PUSHKIN_ID] = {
            "type": "tests.temporary.test_webpush.TestWebpushPushkin",
            "vapid_private_key": self.vapid_key_path,
            "vapid_contact_email": "test@example.com",
        }

    # --- Helpers ------------------------------------------------------------

    def get_test_pushkin(self) -> TestWebpushPushkin:
        pushkin = self.sygnal.pushkins[PUSHKIN_ID]
        assert isinstance(pushkin, TestWebpushPushkin)
        return pushkin

    def _get_pushkin(self, code: int = 201) -> TestWebpushPushkin:
        """Get the test pushkin with its fake HTTP layer configured to return *code*."""
        pushkin = self.get_test_pushkin()
        pushkin.http_request_factory.set_response(code)
        return pushkin

    def _make_webpush_device(
        self, extra_data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Build a device dict with valid webpush subscription info."""
        data: Dict[str, Any] = {
            "endpoint": ENDPOINT_URL,
            "auth": self.subscription_auth,
        }
        if extra_data:
            data.update(extra_data)
        return {
            "app_id": PUSHKIN_ID,
            "pushkey": self.subscription_p256dh,
            "pushkey_ts": 42,
            "data": data,
        }

    def _make_mock_sygnal(self) -> Mock:
        """Create a minimal mock Sygnal object for direct pushkin init."""
        mock = Mock()
        mock.reactor = self.reactor
        mock.config = {}
        return mock

    def _make_valid_config(self) -> Dict[str, Any]:
        """Config dict that passes all __init__ checks."""
        return {
            "type": "tests.temporary.test_webpush.TestWebpushPushkin",
            "vapid_private_key": self.vapid_key_path,
            "vapid_contact_email": "test@example.com",
        }

    def _make_pushkin_with_allowed_endpoints(
        self, patterns: List[str]
    ) -> TestWebpushPushkin:
        """Create a TestWebpushPushkin with allowed_endpoints configured."""
        config = self._make_valid_config()
        config["allowed_endpoints"] = patterns
        return TestWebpushPushkin(PUSHKIN_ID, self._make_mock_sygnal(), config)

    def _direct_dispatch(
        self,
        pushkin: TestWebpushPushkin,
        n: Notification,
        device: Device,
    ) -> List[str]:
        """Dispatch directly via _dispatch_notification_unlimited."""
        ctx = NotificationContext("", Mock(), 0)
        d = ensureDeferred(pushkin._dispatch_notification_unlimited(n, device, ctx))
        while not d.called:
            self.reactor.advance(1)
            self.reactor.wait_for_work(lambda: d.called)
        result = cast(List[str], d.result)
        return result

    def _check_handle_response(self, code: int) -> bool:
        """Call _handle_response with a fake response returning *code*."""
        pushkin = self.get_test_pushkin()
        return pushkin._handle_response(
            FakeWebpushResponse(code), "", "testkey", "push.example.com"
        )

    # -----------------------------------------------------------------------
    # End-to-end dispatch
    # -----------------------------------------------------------------------

    def test_dispatch_success_201(self) -> None:
        """Full chain: mock returns 201 → no pushkeys rejected."""
        self._get_pushkin(201)

        resp = self._request(
            self._make_dummy_notification([self._make_webpush_device()])
        )

        self.assertEqual(resp, {"rejected": []})

    def test_dispatch_rejects_on_410(self) -> None:
        """Mock returns 410 → pushkey rejected."""
        self._get_pushkin(410)

        resp = self._request(
            self._make_dummy_notification([self._make_webpush_device()])
        )

        self.assertEqual(resp, {"rejected": [self.subscription_p256dh]})

    def test_dispatch_rejects_on_404(self) -> None:
        """Mock returns 404 → pushkey rejected."""
        self._get_pushkin(404)

        resp = self._request(
            self._make_dummy_notification([self._make_webpush_device()])
        )

        self.assertEqual(resp, {"rejected": [self.subscription_p256dh]})

    def test_dispatch_no_reject_on_500(self) -> None:
        """Mock returns 500 → pushkey NOT rejected (transient error)."""
        self._get_pushkin(500)

        resp = self._request(
            self._make_dummy_notification([self._make_webpush_device()])
        )

        self.assertEqual(resp, {"rejected": []})

    # -----------------------------------------------------------------------
    # Device data validation (early-return branches)
    # -----------------------------------------------------------------------

    def test_rejects_when_device_data_missing(self) -> None:
        """Device with no 'data' field → pushkey rejected."""
        device = self._make_webpush_device()
        del device["data"]

        resp = self._request(self._make_dummy_notification([device]))

        self.assertEqual(resp, {"rejected": [self.subscription_p256dh]})

    def test_rejects_when_endpoint_missing(self) -> None:
        """data has 'auth' but no 'endpoint' → pushkey rejected."""
        device = self._make_webpush_device()
        del device["data"]["endpoint"]

        resp = self._request(self._make_dummy_notification([device]))

        self.assertEqual(resp, {"rejected": [self.subscription_p256dh]})

    def test_rejects_when_auth_missing(self) -> None:
        """data has 'endpoint' but no 'auth' → pushkey rejected."""
        device = self._make_webpush_device()
        del device["data"]["auth"]

        resp = self._request(self._make_dummy_notification([device]))

        self.assertEqual(resp, {"rejected": [self.subscription_p256dh]})

    def test_rejects_when_endpoint_not_string(self) -> None:
        """endpoint is an int → pushkey rejected."""
        device = self._make_webpush_device()
        device["data"]["endpoint"] = 42

        resp = self._request(self._make_dummy_notification([device]))

        self.assertEqual(resp, {"rejected": [self.subscription_p256dh]})

    def test_rejects_when_empty_pushkey(self) -> None:
        """pushkey is empty string → pushkey rejected."""
        device = self._make_webpush_device()
        device["pushkey"] = ""

        resp = self._request(self._make_dummy_notification([device]))

        self.assertEqual(resp, {"rejected": [""]})

    # -----------------------------------------------------------------------
    # WebPush-specific features
    # -----------------------------------------------------------------------

    def test_events_only_drops_without_event_id(self) -> None:
        """events_only=True and no event_id → no HTTP request, no rejection."""
        pushkin = self._get_pushkin(201)

        device = self._make_webpush_device({"events_only": True})
        # Build a notification WITHOUT event_id
        notif = {
            "notification": {
                "room_id": "!slw48wfj34rtnrf:example.com",
                "type": "m.room.message",
                "sender": "@example:matrix.org",
                "content": {"body": "hi", "msgtype": "m.text"},
                "devices": [device],
            }
        }

        resp = self._request(notif)

        self.assertEqual(resp, {"rejected": []})
        self.assertEqual(pushkin.http_request_factory.num_requests, 0)

    def test_events_only_sends_with_event_id(self) -> None:
        """events_only=True but event_id present → dispatched normally."""
        pushkin = self._get_pushkin(201)

        device = self._make_webpush_device({"events_only": True})
        resp = self._request(self._make_dummy_notification([device]))

        self.assertEqual(resp, {"rejected": []})
        self.assertEqual(pushkin.http_request_factory.num_requests, 1)

    def test_only_last_per_room_sets_topic_header(self) -> None:
        """only_last_per_room=True → Topic header is blake2s of room_id (32-char base64)."""
        pushkin = self._get_pushkin(201)

        device = self._make_webpush_device({"only_last_per_room": True})
        resp = self._request(self._make_dummy_notification([device]))

        self.assertEqual(resp, {"rejected": []})
        last_req = pushkin.http_request_factory.last_request
        assert last_req is not None
        topic = last_req.captured_topic
        self.assertIsNotNone(topic)
        # blake2s with digest_size=22 → 22 bytes → base64 = 32 chars
        self.assertEqual(len(topic), 32)
        # Verify the actual value matches what the pushkin should compute
        room_id = "!slw48wfj34rtnrf:example.com"
        expected_topic = urlsafe_b64encode(
            blake2s(room_id.encode(), digest_size=22).digest()
        )
        self.assertEqual(topic, expected_topic)

    def test_no_topic_without_only_last_per_room(self) -> None:
        """only_last_per_room absent → topic is None."""
        pushkin = self._get_pushkin(201)

        device = self._make_webpush_device()
        resp = self._request(self._make_dummy_notification([device]))

        self.assertEqual(resp, {"rejected": []})
        last_req = pushkin.http_request_factory.last_request
        assert last_req is not None
        self.assertIsNone(last_req.captured_topic)

    def test_allowed_endpoints_blocks_disallowed(self) -> None:
        """Endpoint not in allowed_endpoints → no request, no rejection."""
        pushkin = self._make_pushkin_with_allowed_endpoints(["push.example.com"])
        pushkin.http_request_factory.set_response(201)

        n = Notification(self._make_dummy_notification([])["notification"])
        device = Device(
            self._make_webpush_device({"endpoint": "https://evil.com/push"})
        )

        result = self._direct_dispatch(pushkin, n, device)

        self.assertEqual(result, [])
        self.assertEqual(pushkin.http_request_factory.num_requests, 0)

    def test_allowed_endpoints_permits_matching(self) -> None:
        """Endpoint matching allowed_endpoints → dispatched normally."""
        pushkin = self._make_pushkin_with_allowed_endpoints(["push.example.com"])
        pushkin.http_request_factory.set_response(201)

        n = Notification(self._make_dummy_notification([])["notification"])
        device = Device(self._make_webpush_device())

        result = self._direct_dispatch(pushkin, n, device)

        self.assertEqual(result, [])
        self.assertEqual(pushkin.http_request_factory.num_requests, 1)

    def test_allowed_endpoints_glob(self) -> None:
        """Glob pattern in allowed_endpoints → matches subdomain."""
        pushkin = self._make_pushkin_with_allowed_endpoints(["*.example.com"])
        pushkin.http_request_factory.set_response(201)

        n = Notification(self._make_dummy_notification([])["notification"])
        device = Device(
            self._make_webpush_device({"endpoint": "https://sub.example.com/sub"})
        )

        result = self._direct_dispatch(pushkin, n, device)

        self.assertEqual(result, [])
        self.assertEqual(pushkin.http_request_factory.num_requests, 1)

    def test_urgency_header_high_prio(self) -> None:
        """prio: 'high' → low_priority=False (Urgency: 'normal')."""
        self._get_pushkin(201)

        device = self._make_webpush_device()
        resp = self._request(self._make_dummy_notification([device]))

        self.assertEqual(resp, {"rejected": []})
        last_req = self.get_test_pushkin().http_request_factory.last_request
        assert last_req is not None
        self.assertFalse(last_req.captured_low_priority)

    def test_urgency_header_low_prio(self) -> None:
        """prio: 'low' → low_priority=True (Urgency: 'low')."""
        self._get_pushkin(201)

        device = self._make_webpush_device()
        notif = self._make_dummy_notification([device])
        notif["notification"]["prio"] = "low"
        resp = self._request(notif)

        self.assertEqual(resp, {"rejected": []})
        last_req = self.get_test_pushkin().http_request_factory.last_request
        assert last_req is not None
        self.assertTrue(last_req.captured_low_priority)

    # -----------------------------------------------------------------------
    # Payload construction (_build_payload, static method)
    # -----------------------------------------------------------------------

    def test_payload_body_truncation(self) -> None:
        """Body longer than 1000 chars is truncated with trailing …."""
        long_body = "x" * 1001
        n = Notification({"content": {"body": long_body}, "devices": []})
        device = Device({"app_id": PUSHKIN_ID, "pushkey": "test"})

        payload = WebpushPushkin._build_payload(n, device)

        body = payload["content"]["body"]
        self.assertEqual(len(body), 1000)
        self.assertTrue(body.endswith("…"))
        self.assertEqual(body[:999], "x" * 999)

    def test_payload_ciphertext_removal(self) -> None:
        """Ciphertext longer than 2000 chars is removed entirely."""
        long_ct = "x" * 2001
        n = Notification(
            {"content": {"body": "hello", "ciphertext": long_ct}, "devices": []}
        )
        device = Device({"app_id": PUSHKIN_ID, "pushkey": "test"})

        payload = WebpushPushkin._build_payload(n, device)

        self.assertNotIn("ciphertext", payload["content"])
        self.assertEqual(payload["content"]["body"], "hello")

    def test_payload_ciphertext_kept_when_short(self) -> None:
        """Ciphertext at or below 2000 chars is kept."""
        ct = "x" * 2000
        n = Notification(
            {"content": {"body": "hello", "ciphertext": ct}, "devices": []}
        )
        device = Device({"app_id": PUSHKIN_ID, "pushkey": "test"})

        payload = WebpushPushkin._build_payload(n, device)

        self.assertEqual(payload["content"]["ciphertext"], ct)

    def test_payload_formatted_body_stripped(self) -> None:
        """formatted_body is always removed from content."""
        n = Notification(
            {
                "content": {
                    "body": "hello",
                    "formatted_body": "<b>hello</b>",
                },
                "devices": [],
            }
        )
        device = Device({"app_id": PUSHKIN_ID, "pushkey": "test"})

        payload = WebpushPushkin._build_payload(n, device)

        self.assertNotIn("formatted_body", payload["content"])
        self.assertEqual(payload["content"]["body"], "hello")

    def test_payload_default_payload_merged(self) -> None:
        """device.data.default_payload dict is merged into the top-level payload."""
        n = Notification({"event_id": "$event", "devices": []})
        device = Device(
            {
                "app_id": PUSHKIN_ID,
                "pushkey": "test",
                "data": {
                    "default_payload": {"custom_key": "custom_value", "tag": "mytag"},
                },
            }
        )

        payload = WebpushPushkin._build_payload(n, device)

        self.assertEqual(payload["custom_key"], "custom_value")
        self.assertEqual(payload["tag"], "mytag")
        self.assertEqual(payload["event_id"], "$event")

    def test_payload_counts_flattened(self) -> None:
        """counts.unread → top-level unread, counts.missed_calls → missed_calls."""
        n = Notification({"counts": {"unread": 5, "missed_calls": 2}, "devices": []})
        device = Device({"app_id": PUSHKIN_ID, "pushkey": "test"})

        payload = WebpushPushkin._build_payload(n, device)

        self.assertEqual(payload["unread"], 5)
        self.assertEqual(payload["missed_calls"], 2)

    def test_payload_full_notification(self) -> None:
        """All expected fields are present for a fully-populated notification."""
        n = Notification(
            {
                "room_id": "!room:example.com",
                "room_name": "Room Name",
                "room_alias": "#room:example.com",
                "membership": "join",
                "event_id": "$event_id",
                "sender": "@alice:example.com",
                "sender_display_name": "Alice",
                "user_is_target": True,
                "type": "m.room.message",
                "content": {"body": "hello", "msgtype": "m.text"},
                "counts": {"unread": 3, "missed_calls": 1},
                "devices": [],
            }
        )
        device = Device(
            {
                "app_id": PUSHKIN_ID,
                "pushkey": "test",
                "data": {"default_payload": {"extra": "data"}},
            }
        )

        payload = WebpushPushkin._build_payload(n, device)

        self.assertEqual(payload["room_id"], "!room:example.com")
        self.assertEqual(payload["room_name"], "Room Name")
        self.assertEqual(payload["room_alias"], "#room:example.com")
        self.assertEqual(payload["membership"], "join")
        self.assertEqual(payload["event_id"], "$event_id")
        self.assertEqual(payload["sender"], "@alice:example.com")
        self.assertEqual(payload["sender_display_name"], "Alice")
        self.assertTrue(payload["user_is_target"])
        self.assertEqual(payload["type"], "m.room.message")
        self.assertIn("content", payload)
        self.assertEqual(payload["content"]["body"], "hello")
        self.assertEqual(payload["content"]["msgtype"], "m.text")
        self.assertEqual(payload["unread"], 3)
        self.assertEqual(payload["missed_calls"], 1)
        self.assertEqual(payload["extra"], "data")

    # -----------------------------------------------------------------------
    # Configuration / Init
    # -----------------------------------------------------------------------

    def test_init_missing_vapid_key_raises(self) -> None:
        """No 'vapid_private_key' in config → PushkinSetupException."""
        config = self._make_valid_config()
        del config["vapid_private_key"]

        with self.assertRaises(PushkinSetupException):
            WebpushPushkin(PUSHKIN_ID, self._make_mock_sygnal(), config)

    def test_init_missing_contact_email_raises(self) -> None:
        """No 'vapid_contact_email' in config → PushkinSetupException."""
        config = self._make_valid_config()
        del config["vapid_contact_email"]

        with self.assertRaises(PushkinSetupException):
            WebpushPushkin(PUSHKIN_ID, self._make_mock_sygnal(), config)

    def test_init_nonexistent_key_file_raises(self) -> None:
        """Path to nonexistent file → PushkinSetupException."""
        config = self._make_valid_config()
        config["vapid_private_key"] = "/no/such/file.pem"

        with self.assertRaises(PushkinSetupException):
            WebpushPushkin(PUSHKIN_ID, self._make_mock_sygnal(), config)

    def test_init_invalid_key_file_raises(self) -> None:
        """File exists but isn't a valid VAPID key → PushkinSetupException."""
        fd, bad_path = tempfile.mkstemp(suffix=".pem")
        os.write(fd, b"this is not a valid key")
        os.close(fd)
        try:
            config = self._make_valid_config()
            config["vapid_private_key"] = bad_path

            with self.assertRaises(PushkinSetupException):
                WebpushPushkin(PUSHKIN_ID, self._make_mock_sygnal(), config)
        finally:
            os.unlink(bad_path)

    def test_init_default_ttl(self) -> None:
        """TTL defaults to 900 when not configured."""
        config = self._make_valid_config()
        # Ensure no 'ttl' key is present
        config.pop("ttl", None)

        pushkin = TestWebpushPushkin(PUSHKIN_ID, self._make_mock_sygnal(), config)

        self.assertEqual(pushkin.ttl, 900)

    # -----------------------------------------------------------------------
    # Response handling (_handle_response, direct method call)
    # -----------------------------------------------------------------------

    def test_returns_true_for_404(self) -> None:
        """404 → pushkey should be rejected."""
        self.assertTrue(self._check_handle_response(404))

    def test_returns_true_for_410(self) -> None:
        """410 → pushkey should be rejected."""
        self.assertTrue(self._check_handle_response(410))

    def test_returns_false_for_201(self) -> None:
        """201 → pushkey should NOT be rejected."""
        self.assertFalse(self._check_handle_response(201))

    def test_returns_false_for_200(self) -> None:
        """200 → pushkey should NOT be rejected."""
        self.assertFalse(self._check_handle_response(200))

    def test_returns_false_for_500(self) -> None:
        """500 → pushkey should NOT be rejected (transient)."""
        self.assertFalse(self._check_handle_response(500))

    def test_returns_false_for_429(self) -> None:
        """429 → pushkey should NOT be rejected (rate-limited)."""
        self.assertFalse(self._check_handle_response(429))
