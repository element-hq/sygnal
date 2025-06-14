# -*- coding: utf-8 -*-
# Copyright 2025 New Vector Ltd.
# Copyright 2019, 2020 The Matrix.org Foundation C.I.C.
#
# SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-Element-Commercial
# Please see LICENSE files in the repository root for full details.
#
# Originally licensed under the Apache License, Version 2.0:
# <http://www.apache.org/licenses/LICENSE-2.0>.
import asyncio
import json
from io import BytesIO
from threading import Condition
from typing import BinaryIO, Dict, List, Optional, Union

import attr
import twisted
from incremental import Version
from twisted.internet._resolver import SimpleResolverComplexifier
from twisted.internet.defer import ensureDeferred, fail, succeed
from twisted.internet.error import DNSLookupError
from twisted.internet.interfaces import IReactorPluggableNameResolver, IResolverSimple
from twisted.internet.testing import MemoryReactorClock
from twisted.trial import unittest
from twisted.web.http_headers import Headers
from twisted.web.server import Request
from zope.interface.declarations import implementer

from sygnal.sygnal import CONFIG_DEFAULTS, Sygnal, merge_left_with_defaults

from tests.asyncio_test_helpers import TimelessEventLoopWrapper

REQ_PATH = b"/_matrix/push/v1/notify"


