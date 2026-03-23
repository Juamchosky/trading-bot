from __future__ import annotations

import argparse
import csv
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_SCHEDULER_LOG_PATH = Path("paper_live_scheduler_log.csv")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Scheduler programable para ejecutar run_paper_live_bot.py en ciclos periodicos."
        )
    )
    parser.add_argument("--interval-minutes", type=float, default=60.0)
    parser.add_argument("--cycles", type=int, default=1)
    parser.add_argument(
        "--infinite",
        action="store_true",
        help="Si se pasa, ejecuta ciclos indefinidos e ignora --cycles.",
    )
    parser.add_argument("--scheduler-log-path", type=Path, default=DEFAULT_SCHEDULER_LOG_PATH)

    # Passthrough principal hacia run_paper_live_bot.py
    parser.add_argument("--symbol")
    parser.add_argument("--interval")
    parser.add_argument("--candle-count", type=int)
    parser.add_argument("--historical-offset", type=int)
    parser.add_argument("--initial-cash", type=float)
    parser.add_argument("--fee-rate", type=float)
    parser.add_argument("--log-path", type=Path)
    parser.add_argument("--state-path", type=Path)
    parser.add_argument(
        "--disable-state",
        action="store_true",
        help="Passthrough a run_paper_live_bot.py para no persistir estado.",
    )

    args = parser.parse_args()

    if args.interval_minutes <= 0:
        parser.error("--interval-minutes debe ser > 0.")
    if not args.infinite and args.cycles <= 0:
        parser.error("--cycles debe ser > 0 cuando no se usa --infinite.")

    return args


def ensure_scheduler_log_header(path: Path) -> None:
    if path.exists():
        return
    with path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(
            csv_file,
            fieldnames=[
                "cycle_number",
                "started_at",
                "finished_at",
                "status",
                "notes",
            ],
        )
        writer.writeheader()


def append_scheduler_log_row(
    path: Path,
    *,
    cycle_number: int,
    started_at: str,
    finished_at: str,
    status: str,
    notes: str,
) -> None:
    with path.open("a", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(
            csv_file,
            fieldnames=[
                "cycle_number",
                "started_at",
                "finished_at",
                "status",
                "notes",
            ],
        )
        writer.writerow(
            {
                "cycle_number": cycle_number,
                "started_at": started_at,
                "finished_at": finished_at,
                "status": status,
                "notes": notes,
            }
        )


def build_run_command(args: argparse.Namespace) -> list[str]:
    run_script_path = Path(__file__).with_name("run_paper_live_bot.py")
    command = [sys.executable, str(run_script_path)]

    passthrough_args = {
        "--symbol": args.symbol,
        "--interval": args.interval,
        "--candle-count": args.candle_count,
        "--historical-offset": args.historical_offset,
        "--initial-cash": args.initial_cash,
        "--fee-rate": args.fee_rate,
        "--log-path": args.log_path,
        "--state-path": args.state_path,
    }

    for key, value in passthrough_args.items():
        if value is None:
            continue
        command.extend([key, str(value)])

    if args.disable_state:
        command.append("--disable-state")

    return command


def compact_text(text: str, max_len: int = 260) -> str:
    normalized = " ".join(text.strip().split())
    if len(normalized) <= max_len:
        return normalized
    return normalized[: max_len - 3] + "..."


def run_cycle(command: list[str], cycle_number: int, scheduler_log_path: Path) -> int:
    started_at = utc_now_iso()
    started_dt = datetime.now(timezone.utc)
    print(f"[cycle {cycle_number}] started_at={started_at}")
    print(f"[cycle {cycle_number}] command={' '.join(command)}")

    status = "ok"
    notes = "completed"

    try:
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
        if completed.stdout:
            print(completed.stdout, end="" if completed.stdout.endswith("\n") else "\n")
        if completed.returncode != 0:
            status = "error"
            stderr_summary = compact_text(completed.stderr or "sin stderr")
            notes = f"returncode={completed.returncode}; stderr={stderr_summary}"
            if completed.stderr:
                print(
                    completed.stderr,
                    file=sys.stderr,
                    end="" if completed.stderr.endswith("\n") else "\n",
                )
        else:
            notes = "returncode=0"
    except Exception as exc:  # pragma: no cover
        status = "error"
        notes = f"exception={exc!r}"

    finished_at = utc_now_iso()
    finished_dt = datetime.now(timezone.utc)
    elapsed_seconds = (finished_dt - started_dt).total_seconds()

    print(f"[cycle {cycle_number}] finished_at={finished_at}")
    print(f"[cycle {cycle_number}] status={status} elapsed_seconds={elapsed_seconds:.1f}")

    append_scheduler_log_row(
        scheduler_log_path,
        cycle_number=cycle_number,
        started_at=started_at,
        finished_at=finished_at,
        status=status,
        notes=notes,
    )

    return 0 if status == "ok" else 1


def main() -> None:
    args = parse_args()
    ensure_scheduler_log_header(args.scheduler_log_path)

    command = build_run_command(args)
    cycle_number = 0
    error_count = 0

    print("Scheduler started")
    print(f"interval_minutes={args.interval_minutes}")
    print(f"mode={'infinite' if args.infinite else 'limited'}")
    if not args.infinite:
        print(f"cycles={args.cycles}")
    print(f"scheduler_log_csv={args.scheduler_log_path}")

    while True:
        cycle_number += 1
        cycle_start_monotonic = time.monotonic()

        cycle_exit_code = run_cycle(command, cycle_number, args.scheduler_log_path)
        if cycle_exit_code != 0:
            error_count += 1

        if not args.infinite and cycle_number >= args.cycles:
            break

        cycle_elapsed = time.monotonic() - cycle_start_monotonic
        sleep_seconds = max(0.0, args.interval_minutes * 60.0 - cycle_elapsed)
        print(f"[cycle {cycle_number}] next_in_seconds={sleep_seconds:.1f}")
        time.sleep(sleep_seconds)

    print(
        f"Scheduler finished: total_cycles={cycle_number} errors={error_count} "
        f"log={args.scheduler_log_path}"
    )


if __name__ == "__main__":
    main()
