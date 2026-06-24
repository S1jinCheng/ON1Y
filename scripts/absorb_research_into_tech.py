"""Move misclassified items from 科研 (research) into 科技."""
from __future__ import annotations

import argparse
import logging

from on1y.adapters.sqlite_storage import get_storage
from on1y.auth.context import user_context
from on1y.taxonomy.absorb import absorb_from_theme

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(description="Reclassify research -> 科技 via LLM")
    parser.add_argument("--user-id", type=int, default=1)
    parser.add_argument("--source-slug", default="research")
    parser.add_argument("--target-slug", default="科技")
    parser.add_argument("--locale", default="zh")
    args = parser.parse_args()

    storage = get_storage()
    try:
        with user_context(args.user_id):
            source_id = storage.get_theme_id_by_slug(args.source_slug)
            target_id = storage.get_theme_id_by_slug(args.target_slug)
            if source_id is None or target_id is None:
                raise SystemExit(f"theme not found: source={args.source_slug} target={args.target_slug}")
            stats = absorb_from_theme(
                storage,
                target_theme_id=target_id,
                source_theme_id=source_id,
                locale=args.locale,
            )
    finally:
        storage.close()
    logger.info("Done: %s", stats)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
