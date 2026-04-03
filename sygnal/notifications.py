# Copyright 2019-2025 New Vector Ltd.
# Copyright 2019 The Matrix.org Foundation C.I.C.
# Copyright 2014 OpenMarket Ltd.
#
# SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-Element-Commercial
# Please see LICENSE files in the repository root for full details.
#
# Originally licensed under the Apache License, Version 2.0:
# <http://www.apache.org/licenses/LICENSE-2.0>.
import abc
from typing import TYPE_CHECKING, Any, ClassVar, TypeVar, overload

from matrix_common.regex import glob_to_regex
from opentracing import Span
from prometheus_client import Counter

from sygnal.exceptions import (
    InvalidNotificationException,
    NotificationDispatchException,
    PushkinSetupException,
)

if TYPE_CHECKING:
    from sygnal.sygnal import Sygnal

T = TypeVar("T")


@overload
def get_key(raw: dict[str, Any], key: str, type_: type[T], default: T) -> T: ...


@overload
def get_key(
    raw: dict[str, Any], key: str, type_: type[T], default: None = None
) -> T | None: ...


def get_key(
    raw: dict[str, Any], key: str, type_: type[T], default: T | None = None
) -> T | None:
    if key not in raw:
        return default
    value = raw[key]
    if not isinstance(value, type_):
        raise InvalidNotificationException(f"{key} is of invalid type")
    return value


class Tweaks:
    def __init__(self, raw: dict[str, Any]):
        self.sound: str | None = get_key(raw, "sound", str)


class Device:
    def __init__(self, raw: dict[str, Any]):
        if "app_id" not in raw or not isinstance(raw["app_id"], str):
            raise InvalidNotificationException(
                "Device with missing or non-string app_id"
            )
        self.app_id: str = raw["app_id"]
        if "pushkey" not in raw or not isinstance(raw["pushkey"], str):
            raise InvalidNotificationException(
                "Device with missing or non-string pushkey"
            )
        self.pushkey: str = raw["pushkey"]

        self.pushkey_ts: int = get_key(raw, "pushkey_ts", int, 0)
        self.data: dict[str, Any] | None = get_key(raw, "data", dict)
        self.tweaks = Tweaks(get_key(raw, "tweaks", dict, {}))


class Counts:
    def __init__(self, raw: dict[str, Any]):
        self.unread: int | None = get_key(raw, "unread", int)
        self.missed_calls: int | None = get_key(raw, "missed_calls", int)


class Notification:
    def __init__(self, notif: dict):
        # optional attributes
        self.room_name: str | None = notif.get("room_name")
        self.room_alias: str | None = notif.get("room_alias")
        self.prio: str | None = notif.get("prio")
        self.membership: str | None = notif.get("membership")
        self.sender_display_name: str | None = notif.get("sender_display_name")
        self.content: dict[str, Any] | None = notif.get("content")
        self.event_id: str | None = notif.get("event_id")
        self.room_id: str | None = notif.get("room_id")
        self.user_is_target: bool | None = notif.get("user_is_target")
        self.type: str | None = notif.get("type")
        self.sender: str | None = notif.get("sender")

        if "devices" not in notif or not isinstance(notif["devices"], list):
            raise InvalidNotificationException("Expected list in 'devices' key")

        if "counts" in notif:
            self.counts = Counts(notif["counts"])
        else:
            self.counts = Counts({})

        self.devices = [Device(d) for d in notif["devices"]]


