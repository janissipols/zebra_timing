
# MQTT Tag Registration and Time Tracking

A Python application suite that receives tag events from a Mosquitto MQTT broker, registers people by their tag IDs, records start and finish timestamps, and automatically generates a CSV report containing calculated elapsed times.

## Project Overview

The project consists of three Python applications:

| File | Purpose |
|---|---|
| `registration.py` | Registers new tag IDs and assigns a person's name and start time. |
| `finish.py` | Listens for tag events and records the first eligible event timestamp as the result. |
| `registration_to_csv.py` | Calculates elapsed time and maintains a CSV report. |

### Data Flow

```text
              Mosquitto MQTT Broker
                 tag_data_events
                        |
            +-----------+-----------+
            |                       |
            v                       v
     registration.py             finish.py
            |                       |
            +-----------+-----------+
                        |
                        v
                registration.json
                        |
                        v
              registration_to_csv.py
                        |
                        v
                 registration.csv
```

## Requirements

- Python 3.9 or newer recommended
- A running Mosquitto MQTT broker
- Network connectivity to the broker
- Python package `paho-mqtt`

## Project Structure

```text
.
├── registration.py
├── finish.py
├── registration_to_csv.py
├── registration.json
├── registration.csv
└── README.md
```

The JSON and CSV files are created or updated by the applications. Run the applications from the project directory to ensure they use the intended files.

## Installation

Install the MQTT dependency:

```bash
python -m pip install "paho-mqtt>=2.0"
```

The CSV generator uses only Python's standard library.

### MQTT Configuration

Configure the broker settings in both `registration.py` and `finish.py`:

```python
BROKER_HOST = "192.168.1.103"
BROKER_PORT = 1883
MQTT_TOPIC = "tag_data_events"

MQTT_USERNAME = ""
MQTT_PASSWORD = ""
```

Replace these values with your broker's address and credentials.

Both applications subscribe to the same topic: `tag_data_events`.

## 1. registration.py — Tag Registration

### Purpose

Receives MQTT messages and registers new tag IDs with a person's name and start time.

### Features

- Subscribes to `tag_data_events`.
- Extracts `idHex` from `data.idHex`.
- Ignores duplicate IDs that already have a start time.
- Prompts for a person's name when a new ID is detected.
- Prompts for a start time in `HH:mm` format.
- Combines the entered time with the current local date and timezone.
- Updates an existing record if a duplicate ID has a missing `start_time`.
- Saves registrations to `registration.json`.

### Run

```bash
python registration.py
```

Keep the terminal open because the application requires interactive input.

### Example MQTT Message

```json
{
  "data": {
    "pc": "",
    "idHex": "A1B2C3D4",
    "timestamp": ""
  }
}
```

### Example Registration Record

```json
[
  {
    "idHex": "A1B2C3D4",
    "name": "John Smith",
    "start_time": "2026-10-25T16:37:00.000+0200",
    "result": null
  }
]
```

## 2. finish.py — Finish Event Tracking

### Purpose

Listens for tag events and records the first eligible event timestamp as the result for a registered person.

### Features

- Subscribes to `tag_data_events`.
- Prints the complete received MQTT payload for debugging.
- Extracts `idHex` from `data.idHex`.
- Extracts `timestamp` from the top-level JSON field `timestamp`.
- Finds the matching registration in `registration.json`.
- Ignores unknown IDs and invalid timestamps.
- Ignores events occurring before `start_time`.
- Ignores events on a different calendar date from the registered start time.
- Saves the first eligible event timestamp to `result`.
- Does not overwrite an existing non-null result.

### Run

```bash
python finish.py
```

### Example MQTT Message

```json
{
  "data": {
    "pc": "",
    "idHex": "A1B2C3D4"
  },
  "timestamp": "2026-10-25T16:45:12.500+0200"
}
```

If the registered start time is `16:37:00`, the event is eligible.

The corresponding JSON record becomes:

```json
{
  "idHex": "A1B2C3D4",
  "name": "John Smith",
  "start_time": "2026-10-25T16:37:00.000+0200",
  "result": "2026-10-25T16:45:12.500+0200"
}
```

Subsequent events for this record are ignored once `result` has been set.

## 3. registration_to_csv.py — CSV Report Generator

### Purpose

Monitors `registration.json`, calculates elapsed times, and maintains `registration.csv`.

### Calculation

The elapsed duration is calculated as:

```text
time = result - start_time
```

### Features

- Checks `registration.json` every second.
- Exports only records where `result` is present and not `null`.
- Calculates elapsed duration using the full timestamps, including timezone offsets.
- Removes the date and timezone from the CSV `start_time` and `result` columns.
- Formats elapsed time as `HH:MM:SS.mmm`.
- Supports durations longer than 24 hours.
- Updates the CSV when the report content changes.

### Run

```bash
python registration_to_csv.py
```

Keep the application running to maintain the report automatically.

### Example CSV Output

```csv
name,start_time,result,time
John Smith,16:37:00.000,16:45:12.500,00:08:12.500
```

The `time` column contains the calculated elapsed duration. Records with `result: null` are excluded until a finish event is recorded.

## Recommended Startup Procedure

Run each application in a separate terminal window from the project directory.

**Terminal 1 — Registration**

```bash
python registration.py
```

**Terminal 2 — Finish Event Tracking**

```bash
python finish.py
```

**Terminal 3 — CSV Report**

```bash
python registration_to_csv.py
```

Ensure the Mosquitto broker is running before starting the applications.

## Data Files

### registration.json

Stores registration and event data.

| Field | Description |
|---|---|
| `idHex` | Tag identifier |
| `name` | Person's name |
| `start_time` | Registered start timestamp |
| `result` | First eligible finish timestamp, or `null` |

Timestamps use this format:

```text
YYYY-MM-DDTHH:mm:ss.SSS+ZZZZ
```

Example:

```text
2026-10-25T16:37:00.000+0200
```

### registration.csv

Contains the calculated report with four columns:

| Column | Description |
|---|---|
| `name` | Person's name |
| `start_time` | Start time without date or timezone |
| `result` | Finish time without date or timezone |
| `time` | Elapsed duration |

## Troubleshooting

### MQTT Connection Fails

- Verify that Mosquitto is running.
- Check the broker IP address and port.
- Verify network connectivity and firewall rules.
- Confirm the MQTT credentials if authentication is enabled.

### No Messages Are Received

- Verify that the topic is exactly `tag_data_events`.
- Check that `idHex` is inside `data`.
- For `finish.py`, verify that `timestamp` is at the top level of the JSON payload.

### A Result Is Not Recorded

- Confirm that the ID exists in `registration.json`.
- Verify that `start_time` contains a valid timezone-aware timestamp.
- Check that the event timestamp is on the same date and is not earlier than `start_time`.
- Review the debug output from `finish.py`.

### The CSV Is Empty

- Verify that `registration.json` contains records with non-null results.
- Check for invalid timestamps or results earlier than start times.
- Ensure `registration_to_csv.py` is running from the correct directory.

## Important Considerations

- **Shared JSON file:** Both `registration.py` and `finish.py` modify `registration.json`. Their thread locks do not coordinate between separate processes. For reliable operation, use a shared inter-process file lock or centralize JSON writes to avoid concurrent-write conflicts.
- **Single result:** `finish.py` records the first eligible event and does not overwrite an existing result.
- **Same-day restriction:** Finish events must be on the same calendar date as the registered start time, interpreted in the start time's timezone.
- **Timezone:** Ensure the computer's local timezone is configured correctly.
- **Backups:** Back up `registration.json` regularly.

## License

Add a license appropriate for your project before publishing it publicly.
```

