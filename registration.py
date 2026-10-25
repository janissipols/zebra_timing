
import json
import os
import tempfile
import threading
from pathlib import Path
from queue import Queue
from datetime import datetime

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

# --------------------------------------------------
# Thread-safe message handling
# --------------------------------------------------
file_lock = threading.Lock()
message_queue = Queue()


# --------------------------------------------------
# Load existing registrations
# --------------------------------------------------
def load_records():
    """Load existing records from the JSON file."""
    if not OUTPUT_FILE.exists():
        return []

    try:
        with OUTPUT_FILE.open("r", encoding="utf-8") as file:
            data = json.load(file)

        if not isinstance(data, list):
            raise ValueError(
                "JSON file must contain a list of records"
            )

        return data

    except (json.JSONDecodeError, OSError, ValueError) as exc:
        raise RuntimeError(
            f"Cannot safely load {OUTPUT_FILE}: {exc}"
        ) from exc


# --------------------------------------------------
# Save registrations safely
# --------------------------------------------------
def save_records(records):
    """Atomically save records to the JSON file."""
    temp_name = None

    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=OUTPUT_FILE.parent,
            delete=False,
        ) as file:
            temp_name = file.name
            json.dump(
                records,
                file,
                indent=2,
                ensure_ascii=False,
            )
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())

        os.replace(temp_name, OUTPUT_FILE)
        temp_name = None

    finally:
        if temp_name and os.path.exists(temp_name):
            os.unlink(temp_name)


# --------------------------------------------------
# Format start time
# --------------------------------------------------
def get_start_time():
    """Prompt for HH:mm and return a local timestamp."""
    while True:
        time_input = input(
            "Enter start time (HH:mm): "
        ).strip()

        try:
            parsed_time = datetime.strptime(
                time_input, "%H:%M"
            ).time()

            now = datetime.now().astimezone()

            start_datetime = now.replace(
                hour=parsed_time.hour,
                minute=parsed_time.minute,
                second=0,
                microsecond=0,
            )

            return (
                start_datetime.strftime("%Y-%m-%dT%H:%M:%S")
                + f".{start_datetime.microsecond // 1000:03d}"
                + start_datetime.strftime("%z")
            )

        except ValueError:
            print("Invalid time. Enter HH:mm, e.g. 16:37.")


# --------------------------------------------------
# MQTT connection callback
# --------------------------------------------------
def on_connect(client, userdata, flags, reason_code, properties):
    """Subscribe to the MQTT topic after connecting."""
    if reason_code.is_failure:
        print(f"MQTT connection failed: {reason_code}")
        return

    print(f"Connected to {BROKER_HOST}:{BROKER_PORT}")

    result, _ = client.subscribe(MQTT_TOPIC, qos=1)

    if result == mqtt.MQTT_ERR_SUCCESS:
        print(f"Subscribed to topic: {MQTT_TOPIC}")
    else:
        print(f"Subscription request failed: {result}")


# --------------------------------------------------
# MQTT message callback
# --------------------------------------------------
def on_message(client, userdata, message):
    """Extract ID and queue it for processing."""
    try:
        payload = json.loads(
            message.payload.decode("utf-8")
        )

        if not isinstance(payload, dict):
            print("Ignoring message: expected a JSON object")
            return

        data = payload.get("data")

        if not isinstance(data, dict):
            print("Ignoring message: missing or invalid 'data'")
            return

        id_hex = data.get("idHex")

        if not isinstance(id_hex, str) or not id_hex.strip():
            print("Ignoring message: missing or invalid idHex")
            return

        message_queue.put({
            "idHex": id_hex.strip(),
        })

    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        print(f"Invalid MQTT JSON payload: {exc}")


# --------------------------------------------------
# Process new IDs and duplicates
# --------------------------------------------------
def process_messages():
    """Register new IDs or fill in missing start times."""
    while True:
        item = message_queue.get()

        try:
            id_hex = item["idHex"]

            with file_lock:
                records = load_records()

                existing_record = next(
                    (
                        record for record in records
                        if isinstance(record, dict)
                        and record.get("idHex") == id_hex
                    ),
                    None,
                )

            # ------------------------------------------
            # Duplicate ID
            # ------------------------------------------
            if existing_record is not None:
                if existing_record.get("start_time"):
                    print(f"\nDuplicate ignored: {id_hex}")
                    continue

                print(
                    f"\nExisting ID has no start_time: {id_hex}"
                )

                start_time = get_start_time()

                with file_lock:
                    # Reload before updating to preserve changes.
                    records = load_records()

                    current_record = next(
                        (
                            record for record in records
                            if isinstance(record, dict)
                            and record.get("idHex") == id_hex
                        ),
                        None,
                    )

                    if current_record is None:
                        print(
                            f"Record disappeared before update: {id_hex}"
                        )
                        continue

                    if current_record.get("start_time"):
                        print(
                            f"start_time already exists for {id_hex}"
                        )
                        continue

                    current_record["start_time"] = start_time
                    save_records(records)

                print(f"Updated start_time for {id_hex}")
                print(f"Start time: {start_time}")
                continue

            # ------------------------------------------
            # New ID
            # ------------------------------------------
            print(f"\nNew ID detected: {id_hex}")

            while True:
                try:
                    name = input(
                        f"Enter person's name for {id_hex}: "
                    ).strip()
                except EOFError:
                    print("\nNo terminal input available.")
                    return

                if name:
                    break

                print("Name cannot be empty. Please try again.")

            try:
                start_time = get_start_time()
            except EOFError:
                print("\nNo terminal input available.")
                return

            record = {
                "idHex": id_hex,
                "name": name,
                "start_time": start_time,
                "result": None,
            }

            with file_lock:
                # Check again before appending.
                records = load_records()

                duplicate = any(
                    isinstance(entry, dict)
                    and entry.get("idHex") == id_hex
                    for entry in records
                )

                if duplicate:
                    print(f"Duplicate ignored: {id_hex}")
                    continue

                records.append(record)
                save_records(records)

            print(f"Saved registration: {name} ({id_hex})")
            print(f"Start time: {start_time}")

        except (OSError, RuntimeError) as exc:
            print(f"Could not save registration: {exc}")

        finally:
            message_queue.task_done()


# --------------------------------------------------
# Main application
# --------------------------------------------------
def main():
    # Validate existing JSON before connecting.
    with file_lock:
        load_records()

    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id="mqtt-json-collector",
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
    print(f"Output file: {OUTPUT_FILE.resolve()}")

    try:
        client.connect(
            BROKER_HOST,
            BROKER_PORT,
            keepalive=60,
        )

        # Receive MQTT messages in the background.
        client.loop_start()

        # Process messages and request input in the main thread.
        process_messages()

    except KeyboardInterrupt:
        print("\nStopping MQTT collector...")

    except (OSError, RuntimeError) as exc:
        print(f"Application error: {exc}")

    finally:
        client.disconnect()
        client.loop_stop()
        print("MQTT collector stopped.")


if __name__ == "__main__":
    main()
