"""One-shot scrape-loop wake: sleep briefly then emit sentinel (re-armed each turn)."""
from __future__ import annotations

import argparse
import time

PROMPT = (
    "Continue maximizing prefer-pool website scrape: fix remaining L1/L2 gaps "
    "(TLS/WAF/flaky Exa domains), GitHub research if stuck, clarify unsolvable "
    "blockers, update evidence. Wake again immediately after finishing this tick. "
    "Stop only when user asks or capability plateaus with clarified blockers."
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--delay", type=float, default=3.0, help="seconds before wake")
    args = parser.parse_args()
    time.sleep(max(0.5, args.delay))
    print(f'AGENT_LOOP_WAKE_scrape {{"prompt":"{PROMPT}"}}', flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
