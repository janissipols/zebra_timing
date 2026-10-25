
import csv
import json
import os
import tempfile
import time
from datetime import datetime
from pathlib import Path

# --------------------------------------------------
# Configuration
# --------------------------------------------------
JSON_FILE = Path("registration.json")
CSV_FILE = Path("registration.csv")
CHECK_INTERVAL = 1  # Seconds


# --------------------------------------------------
# Timestamp parsing
# --------------------------------------------------
def parse_timestamp(value):
    """Parse timezone-aware timestamps from registration.json."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Timestamp is empty or invalid")

    timestamp = value.strip()

    if timestamp.endswith("Z"):
        timestamp = timestamp[:-1] + "+00:00"

    parsed = datetime.fromisoformat(timestamp)

    if parsed.utcoffset() is None:
        raise ValueError("Timestamp must include a timezone offset")

    return parsed


# --------------------------------------------------
# Duration formatting
# --------------------------------------------------
def format_duration(delta):
    """Format duration as HH:MM:SS.mmm, including >24 hours."""
    total_ms = int(delta.total_seconds() * 1000)

    if total_ms < 0:
        raise ValueError("Result is earlier than start_time")

    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, milliseconds = divmod(remainder, 1000)

    return (
        f"{hours:02d}:{minutes:02d}:"
        f"{seconds:02d}.{milliseconds:03d}"
    )


# --------------------------------------------------
# Read JSON and prepare CSV rows
# --------------------------------------------------
def build_csv_rows():
    """Build CSV rows for records with a non-null result."""
    if not JSON_FILE.exists():
        print(f"Waiting for {JSON_FILE}...")
        return []

    with JSON_FILE.open("r", encoding="utf-8") as file:
        records = json.load(file)

    if not isinstance(records, list):
        raise ValueError("JSON file must contain a list of records")

    rows = []

    for record in records:
        if not isinstance(record, dict):
            continue

        result = record.get("result")

        # Export only records with a completed result.
        if result is None or result == "":
            continue

        name = record.get("name") or ""
        start_time_value = record.get("start_time")

        try:
            start_time = parse_timestamp(start_time_value)
            result_time = parse_timestamp(result)

            # Calculate duration using the original timestamps.
            elapsed = result_time - start_time

            if elapsed.total_seconds() < 0:
                print(f"Skipping {name}: result is before start_time")
                continue

            duration = format_duration(elapsed)

        except (ValueError, TypeError) as exc:
            print(f"Skipping {name}: invalid timestamp: {exc}")
            continue

        # Remove date and timezone from the CSV time fields.
        rows.append({
            "name": name,
            "start_time": start_time.strftime("%H:%M:%S.%f")[:-3],
            "result": result_time.strftime("%H:%M:%S.%f")[:-3],
            "time": duration,
        })

    rows.sort(key=lambda row: row["start_time"])
    return rows


# --------------------------------------------------
# Write CSV safely
# --------------------------------------------------
def write_csv(rows):
    """Atomically write the CSV report."""
    columns = ["name", "start_time", "result", "time"]
    temp_name = None

    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8-sig",
            newline="",
            dir=CSV_FILE.parent,
            delete=False,
        ) as file:
            temp_name = file.name

            writer = csv.DictWriter(
                file,
                fieldnames=columns,
            )
            writer.writeheader()
            writer.writerows(rows)

            file.flush()
            os.fsync(file.fileno())

        os.replace(temp_name, CSV_FILE)
        temp_name = None

    finally:
        if temp_name and os.path.exists(temp_name):
            os.unlink(temp_name)


# --------------------------------------------------
# Main monitoring loop
# --------------------------------------------------
def main():
    print(f"Monitoring JSON: {JSON_FILE.resolve()}")
    print(f"CSV output:      {CSV_FILE.resolve()}")
    print("Checking for updates every second.")
    print("Press Ctrl+C to stop.\n")

    last_report = None

    while True:
        try:
            rows = build_csv_rows()

            # Update the CSV only when the report changes.
            report = json.dumps(rows, ensure_ascii=False)

            if report != last_report:
                write_csv(rows)
                last_report = report

                print(
                    f"CSV updated: {len(rows)} completed record(s)"
                )

        except (
            OSError,
            json.JSONDecodeError,
            ValueError,
        ) as exc:
            print(f"Could not update report: {exc}")

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nCSV report generator stopped.")
