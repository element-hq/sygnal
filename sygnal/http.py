# -*- coding: utf-8 -*-
# Copyright 2019-2025 New Vector Ltd.
# Copyright 2019 The Matrix.org Foundation C.I.C.
# Copyright 2014 OpenMarket Ltd.
#
# SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-Element-Commercial
# Please see LICENSE files in the repository root for full details.
#
# Originally licensed under the Apache License, Version 2.0:
# <http://www.apache.org/licenses/LICENSE-2.0>.
import json
import logging
import sys
import time
import traceback
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Awaitable, Callable, List
from uuid import uuid4

from aiohttp import web
from opentracing import Format, Span, logs, tags
from prometheus_client import Counter, Gauge, Histogram

from sygnal.exceptions import (
    InvalidNotificationException,
    NotificationDispatchException,
)
from sygnal.notifications import Notification, NotificationContext, Pushkin
from sygnal.utils import NotificationLoggerAdapter, json_decoder

if TYPE_CHECKING:
    from sygnal.sygnal import Sygnal

logger = logging.getLogger(__name__)

NOTIFS_RECEIVED_COUNTER = Counter(
    "sygnal_notifications_received", "Number of notification pokes received"
)

NOTIFS_RECEIVED_DEVICE_PUSH_COUNTER = Counter(
    "sygnal_notifications_devices_received", "Number of devices been asked to push"
)

NOTIFS_BY_PUSHKIN = Counter(
    "sygnal_per_pushkin_type",
    "Number of pushes sent via each type of pushkin",
    labelnames=["pushkin"],
)

PUSHGATEWAY_HTTP_RESPONSES_COUNTER = Counter(
    "sygnal_pushgateway_status_codes",
    "HTTP Response Codes given on the Push Gateway API",
    labelnames=["code"],
)

NOTIFY_HANDLE_HISTOGRAM = Histogram(
    "sygnal_notify_time",
    "Time taken to handle /notify push gateway request",
    labelnames=["code"],
)

REQUESTS_IN_FLIGHT_GUAGE = Gauge(
    "sygnal_requests_in_flight",
    "Number of HTTP requests in flight",
    labelnames=["resource"],
)

access_logger = logging.getLogger("sygnal.access")


def _make_request_id() -> str:
    """
    Generates a request ID, intended to be unique, for a request so it can
    be followed through logging.
    """
    return str(uuid4())


def find_pushkins(sygnal: "Sygnal", appid: str) -> List[Pushkin]:
    """Finds matching pushkins according to the appid.

    Args:
        sygnal: the Sygnal instance.
        appid: app identifier to search.

    Returns:
        list of `Pushkin`: If it finds a specific pushkin with
            the exact app id, immediately returns it.
            Otherwise returns possible pushkins.
    """
    if appid in sygnal.pushkins:
        return [sygnal.pushkins[appid]]

    return [
        pushkin for pushkin in sygnal.pushkins.values() if pushkin.handles_appid(appid)
    ]


async def _handle_dispatch(
    sygnal: "Sygnal",
    root_span: Span,
    log: NotificationLoggerAdapter,
    notif: Notification,
    context: NotificationContext,
) -> web.Response:
    """
    Handle the dispatch of notifications to devices, sequentially.

    Returns an aiohttp Response.
    """
    status_code = 200
    try:
        rejected = []

        for d in notif.devices:
            NOTIFS_RECEIVED_DEVICE_PUSH_COUNTER.inc()

            appid = d.app_id
            found_pushkins = find_pushkins(sygnal, appid)
            if len(found_pushkins) == 0:
                log.warning("Got notification for unknown app ID %s", appid)
                rejected.append(d.pushkey)
                continue

            if len(found_pushkins) > 1:
                log.warning("Got notification for an ambiguous app ID %s", appid)
                rejected.append(d.pushkey)
                continue

            pushkin = found_pushkins[0]
            log.debug("Sending push to pushkin %s for app ID %s", pushkin.name, appid)

            NOTIFS_BY_PUSHKIN.labels(pushkin.name).inc()

            result = await pushkin.dispatch_notification(notif, d, context)
            if not isinstance(result, list):
                raise TypeError("Pushkin should return list.")

            rejected += result

        body = json.dumps({"rejected": rejected})

        if rejected:
            log.info(
                "Successfully delivered notifications with %d rejected pushkeys",
                len(rejected),
            )

        return web.Response(text=body, content_type="application/json", status=200)
    except NotificationDispatchException:
        status_code = 502
        log.warning("Failed to dispatch notification.", exc_info=True)
        return web.Response(status=502)
    except Exception:
        status_code = 500
        log.error("Exception whilst dispatching notification.", exc_info=True)
        return web.Response(status=500)
    finally:
        PUSHGATEWAY_HTTP_RESPONSES_COUNTER.labels(code=status_code).inc()
        root_span.set_tag(tags.HTTP_STATUS_CODE, status_code)

        req_time = time.perf_counter() - context.start_time
        if req_time > 0:
            NOTIFY_HANDLE_HISTOGRAM.labels(code=status_code).observe(req_time)
        if not 200 <= status_code < 300:
            root_span.set_tag(tags.ERROR, True)
        root_span.finish()


