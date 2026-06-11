"""Entry point: load settings, configure logging, start the Telegram bot."""

from __future__ import annotations

import logging
import sys

from bot.handler import build_application
from config.settings import SettingsError, get


def main() -> int:
    """Boot the bot in long-polling mode; return non-zero on config error."""
    try:
        cfg = get()
    except SettingsError as exc:
        logging.basicConfig(level=logging.ERROR)
        logging.getLogger(__name__).error("Configuration error: %s", exc)
        return 1

    logging.basicConfig(
        level=cfg.log_level,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    log = logging.getLogger(__name__)
    log.info(cfg.verify())

    app = build_application(cfg)
    log.info("starting Telegram long-polling")
    app.run_polling()
    return 0


if __name__ == "__main__":
    sys.exit(main())
