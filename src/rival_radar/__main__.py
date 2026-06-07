import argparse
import json
import sys

from dotenv import load_dotenv

load_dotenv()

from rival_radar.database import SessionLocal, init_db  # noqa: E402
from rival_radar.models import Competitor  # noqa: E402
from rival_radar.nodes.scraper import scraper  # noqa: E402
from rival_radar.state import MonitorState  # noqa: E402


def cmd_scrape(args: argparse.Namespace) -> None:
    init_db()
    with SessionLocal() as db:
        comp = Competitor(
            name=args.name or args.url,
            urls=json.dumps([args.url]),
        )
        db.add(comp)
        db.flush()

        state = MonitorState(
            competitors=[{"competitor_id": comp.id, "name": comp.name, "urls": [args.url]}],
            diffs={},
            analyses=[],
            brief="",
            run_id=0,
        )
        result = scraper(state)
        db.commit()

    print("\nRival Radar — Scrape Results")
    print("=" * 60)
    for url, diff in result["diffs"].items():
        print(f"\nCompetitor : {diff['competitor']}")
        print(f"URL        : {url}")
        print(f"Changed    : {diff['changed']}")
        if diff.get("old_excerpt", "").startswith("error:"):
            print(f"Error      : {diff['old_excerpt']}")
        elif diff["changed"]:
            print(f"\nPrevious excerpt:\n{diff['old_excerpt'] or '(first run)'}")
            print(f"\nCurrent excerpt:\n{diff['new_excerpt']}")
        else:
            print("No changes detected since last run.")


def cmd_run(args: argparse.Namespace) -> None:
    from rival_radar.graph import app  # imported here to avoid loading LLM on scrape-only calls

    init_db()
    urls = [u.strip() for u in args.urls.split(",")]

    with SessionLocal() as db:
        comp = Competitor(
            name=args.name,
            urls=json.dumps(urls),
        )
        db.add(comp)
        db.flush()

        state = MonitorState(
            competitors=[{"competitor_id": comp.id, "name": args.name, "urls": urls}],
            diffs={},
            analyses=[],
            brief="",
            run_id=0,
        )
        result = app.invoke(state)
        db.commit()

    print("\n" + "=" * 60)
    print(result["brief"])
    print("=" * 60)


def main() -> None:
    parser = argparse.ArgumentParser(prog="rival-radar", description="Rival Radar CLI")
    sub = parser.add_subparsers(dest="command")

    scrape_p = sub.add_parser("scrape", help="Scrape a URL and show diff vs last run")
    scrape_p.add_argument("--url", required=True, help="URL to scrape")
    scrape_p.add_argument("--name", default=None, help="Competitor name (defaults to URL)")

    run_p = sub.add_parser("run", help="Run full pipeline: scrape → analyze → write Slack brief")
    run_p.add_argument("--name", required=True, help="Competitor name")
    run_p.add_argument("--urls", required=True, help="Comma-separated URLs to monitor")

    args = parser.parse_args()
    if args.command == "scrape":
        cmd_scrape(args)
    elif args.command == "run":
        cmd_run(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
