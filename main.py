"""Entry point. Verifies configuration; bot wiring lands in Phase 1."""
from __future__ import annotations

import logging
import sys

from config.settings import SettingsError, get


def main() -> int:
    """Load settings, configure logging, print verification status."""
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
    logging.getLogger(__name__).info(cfg.verify())
    return 0


if __name__ == "__main__":
    sys.exit(main())