class TestCase(unittest.TestCase):
    def config_setup(self, config):
        pass

    def setUp(self):
        reactor = ExtendedMemoryReactorClock()

        logging_config = {
            "setup": {
                "disable_existing_loggers": False,  # otherwise this breaks logging!
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

        config = {"apps": {}, "log": logging_config}

        self.loop: Union[asyncio.AbstractEventLoop, TimelessEventLoopWrapper] = (
            asyncio.new_event_loop()
        )
        self.config_setup(config)
        # Manually set the running loop after calling config_setup since self.loop
        # can be modified inside config_setup.
        # asyncio doesn't set this itself for some reason when calling `set_event_loop`.
        asyncio._set_running_loop(self.loop)

        config = merge_left_with_defaults(CONFIG_DEFAULTS, config)

        self.sygnal = Sygnal(config, reactor)  # type: ignore[arg-type]
        self.reactor = reactor

        start_deferred = ensureDeferred(self.sygnal.make_pushkins_then_start())

        while not start_deferred.called:
            # we need to advance until the pushkins have started up
            self.reactor.advance(1)
            self.reactor.wait_for_work(lambda: start_deferred.called)

        # sygnal should have started a single (fake) tcp listener
        listeners = self.reactor.tcpServers
        self.assertEqual(len(listeners), 1)
        (port, site, _backlog, interface) = listeners[0]
        self.site = site

    def _make_dummy_notification(self, devices):
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

    def _make_dummy_notification_event_id_only(self, devices):
        return {
            "notification": {
                "room_id": "!slw48wfj34rtnrf:example.com",
                "event_id": "$qTOWWTEL48yPm3uT-gdNhFcoHxfKbZuqRVnnWWSkGBs",
                "counts": {"unread": 2},
                "devices": devices,
            }
        }

    def _make_dummy_notification_badge_only(self, devices):
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
    def _make_dummy_notification_large_fields(self, devices):
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

    def _request(self, payload: Union[str, dict]) -> Union[dict, int]:
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
        content = BytesIO(payload.encode())

        channel = FakeChannel(self.site, self.sygnal.reactor)
        channel.process_request(b"POST", REQ_PATH, content)

        while not channel.done:
            # we need to advance until the request has been finished
            self.reactor.advance(1)
            self.reactor.wait_for_work(lambda: channel.done)

        assert channel.done
        assert channel.result is not None

        if channel.result.code != 200:
            return channel.result.code

        return json.loads(channel.response_body)

    def _multi_requests(
        self, payloads: List[Union[str, dict]]
    ) -> List[Union[dict, int]]:
        """
        Make multiple dummy requests to the notify endpoint with the specified payloads.

        Acts like a listified version of `_request`.

        Args:
            payloads: list of payloads to be JSON encoded

        Returns (lists of dicts and/or ints):
            If successful (200 response received), the response is JSON decoded
            and the resultant dict is returned.
            If the response code is not 200, returns the response code.
        """

        def dump_if_needed(payload):
            if isinstance(payload, dict):
                payload = json.dumps(payload)
            return payload

        contents = [BytesIO(dump_if_needed(payload).encode()) for payload in payloads]

        channels = [FakeChannel(self.site, self.sygnal.reactor) for _ in contents]

        for channel, content in zip(channels, contents):
            channel.process_request(b"POST", REQ_PATH, content)

        def all_channels_done():
            return all(channel.done for channel in channels)

        while not all_channels_done():
            # we need to advance until the request has been finished
            assert isinstance(self.sygnal.reactor, ExtendedMemoryReactorClock)
            self.sygnal.reactor.advance(1)
            self.sygnal.reactor.wait_for_work(all_channels_done)

        def channel_result(channel):
            if channel.result.code != 200:
                return channel.result.code
            else:
                return json.loads(channel.response_body)

        return [channel_result(channel) for channel in channels]


@implementer(IReactorPluggableNameResolver)
class ExtendedMemoryReactorClock(MemoryReactorClock):
    def __init__(self):
        super().__init__()
        self.work_notifier = Condition()

        self.lookups: Dict[str, str] = {}

        @implementer(IResolverSimple)
        class FakeResolver:
            @staticmethod
            def getHostByName(name, timeout=None):
                if name not in self.lookups:
                    return fail(DNSLookupError("OH NO: unknown %s" % (name,)))
                return succeed(self.lookups[name])

        self.nameResolver = SimpleResolverComplexifier(FakeResolver())

        # In order for the TLS protocol tests to work, modify _get_default_clock
        # on newer Twisted versions to use the test reactor's clock.
        #
        # This is *super* dirty since it is never undone and relies on the next
        # test to overwrite it.
        if twisted.version > Version("Twisted", 23, 8, 0):  # type: ignore[attr-defined]
            from twisted.protocols import tls

            tls._get_default_clock = lambda: self

    def installNameResolver(self, resolver):
        # It is not expected that this gets called.
        raise RuntimeError(resolver)

    def callFromThread(self, function, *args):
        self.callLater(0, function, *args)

    def callLater(self, when, what, *a, **kw):
        self.work_notifier.acquire()
        try:
            return_value = super().callLater(when, what, *a, **kw)
            self.work_notifier.notify_all()
        finally:
            self.work_notifier.release()

        return return_value

    def wait_for_work(self, early_stop=lambda: False):
        """
        Blocks until there is work as long as the early stop condition
        is not satisfied.

        Args:
            early_stop: Extra function called that determines whether to stop
                blocking.
                Should returns true iff the early stop condition is satisfied,
                in which case no blocking will be done.
                It is intended to be used to detect when the task you are
                waiting for is complete, e.g. a Deferred has fired or a
                Request has been finished.
        """
        self.work_notifier.acquire()

        try:
            while len(self.getDelayedCalls()) == 0 and not early_stop():
                self.work_notifier.wait()
        finally:
            self.work_notifier.release()


class DummyResponse:
    def __init__(self, code):
        self.code = code
        self.headers = Headers()


def make_async_magic_mock(ret_val):
    async def dummy(*_args, **_kwargs):
        return ret_val

    return dummy


@attr.s
class HTTPResult:
    """Holds the result data for FakeChannel"""

    version = attr.ib(type=str)
    code = attr.ib(type=int)
    reason = attr.ib(type=str)
    headers = attr.ib(type=Headers)


@attr.s
class FakeChannel:
    """
    A fake Twisted Web Channel (the part that interfaces with the
    wire).
    """

    site = attr.ib()
    _reactor = attr.ib()
    _producer = None

    result = attr.ib(type=Optional[HTTPResult], default=None)
    response_body = b""
    done = attr.ib(type=bool, default=False)

    @property
    def code(self):
        if not self.result:
            raise Exception("No result yet.")
        return int(self.result.code)

    def writeHeaders(self, version, code, reason, headers):
        self.result = HTTPResult(version, int(code), reason, headers)

    def write(self, content):
        assert isinstance(content, bytes), "Should be bytes! " + repr(content)
        self.response_body += content

    def requestDone(self, _self):
        self.done = True

    def getPeer(self):
        return None

    def getHost(self):
        return None

    @property
    def transport(self):
        return None

    def process_request(self, method: bytes, request_path: bytes, content: BinaryIO):
        """pretend that a request has arrived, and process it"""

        # this is normally done by HTTPChannel, in its various lineReceived etc methods
        req: Request = self.site.requestFactory(self)
        req.content = content
        req.requestReceived(method, request_path, b"1.1")
