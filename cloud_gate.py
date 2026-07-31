from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parent
STATE_PATH = ROOT / "strategy" / "state.json"
SHANGHAI = ZoneInfo("Asia/Shanghai")
SCREENING_START = "15:35"


def read_last_trade_date(path: Path = STATE_PATH) -> str:
    if not path.exists():
        return ""
    try:
        return str(json.loads(path.read_text(encoding="utf-8")).get("last_trade_date", ""))
    except (OSError, ValueError, TypeError):
        return ""


def parse_tencent_trade_date(raw: str) -> str:
    match = re.search(r'v_sh000001="([^"]*)";', raw)
    if not match:
        return ""
    fields = match.group(1).split("~")
    timestamp = fields[30] if len(fields) > 30 else ""
    if len(timestamp) < 8 or not timestamp[:8].isdigit():
        return ""
    return datetime.strptime(timestamp[:8], "%Y%m%d").strftime("%Y-%m-%d")


def fetch_tencent_trade_date() -> str:
    request = Request(
        "https://qt.gtimg.cn/q=sh000001",
        headers={
            "Referer": "https://finance.qq.com/",
            "User-Agent": "Mozilla/5.0 (compatible; ali-stock-daily-picks/1.0)",
        },
    )
    with urlopen(request, timeout=10) as response:
        raw = response.read().decode("gbk", errors="replace")
    return parse_tencent_trade_date(raw)


def should_screen(
    now: datetime,
    last_trade_date: str,
    quote_trade_date: str,
    force: bool = False,
) -> tuple[bool, str]:
    local_now = (
        now.replace(tzinfo=SHANGHAI)
        if now.tzinfo is None
        else now.astimezone(SHANGHAI)
    )
    today = local_now.strftime("%Y-%m-%d")
    if force:
        return True, "manual force"
    if local_now.weekday() >= 5:
        return False, "weekend"
    if local_now.strftime("%H:%M") < SCREENING_START:
        return False, f"before {SCREENING_START} Asia/Shanghai"
    if last_trade_date == today:
        return False, f"{today} already published"
    if quote_trade_date and quote_trade_date != today:
        return False, f"market quote date is {quote_trade_date}, not {today}"
    return True, "new completed trading day"


def write_github_output(name: str, value: str) -> None:
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with Path(output).open("a", encoding="utf-8") as stream:
            stream.write(f"{name}={value}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Gate cloud close screening")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    now = datetime.now(SHANGHAI)
    last_trade_date = read_last_trade_date()
    quote_trade_date = ""
    if (
        not args.force
        and now.weekday() < 5
        and now.strftime("%H:%M") >= SCREENING_START
        and last_trade_date != now.strftime("%Y-%m-%d")
    ):
        try:
            quote_trade_date = fetch_tencent_trade_date()
        except Exception as exc:
            # 行情日期预检失败时仍运行完整扫描，避免因门禁接口短暂故障漏掉交易日。
            print(f"Trade-date preflight unavailable: {type(exc).__name__}: {exc}")

    run, reason = should_screen(
        now,
        last_trade_date,
        quote_trade_date,
        force=args.force,
    )
    write_github_output("run", "true" if run else "false")
    write_github_output("reason", reason)
    print(
        f"Close-screening gate: run={run}; reason={reason}; "
        f"last={last_trade_date or '-'}; quote={quote_trade_date or '-'}; "
        f"now={now:%Y-%m-%d %H:%M:%S}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