class Pushkin(abc.ABC):
    def __init__(self, name: str, sygnal: "Sygnal", config: dict[str, Any]):
        self.name = name
        self.appid_pattern = glob_to_regex(name, ignore_case=False)
        self.cfg = config
        self.sygnal = sygnal

    @overload
    def get_config(self, key: str, type_: type[T], default: T) -> T: ...

    @overload
    def get_config(
        self, key: str, type_: type[T], default: None = None
    ) -> T | None: ...

    def get_config(
        self, key: str, type_: type[T], default: T | None = None
    ) -> T | None:
        if key not in self.cfg:
            return default
        value = self.cfg[key]
        if not isinstance(value, type_):
            raise PushkinSetupException(
                f"{key} is of incorrect type, please check that the entry for {key} is "
                f"formatted correctly in the config file. "
            )
        return value

    def handles_appid(self, appid: str) -> bool:
        """Checks whether the pushkin is responsible for the given app ID"""
        return self.name == appid or self.appid_pattern.match(appid) is not None

    @abc.abstractmethod
    async def dispatch_notification(
        self, n: Notification, device: Device, context: "NotificationContext"
    ) -> list[str]:
        """
        Args:
            n: The notification to dispatch via this pushkin
            device: The device to dispatch the notification for.
            context: the request context

        Returns:
            A list of rejected pushkeys, to be reported back to the homeserver
        """
        ...

    async def close(self) -> None:  # noqa: B027
        """Clean up resources held by this pushkin. Called during shutdown."""

    @classmethod
    async def create(
        cls, name: str, sygnal: "Sygnal", config: dict[str, Any]
    ) -> "Pushkin":
        """
        Override this if your pushkin needs to call async code in order to
        be constructed. Otherwise, it defaults to just invoking the Python-standard
        __init__ constructor.

        Returns:
            an instance of this Pushkin
        """
        return cls(name, sygnal, config)


class ConcurrencyLimitedPushkin(Pushkin):
    """
    A subclass of Pushkin that limits the number of in-flight requests at any
    one time, so as to prevent one Pushkin pulling the whole show down.
    """

    # Maximum in-flight, concurrent notification dispatches that we apply by default
    # We start turning away requests after this limit is reached.
    DEFAULT_CONCURRENCY_LIMIT = 512

    UNDERSTOOD_CONFIG_FIELDS: ClassVar[set[str]] = {"inflight_request_limit"}

    RATELIMITING_DROPPED_REQUESTS = Counter(
        "sygnal_inflight_request_limit_drop",
        "Number of notifications dropped because the number of inflight requests"
        " exceeded the configured inflight_request_limit.",
        labelnames=["pushkin"],
    )

    def __init__(self, name: str, sygnal: "Sygnal", config: dict[str, Any]):
        super().__init__(name, sygnal, config)
        self._concurrent_limit = config.get(
            "inflight_request_limit",
            ConcurrencyLimitedPushkin.DEFAULT_CONCURRENCY_LIMIT,
        )
        self._concurrent_now = 0

        # Grab an instance of the dropped request counter given our pushkin name.
        # Note this ensures the counter appears in metrics even if it hasn't yet
        # been incremented.
        dropped_requests = ConcurrencyLimitedPushkin.RATELIMITING_DROPPED_REQUESTS
        self.dropped_requests_counter = dropped_requests.labels(pushkin=name)

    async def dispatch_notification(
        self, n: Notification, device: Device, context: "NotificationContext"
    ) -> list[str]:
        if self._concurrent_now >= self._concurrent_limit:
            self.dropped_requests_counter.inc()
            raise NotificationDispatchException(
                "Too many in-flight requests for this pushkin. "
                "(Something is wrong and Sygnal is struggling to keep up!)"
            )

        self._concurrent_now += 1
        try:
            return await self._dispatch_notification_unlimited(n, device, context)
        finally:
            self._concurrent_now -= 1

    async def _dispatch_notification_unlimited(
        self, n: Notification, device: Device, context: "NotificationContext"
    ) -> list[str]:
        # to be overridden by Pushkins!
        raise NotImplementedError


class NotificationContext:
    def __init__(self, request_id: str, opentracing_span: Span, start_time: float):
        """
        Args:
            request_id: An ID for the request, or None to have it
                generated automatically.
            opentracing_span: The span for the API request triggering
                the notification.
            start_time: Start timer value, `time.perf_counter()`
        """
        self.request_id = request_id
        self.opentracing_span = opentracing_span
        self.start_time = start_time
