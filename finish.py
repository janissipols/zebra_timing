
import json
import os
import tempfile
import threading
from datetime import datetime
from pathlib import Path

import paho.mqtt.client as mqtt

# --------------------------------------------------
# Configuration
# --------------------------------------------------
BROKER_HOST = "192.168.1.103"
BROKER_PORT = 1883
MQTT_TOPIC = "tag_data_events"
MQTT_USERNAME = ""
MQTT_PASSWORD = ""

OUTPUT_FILE = Path("registration.json")

file_lock = threading.Lock()


# --------------------------------------------------
# JSON file handling
# --------------------------------------------------
def load_records():
    """Load existing registration records."""
    if not OUTPUT_FILE.exists():
        return []

    try:
        with OUTPUT_FILE.open("r", encoding="utf-8") as file:
            records = json.load(file)

        if not isinstance(records, list):
            raise ValueError("JSON file must contain a list")

        return records

    except (json.JSONDecodeError, OSError, ValueError) as exc:
        raise RuntimeError(
            f"Cannot safely load {OUTPUT_FILE}: {exc}"
        ) from exc


def save_records(records):
    """Save JSON atomically."""
    temp_name = None

    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=OUTPUT_FILE.parent,
            delete=False,
        ) as file:
            temp_name = file.name
            json.dump(records, file, indent=2, ensure_ascii=False)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())

        os.replace(temp_name, OUTPUT_FILE)
        temp_name = None

    finally:
        if temp_name and os.path.exists(temp_name):
            os.unlink(temp_name)


# --------------------------------------------------
# Timestamp parsing
# --------------------------------------------------
def parse_timestamp(value):
    """
    Parse ISO timestamps, including:
    2026-10-25T16:37:08.234+0200
    2026-10-25T16:37:08.234+02:00
    2026-10-25T14:37:08.234Z
    """
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Timestamp is empty or invalid")

    value = value.strip()

    if value.endswith("Z"):
        value = value[:-1] + "+00:00"

    parsed = datetime.fromisoformat(value)

    # Comparisons require timezone-aware timestamps.
    if parsed.utcoffset() is None:
        raise ValueError("Timestamp must include a timezone offset")

    return parsed


# --------------------------------------------------
# MQTT connection callback
# --------------------------------------------------
def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code.is_failure:
        print(f"MQTT connection failed: {reason_code}")
        return

    print(f"Connected to {BROKER_HOST}:{BROKER_PORT}")

    result, _ = client.subscribe(MQTT_TOPIC, qos=1)

    if result == mqtt.MQTT_ERR_SUCCESS:
        print(f"Subscribed to {MQTT_TOPIC}")
    else:
        print(f"Subscription failed: {result}")


# --------------------------------------------------
# Process incoming events
# --------------------------------------------------

def on_message(client, userdata, message):
    # Print the complete received MQTT payload
    print("\n========== MQTT MESSAGE RECEIVED ==========")
    print(f"Topic: {message.topic}")
    print(message.payload.decode("utf-8", errors="replace"))
    print("===========================================\n")

    try:
        payload = json.loads(message.payload.decode("utf-8"))

        if not isinstance(payload, dict):
            print("Ignored: payload is not a JSON object")
            return

        data = payload.get("data")

        if not isinstance(data, dict):
            print("Ignored: missing data object")
            return

        # idHex is nested inside data; timestamp is at the top level
        id_hex = data.get("idHex")
        event_timestamp = payload.get("timestamp")

        if not isinstance(id_hex, str) or not id_hex.strip():
            print("Ignored: missing idHex")
            return

        id_hex = id_hex.strip()

        try:
            event_time = parse_timestamp(event_timestamp)
        except ValueError as exc:
            print(f"[UNKNOWN] ID={id_hex} | Ignored: invalid timestamp: {exc}")
            return

        with file_lock:
            records = load_records()

            record = next(
                (
                    item for item in records
                    if isinstance(item, dict)
                    and item.get("idHex") == id_hex
                ),
                None,
            )

            if record is None:
                print(f"[UNKNOWN] ID={id_hex} | Ignored: no registration")
                return

            name = record.get("name") or "(no name)"
            prefix = f"[{name}] ID={id_hex}"

            # Do not change a result that has already been set.
            if record.get("result") is not None:
                print(f"{prefix} | Ignored: result already exists")
                return

            start_time_value = record.get("start_time")

            if not start_time_value:
                print(f"{prefix} | Ignored: missing start_time")
                return

            try:
                start_time = parse_timestamp(start_time_value)
            except ValueError as exc:
                print(f"{prefix} | Ignored: invalid start_time: {exc}")
                return

            # Compare the event date in the start time's timezone.
            event_local = event_time.astimezone(start_time.tzinfo)

            if event_local.date() != start_time.date():
                print(f"{prefix} | Ignored: event is not on start date")
                return

            if event_time < start_time:
                print(
                    f"{prefix} | Ignored: event before start_time "
                    f"({event_timestamp} < {start_time_value})"
                )
                return

            # First eligible event sets the result permanently.
            record["result"] = event_timestamp
            save_records(records)

        print(
            f"{prefix} | RESULT SAVED: {event_timestamp}"
        )

    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        print(f"Invalid MQTT message: {exc}")

    except (OSError, RuntimeError) as exc:
        print(f"File error: {exc}")



# --------------------------------------------------
# Main application
# --------------------------------------------------
def main():
    with file_lock:
        load_records()

    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id="mqtt-result-collector",
        protocol=mqtt.MQTTv311,
    )

    if MQTT_USERNAME:
        client.username_pw_set(
            MQTT_USERNAME,
            MQTT_PASSWORD,
        )

    client.on_connect = on_connect
    client.on_message = on_message

    print(f"Connecting to {BROKER_HOST}:{BROKER_PORT}...")
    print(f"Reading and updating: {OUTPUT_FILE.resolve()}")

    try:
        client.connect(BROKER_HOST, BROKER_PORT, keepalive=60)
        client.loop_forever()

    except KeyboardInterrupt:
        print("\nStopping result collector...")

    except (OSError, RuntimeError) as exc:
        print(f"Application error: {exc}")

    finally:
        client.disconnect()
        print("Result collector stopped.")


if __name__ == "__main__":
    main()
