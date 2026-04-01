# -*- coding: utf-8 -*-
# Copyright 2025 New Vector Ltd.
# Copyright 2019, 2020 The Matrix.org Foundation C.I.C.
# Copyright 2018, 2019 New Vector Ltd.
# Copyright 2014 OpenMarket Ltd.
#
# SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-Element-Commercial
# Please see LICENSE files in the repository root for full details.
#
# Originally licensed under the Apache License, Version 2.0:
# <http://www.apache.org/licenses/LICENSE-2.0>.
import asyncio
import copy
import importlib
import logging
import logging.config
import os
import sys
import traceback
from typing import Any, Dict, Set

import opentracing
import prometheus_client
import yaml
from aiohttp import web
from opentracing import Tracer
from opentracing.scope_managers.asyncio import AsyncioScopeManager

from sygnal.http import create_app
from sygnal.notifications import Pushkin

logger = logging.getLogger(__name__)

CONFIG_DEFAULTS: Dict[str, Any] = {
    "http": {"port": 5000, "bind_addresses": ["127.0.0.1"]},
    "log": {"setup": {}, "access": {"x_forwarded_for": False}},
    "metrics": {
        "prometheus": {"enabled": False, "address": "127.0.0.1", "port": 8000},
        "opentracing": {
            "enabled": False,
            "implementation": None,
            "jaeger": {},
            "service_name": "sygnal",
        },
        "sentry": {"enabled": False},
    },
    "proxy": None,
    "apps": {},
}


