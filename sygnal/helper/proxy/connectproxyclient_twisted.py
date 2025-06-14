# Copyright 2025 New Vector Ltd.
# Copyright 2019, 2020 The Matrix.org Foundation C.I.C.
#
# SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-Element-Commercial
# Please see LICENSE files in the repository root for full details.
#
# Originally licensed under the Apache License, Version 2.0:
# <http://www.apache.org/licenses/LICENSE-2.0>.

# Adapted from Synapse:
# https://github.com/element-hq/synapse/blob/6920e58136671f086536332bdd6844dff0d4b429/synapse/http/connectproxyclient.py

import logging
from base64 import urlsafe_b64encode
from typing import Optional, Tuple

from twisted.internet import defer, protocol
from twisted.internet.base import ReactorBase
from twisted.internet.defer import Deferred
from twisted.internet.interfaces import (
    IAddress,
    IConnector,
    IProtocol,
    IProtocolFactory,
    IStreamClientEndpoint,
)
from twisted.internet.protocol import Protocol, connectionDone
from twisted.python.failure import Failure
from twisted.web import http
from zope.interface import implementer

from sygnal.exceptions import ProxyConnectError

logger = logging.getLogger(__name__)


@implementer(IStreamClientEndpoint)
class HTTPConnectProxyEndpoint:
    """An Endpoint implementation which will send a CONNECT request to an http proxy

    Wraps an existing HostnameEndpoint for the proxy.

    When we get the connect() request from the connection pool (via the TLS wrapper),
    we'll first connect to the proxy endpoint with a ProtocolFactory which will make the
    CONNECT request. Once that completes, we invoke the protocolFactory which was passed
    in.

    Args:
        reactor: the Twisted reactor to use for the connection
        proxy_endpoint: the endpoint to use to connect to the proxy
        host: hostname that we want to CONNECT to
        port: port that we want to connect to
        proxy_auth: None or tuple of (username, pasword) for HTTP basic proxy
            authentication
    """

    def __init__(
        self,
        reactor: ReactorBase,
        proxy_endpoint: IStreamClientEndpoint,
        host: bytes,
        port: int,
        proxy_auth: Optional[Tuple[str, str]],
    ):
        self._reactor = reactor
        self._proxy_endpoint = proxy_endpoint
        self._host = host
        self._port = port
        self._proxy_auth = proxy_auth

    def __repr__(self) -> str:
        return "<HTTPConnectProxyEndpoint %s>" % (self._proxy_endpoint,)

    def connect(self, protocolFactory: IProtocolFactory) -> "defer.Deferred[IProtocol]":
        assert isinstance(protocolFactory, protocol.ClientFactory)
        f = HTTPProxiedClientFactory(
            self._host, self._port, self._proxy_auth, protocolFactory
        )
        d = self._proxy_endpoint.connect(f)
        # once the tcp socket connects successfully, we need to wait for the
        # CONNECT to complete.
        d.addCallback(lambda conn: f.on_connection)
        return d


class HTTPProxiedClientFactory(protocol.ClientFactory):
    """ClientFactory wrapper that triggers an HTTP proxy CONNECT on connect.

    It invokes the original ClientFactory to build the HTTP Protocol object,
     and then, once CONNECT is completed, uses it to run the rest of the
     connection.

    Args:
        dst_host: hostname that we want to CONNECT to
        dst_port: port that we want to connect to
        proxy_auth: None or tuple of (username, pasword) for HTTP basic proxy
            authentication
        wrapped_factory: The original Factory
    """

    def __init__(
        self,
        dst_host: bytes,
        dst_port: int,
        proxy_auth: Optional[Tuple[str, str]],
        wrapped_factory: protocol.ClientFactory,
    ):
        self.dst_host = dst_host
        self.dst_port = dst_port
        self._proxy_auth = proxy_auth
        self.wrapped_factory = wrapped_factory
        self.on_connection: defer.Deferred = defer.Deferred()

    def startedConnecting(self, connector: IConnector) -> None:
        return self.wrapped_factory.startedConnecting(connector)

    def buildProtocol(self, addr: IAddress) -> "HTTPConnectProtocol":
        wrapped_protocol = self.wrapped_factory.buildProtocol(addr)
        assert wrapped_protocol is not None

        return HTTPConnectProtocol(
            self.dst_host,
            self.dst_port,
            self._proxy_auth,
            wrapped_protocol,
            self.on_connection,
        )

    def clientConnectionFailed(self, connector: IConnector, reason: Failure) -> None:
        logger.debug("Connection to proxy failed: %s", reason)
        if not self.on_connection.called:
            self.on_connection.errback(reason)
        return self.wrapped_factory.clientConnectionFailed(connector, reason)

    def clientConnectionLost(self, connector: IConnector, reason: Failure) -> None:
        logger.debug("Connection to proxy lost: %s", reason)
        if not self.on_connection.called:
            self.on_connection.errback(reason)
        return self.wrapped_factory.clientConnectionLost(connector, reason)