async def handle_notify(request: web.Request) -> web.Response:
    """Handle POST /_matrix/push/v1/notify."""
    sygnal: "Sygnal" = request.app["sygnal"]

    request_id = _make_request_id()
    header_dict = {k: v for k, v in request.headers.items()}

    # extract OpenTracing scope from the HTTP headers
    span_ctx = sygnal.tracer.extract(Format.HTTP_HEADERS, header_dict)
    span_tags = {
        tags.SPAN_KIND: tags.SPAN_KIND_RPC_SERVER,
        "request_id": request_id,
    }

    root_span = sygnal.tracer.start_span(
        "pushgateway_v1_notify", child_of=span_ctx, tags=span_tags
    )

    # if this is True, we will not close the root_span at the end of this
    # function.
    root_span_accounted_for = False

    try:
        context = NotificationContext(request_id, root_span, time.perf_counter())
        log = NotificationLoggerAdapter(logger, {"request_id": request_id})

        try:
            raw_body = await request.read()
            body = json_decoder.decode(raw_body.decode("utf-8"))
        except Exception as exc:
            msg = "Expected JSON request body"
            log.warning(msg, exc_info=exc)
            root_span.log_kv({logs.EVENT: "error", "error.object": exc})
            return web.Response(text=msg, status=400)

        if "notification" not in body or not isinstance(body["notification"], dict):
            msg = "Invalid notification: expecting object in 'notification' key"
            log.warning(msg)
            root_span.log_kv({logs.EVENT: "error", "message": msg})
            return web.Response(text=msg, status=400)

        try:
            notif = Notification(body["notification"])
        except InvalidNotificationException as e:
            log.exception("Invalid notification")
            root_span.log_kv({logs.EVENT: "error", "error.object": e})
            return web.Response(text=str(e), status=400)

        if notif.event_id is not None:
            root_span.set_tag("event_id", notif.event_id)

        root_span.set_tag("has_content", notif.content is not None)

        NOTIFS_RECEIVED_COUNTER.inc()

        if len(notif.devices) == 0:
            msg = "No devices in notification"
            log.warning(msg)
            return web.Response(text=msg, status=400)

        root_span_accounted_for = True

        with REQUESTS_IN_FLIGHT_GUAGE.labels("notify").track_inprogress():
            return await _handle_dispatch(sygnal, root_span, log, notif, context)

    except Exception as exc_val:
        root_span.set_tag(tags.ERROR, True)

        trace = traceback.format_tb(sys.exc_info()[2])
        root_span.log_kv(
            {
                logs.EVENT: tags.ERROR,
                logs.MESSAGE: str(exc_val),
                logs.ERROR_OBJECT: exc_val,
                logs.ERROR_KIND: type(exc_val),
                logs.STACK: trace,
            }
        )
        raise
    finally:
        if not root_span_accounted_for:
            root_span.finish()


async def handle_health(request: web.Request) -> web.Response:
    """
    `/health` is used for automatic checking of whether the service is up.
    It should just return a blank 200 OK response.
    """
    return web.Response()


@web.middleware
async def access_log_middleware(
    request: web.Request,
    handler: Callable[[web.Request], Awaitable[web.StreamResponse]],
) -> web.StreamResponse:
    """Middleware that logs requests, skipping /health at INFO level."""
    response = await handler(request)

    is_health = request.path == "/health"
    log_level = logging.DEBUG if is_health else logging.INFO

    use_x_forwarded_for = request.app.get("use_x_forwarded_for", False)
    if use_x_forwarded_for:
        remote = request.headers.get("X-Forwarded-For", request.remote)
    else:
        remote = request.remote

    now = datetime.now(timezone.utc).strftime("%d/%b/%Y:%H:%M:%S %z")
    line = (
        f"{remote} - - [{now}] "
        f'"{request.method} {request.path} '
        f'HTTP/{request.version.major}.{request.version.minor}" '
        f"{response.status} {response.content_length or 0}"
    )
    access_logger.log(log_level, "Handled request: %s", line)

    return response


# Arbitrarily limited to 512 KiB.
MAX_REQUEST_SIZE = 512 * 1024


def create_app(sygnal: "Sygnal") -> web.Application:
    """Create and configure the aiohttp web application."""
    app = web.Application(
        middlewares=[access_log_middleware],
        client_max_size=MAX_REQUEST_SIZE,
    )
    app["sygnal"] = sygnal
    app["use_x_forwarded_for"] = sygnal.config["log"]["access"]["x_forwarded_for"]

    app.router.add_post("/_matrix/push/v1/notify", handle_notify)
    app.router.add_get("/health", handle_health)

    return app
