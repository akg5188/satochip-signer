#!/usr/bin/env python

import argparse
import logging
import os
import sys

from seedsigner.controller import Controller
from seedsigner.views.view import Destination

logger = logging.getLogger(__name__)

DEFAULT_MODULE_LOG_LEVELS = {
    "PIL": logging.WARNING,
    # "seedsigner.gui.toast": logging.DEBUG,  # example of more specific submodule logging config
}


def main(sys_argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-l",
        "--loglevel",
        choices=list((logging._nameToLevel.keys())),
        default="INFO",
        type=str,
        help=(
            "Set the log level (default: %(default)s), WARNING: changing the log level "
            "to something more verbose than %(default)s may result in unwanted data "
            "being written to stderr"
        ),
    )
    parser.add_argument(
        "--iotest",
        action="store_true",
        help="Launch directly into the I/O test screen",
    )

    args = parser.parse_args(sys_argv)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.getLevelName(args.loglevel))
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)8s [%(name)s %(funcName)s (%(lineno)d)]: %(message)s")
    )
    root_logger.addHandler(console_handler)

    # Set log levels for specific modules
    for module, level in DEFAULT_MODULE_LOG_LEVELS.items():
        logging.getLogger(module).setLevel(level)

    logger.info(f"Starting SeedSigner with: {args.__dict__}")

    # Keep the device in the trimmed offline-signer runtime to avoid the broader
    # SeedSigner UI path that is unstable on this customized image.
    offline_signer_mode = True
    initial_destination = None
    if args.iotest:
        from seedsigner.views.settings_views import IOTestView

        initial_destination = Destination(IOTestView)
        offline_signer_mode = False
    else:
        os.environ["OFFLINE_SIGNER_MODE"] = "1"
        # Compatibility: many customized views still use the historical TP_ONLY_MODE key.
        os.environ["TP_ONLY_MODE"] = "1"
        from seedsigner.views.tp_views import ToolsTpUiLockView

        initial_destination = Destination(ToolsTpUiLockView, clear_history=True)

    Controller.get_instance().start(
        initial_destination=initial_destination,
        skip_startup_interstitials=(args.iotest or offline_signer_mode),
    )


if __name__ == "__main__":
    main(sys.argv[1:])
