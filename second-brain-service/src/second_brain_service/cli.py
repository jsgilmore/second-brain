import argparse
import json
from typing import Optional

from second_brain_service.ingest.gmail_sync import parse_args as parse_gmail_args
from second_brain_service.ingest.gmail_sync import rehydrate_gmail_messages, run_sync_from_args
from second_brain_service.interfaces.http_api import serve_http
from second_brain_service.interfaces.remote_mcp import serve_remote_mcp
from second_brain_service.interfaces.stdio_mcp import serve_stdio_mcp
from second_brain_service.store.maintenance import apply_schema_scripts


def main(argv: Optional[list[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="Second-brain Gmail service")
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("serve-http")
    subcommands.add_parser("serve-stdio-mcp")
    subcommands.add_parser("serve-remote-mcp")
    subcommands.add_parser("apply-schema")
    rehydrate_parser = subcommands.add_parser("rehydrate-gmail")
    rehydrate_parser.add_argument("--limit", type=int)
    gmail_parser = subcommands.add_parser("gmail-sync")
    gmail_parser.add_argument("gmail_mode", choices=["backfill", "incremental"])
    gmail_parser.add_argument("--credentials", required=True)
    gmail_parser.add_argument("--token", required=True)
    gmail_parser.add_argument("--query")
    gmail_parser.add_argument("--label", action="append", default=[])
    gmail_parser.add_argument("--max-messages", type=int)
    gmail_parser.add_argument("--resume", action="store_true")
    gmail_parser.add_argument("--disable-embeddings", action="store_true")
    args = parser.parse_args(argv)

    if args.command == "serve-http":
        serve_http()
        return
    if args.command == "serve-stdio-mcp":
        serve_stdio_mcp()
        return
    if args.command == "serve-remote-mcp":
        serve_remote_mcp()
        return
    if args.command == "apply-schema":
        print(json.dumps(apply_schema_scripts(), default=str))
        return
    if args.command == "rehydrate-gmail":
        print(json.dumps(rehydrate_gmail_messages(limit=args.limit), default=str))
        return
    if args.command == "gmail-sync":
        gmail_args = parse_gmail_args(
            [
                args.gmail_mode,
                "--credentials",
                args.credentials,
                "--token",
                args.token,
                *sum([["--label", label] for label in args.label], []),
                *(["--query", args.query] if args.query else []),
                *(["--max-messages", str(args.max_messages)] if args.max_messages is not None else []),
                *(["--resume"] if args.resume else []),
                *(["--disable-embeddings"] if args.disable_embeddings else []),
            ]
        )
        print(json.dumps(run_sync_from_args(gmail_args), default=str))
        return
    raise SystemExit(1)


if __name__ == "__main__":
    main()
