from __future__ import annotations

import argparse
import logging

from rich.logging import RichHandler

from stockcheck.runner import build_service


def configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(message)s",
        handlers=[RichHandler(rich_tracebacks=True)],
    )


def main() -> None:
    parser = argparse.ArgumentParser(prog="stockcheck")
    parser.add_argument("--verbose", action="store_true")

    sub = parser.add_subparsers(dest="command", required=True)

    for cmd in ("run", "once"):
        p = sub.add_parser(cmd)
        p.add_argument("--config", required=True)
        p.add_argument("--dry-run", action="store_true")
        p.add_argument("--headed", action="store_true", help="show browser for Playwright adapters")

    web = sub.add_parser("web")
    web.add_argument("--host", default="0.0.0.0")
    web.add_argument("--port", type=int, default=8000)

    args = parser.parse_args()
    configure_logging(args.verbose)

    if args.command == "web":
        import uvicorn

        uvicorn.run("stockcheck.api:app", host=args.host, port=args.port, reload=False)
        return

    service = build_service(
        config_path=args.config,
        dry_run=args.dry_run,
        headless=not args.headed,
    )

    if args.command == "once":
        service.run_once()
        return

    if args.command == "run":
        service.run_forever()
        return

    raise RuntimeError(f"unsupported command: {args.command}")


if __name__ == "__main__":
    main()