class Sygnal:
    def __init__(
        self,
        config: Dict[str, Any],
        tracer: Tracer = opentracing.tracer,
    ):
        """
        Object that holds state for the entirety of a Sygnal instance.
        Args:
            config: Configuration for this Sygnal
            tracer (optional): an OpenTracing tracer. The default is the no-op tracer.
        """
        self.config = config
        self.pushkins: Dict[str, Pushkin] = {}
        self.tracer = tracer

        logging_dict_config = config["log"]["setup"]
        logging.config.dictConfig(logging_dict_config)

        logger.debug("Started logging")

        proxy_url = config.get("proxy")
        if proxy_url is not None:
            logger.info("Using proxy configuration from Sygnal configuration file")
        else:
            proxy_url = os.getenv("HTTPS_PROXY")
            if proxy_url:
                logger.info(
                    "Using proxy configuration from HTTPS_PROXY environment variable."
                )
                config["proxy"] = proxy_url

        sentrycfg = config["metrics"]["sentry"]
        if sentrycfg["enabled"] is True:
            import sentry_sdk

            logger.info("Initialising Sentry")
            sentry_sdk.init(sentrycfg["dsn"])

        if config.get("db") is not None:
            logger.warning(
                "Config includes the legacy 'db' option and will be ignored"
                " as Sygnal no longer uses a database, this field can be removed"
            )

        if config.get("database") is not None:
            logger.warning(
                "Config includes the legacy 'database' option and will be ignored"
                " as Sygnal no longer uses a database, this field can be removed"
            )

        promcfg = config["metrics"]["prometheus"]
        if promcfg["enabled"] is True:
            prom_addr = promcfg["address"]
            prom_port = int(promcfg["port"])
            logger.info(
                "Starting Prometheus Server on %s port %d", prom_addr, prom_port
            )

            prometheus_client.start_http_server(port=prom_port, addr=prom_addr or "")

        tracecfg = config["metrics"]["opentracing"]
        if tracecfg["enabled"] is True:
            if tracecfg["implementation"] == "jaeger":
                try:
                    import jaeger_client

                    jaeger_cfg = jaeger_client.Config(
                        config=tracecfg["jaeger"],
                        service_name=tracecfg["service_name"],
                        scope_manager=AsyncioScopeManager(),
                    )

                    jaeger_tracer = jaeger_cfg.initialize_tracer()
                    assert jaeger_tracer is not None
                    self.tracer = jaeger_tracer

                    logger.info("Enabled OpenTracing support with Jaeger")
                except ModuleNotFoundError:
                    logger.critical(
                        "You have asked for OpenTracing with Jaeger but do not have"
                        " the Python package 'jaeger_client' installed."
                    )
                    raise
            else:
                raise RuntimeError(
                    "Unknown OpenTracing implementation: %s.", tracecfg["impl"]
                )

    async def _make_pushkin(self, app_name: str, app_config: Dict[str, Any]) -> Pushkin:
        """
        Load and instantiate a pushkin.
        Args:
            app_name: The pushkin's app_id
            app_config: The pushkin's configuration

        Returns:
            A pushkin of the desired type.
        """
        app_type = app_config["type"]
        if "." in app_type:
            kind_split = app_type.rsplit(".", 1)
            to_import = kind_split[0]
            to_construct = kind_split[1]
        else:
            to_import = f"sygnal.{app_type}pushkin"
            to_construct = f"{app_type.capitalize()}Pushkin"

        logger.info("Importing pushkin module: %s", to_import)
        pushkin_module = importlib.import_module(to_import)
        logger.info("Creating pushkin: %s", to_construct)
        clarse = getattr(pushkin_module, to_construct)
        return await clarse.create(app_name, self, app_config)

    async def _start(self) -> None:
        """Create pushkins and start the HTTP server."""
        for app_id, app_cfg in self.config["apps"].items():
            try:
                self.pushkins[app_id] = await self._make_pushkin(app_id, app_cfg)
            except Exception:
                logger.error(
                    "Failed to load and create pushkin for kind '%s'" % app_cfg["type"]
                )
                raise

        if len(self.pushkins) == 0:
            raise RuntimeError(
                "No app IDs are configured. Edit sygnal.yaml to define some."
            )

        logger.info("Configured with app IDs: %r", self.pushkins.keys())

        app = create_app(self)
        runner = web.AppRunner(app)
        await runner.setup()

        port = int(self.config["http"]["port"])
        for interface in self.config["http"]["bind_addresses"]:
            logger.info("Starting listening on %s port %d", interface, port)
            site = web.TCPSite(runner, interface, port)
            await site.start()

        # Wait forever (until cancelled)
        try:
            await asyncio.Event().wait()
        finally:
            await runner.cleanup()

    def run(self) -> None:
        """
        Attempt to run Sygnal and then exit the application.
        """
        try:
            asyncio.run(self._start())
        except KeyboardInterrupt:
            pass
        except Exception:
            print("Error during startup:", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
            sys.exit(1)


def parse_config() -> Dict[str, Any]:
    """
    Find and load Sygnal's configuration file.
    Returns:
        A loaded configuration.
    """
    config_path = os.getenv("SYGNAL_CONF", "sygnal.yaml")
    print("Using configuration file: %s" % config_path, file=sys.stderr)
    try:
        with open(config_path) as file_handle:
            return yaml.safe_load(file_handle)
    except FileNotFoundError:
        logger.critical(
            "Could not find configuration file!\nPath: %s\nAbsolute Path: %s",
            config_path,
            os.path.realpath(config_path),
        )
        raise


def check_config(config: Dict[str, Any]) -> None:
    """
    Lightly check the configuration and issue warnings as appropriate.
    Args:
        config: The loaded configuration.
    """
    UNDERSTOOD_CONFIG_FIELDS = CONFIG_DEFAULTS.keys()

    def check_section(
        section_name: str, known_keys: Set[str], cfgpart: Dict[str, Any] = config
    ) -> None:
        nonunderstood = set(cfgpart[section_name].keys()).difference(known_keys)
        if len(nonunderstood) > 0:
            logger.warning(
                f"The following configuration fields in '{section_name}' "
                f"are not understood: %s",
                nonunderstood,
            )

    nonunderstood = set(config.keys()).difference(UNDERSTOOD_CONFIG_FIELDS)
    if len(nonunderstood) > 0:
        logger.warning(
            "The following configuration sections are not understood: %s", nonunderstood
        )

    check_section("http", {"port", "bind_addresses"})
    check_section("log", {"setup", "access"})
    check_section(
        "access", {"file", "enabled", "x_forwarded_for"}, cfgpart=config["log"]
    )
    check_section("metrics", {"opentracing", "sentry", "prometheus"})
    check_section(
        "opentracing",
        {"enabled", "implementation", "jaeger", "service_name"},
        cfgpart=config["metrics"],
    )
    check_section(
        "prometheus", {"enabled", "address", "port"}, cfgpart=config["metrics"]
    )
    check_section("sentry", {"enabled", "dsn"}, cfgpart=config["metrics"])


def merge_left_with_defaults(
    defaults: Dict[str, Any], loaded_config: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Merge two configurations, with one of them overriding the other.
    Args:
        defaults: A configuration of defaults
        loaded_config: A configuration, as loaded from disk.

    Returns:
        A merged configuration, with loaded_config preferred over defaults.
    """
    result = defaults.copy()

    if loaded_config is None:
        return result

    # copy defaults or override them
    for k, v in result.items():
        if isinstance(v, dict):
            if k in loaded_config:
                result[k] = merge_left_with_defaults(v, loaded_config[k])
            else:
                result[k] = copy.deepcopy(v)
        elif k in loaded_config:
            result[k] = loaded_config[k]

    # copy things with no defaults
    for k, v in loaded_config.items():
        if k not in result:
            result[k] = v

    return result


def main() -> None:
    config = parse_config()
    config = merge_left_with_defaults(CONFIG_DEFAULTS, config)
    check_config(config)
    sygnal = Sygnal(config)
    sygnal.run()


if __name__ == "__main__":
    main()