class HTTPConnectProtocol(protocol.Protocol):
    """Protocol that wraps an existing Protocol to do a CONNECT handshake at connect

    Args:
        host: The original HTTP(s) hostname or IPv4 or IPv6 address literal
            to put in the CONNECT request

        port: The original HTTP(s) port to put in the CONNECT request

        proxy_auth: None or tuple of (username, pasword) for HTTP basic proxy
            authentication

        wrapped_protocol: the original protocol (probably
            HTTPChannel or TLSMemoryBIOProtocol, but could be anything really)

        connected_deferred: a Deferred which will be callbacked with
            wrapped_protocol when the CONNECT completes
    """

    def __init__(
        self,
        host: bytes,
        port: int,
        proxy_auth: Optional[Tuple[str, str]],
        wrapped_protocol: Protocol,
        connected_deferred: Deferred,
    ):
        self.host = host
        self.port = port
        self.wrapped_protocol = wrapped_protocol
        self.connected_deferred = connected_deferred
        self.http_setup_client = HTTPConnectSetupClient(
            self.host, self.port, proxy_auth
        )
        self.http_setup_client.on_connected.addCallback(self.proxyConnected)

    def connectionMade(self) -> None:
        self.http_setup_client.makeConnection(self.transport)

    def connectionLost(self, reason: Failure = connectionDone) -> None:
        if self.wrapped_protocol.connected:
            self.wrapped_protocol.connectionLost(reason)

        self.http_setup_client.connectionLost(reason)

        if not self.connected_deferred.called:
            self.connected_deferred.errback(reason)

    def proxyConnected(self, _: Optional["defer.Deferred[None]"]) -> None:
        self.wrapped_protocol.makeConnection(self.transport)

        self.connected_deferred.callback(self.wrapped_protocol)

        # Get any pending data from the http buf and forward it to the original protocol
        buf = self.http_setup_client.clearLineBuffer()
        if buf:
            self.wrapped_protocol.dataReceived(buf)

    def dataReceived(self, data: bytes) -> None:
        # if we've set up the HTTP protocol, we can send the data there
        if self.wrapped_protocol.connected:
            return self.wrapped_protocol.dataReceived(data)

        # otherwise, we must still be setting up the connection: send the data to the
        # setup client
        return self.http_setup_client.dataReceived(data)


class HTTPConnectSetupClient(http.HTTPClient):
    """HTTPClient protocol to send a CONNECT message for proxies and read the response.

    Args:
        host: The hostname to send in the CONNECT message
        port: The port to send in the CONNECT message
        proxy_auth: None or tuple of (username, pasword) for HTTP basic proxy
            authentication
    """

    def __init__(self, host: bytes, port: int, proxy_auth: Optional[Tuple[str, str]]):
        self.host = host
        self.port = port
        self._proxy_auth = proxy_auth
        self.on_connected: defer.Deferred = defer.Deferred()

    def connectionMade(self) -> None:
        logger.debug("Connected to proxy, sending CONNECT")
        self.sendCommand(b"CONNECT", b"%s:%d" % (self.host, self.port))
        if self._proxy_auth is not None:
            username, password = self._proxy_auth
            # a credential pair is a urlsafe-base64-encoded pair separated by colon
            encoded_credentials = urlsafe_b64encode(f"{username}:{password}".encode())
            self.sendHeader(b"Proxy-Authorization", b"basic " + encoded_credentials)
        self.endHeaders()

    def handleStatus(self, version: bytes, status: bytes, message: bytes) -> None:
        logger.debug("Got Status: %s %s %s", status, message, version)
        if status != b"200":
            raise ProxyConnectError(f"Unexpected status on CONNECT: {status!s}")

    def handleEndHeaders(self) -> None:
        logger.debug("End Headers")
        self.on_connected.callback(None)

    def handleResponse(self, body: bytes) -> None:
        pass
