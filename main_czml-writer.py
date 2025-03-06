import json
import math
import csv
from pathlib import Path
from datetime import datetime, timedelta, date

def parse_csv(file_path):
    """
    Parse a CSV containing ROV data, converting numeric fields to floats.

    Expected columns (some optional):
    - Timestamp (YYYY-mm-ddTHH:MM:SSZ)
    - Latitude, Longitude, Depth, Heading, Pitch, Roll
    - O2_Concentration, Temperature, Salinity, Pressure
    - sensor_name (Optional: used to label the sensor in the CZML)
    - event_value, event_free_text, vehicleRealtimeDualHDGrabData.filename_2_value (for events)

    Returns:
        List[dict]: Each row from the CSV as a dictionary.
    """
    rows = []
    file_path = Path(file_path)
    if not file_path.exists():
        print(f"Error: CSV not found at {file_path}")
        return rows

    try:
        with file_path.open('r', newline='') as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Convert numeric fields to float
                for key in [
                    'Latitude', 'Longitude', 'Depth', 'Heading', 'Pitch', 'Roll',
                    'O2_Concentration', 'Temperature', 'Salinity', 'Pressure'
                ]:
                    if key in row:
                        try:
                            row[key] = float(row[key]) if row[key] else None
                        except ValueError:
                            row[key] = None
                rows.append(row)
        print(f"Successfully loaded {len(rows)} rows from {file_path}")
    except Exception as ex:
        print(f"Error reading CSV {file_path}: {ex}")
    return rows

def euler_to_quaternion(heading_deg, pitch_deg, roll_deg):
    """
    Convert Euler angles (heading, pitch, roll) to a quaternion [x, y, z, w].
    For advanced ROV orientation, you'd incorporate pitch_deg and roll_deg as well.

    We'll do a simple heading rotation about Z. We add 180° to heading so the
    ROV faces forward along its track. Adjust or remove this as needed.
    """
    adjusted_heading = (heading_deg + 180.0) % 360.0
    heading_rad = math.radians(adjusted_heading)
    qz = math.sin(heading_rad / 2.0)
    qw = math.cos(heading_rad / 2.0)
    return [0.0, 0.0, qz, qw]

def seconds_between(start_time_str, current_time_str):
    """
    Compute the difference in seconds between two ISO8601 strings,
    used to build time-tagged arrays in CZML (position, orientation).
    """
    try:
        fmt = "%Y-%m-%dT%H:%M:%SZ"
        start = datetime.strptime(start_time_str, fmt)
        current = datetime.strptime(current_time_str, fmt)
        return (current - start).total_seconds()
    except Exception as ex:
        print(f"Error parsing timestamps: {ex}")
        return 0

def build_czml(data):
    """
    Create a list of CZML packets:
      - 'document' packet (clock/time range)
      - 'Hercules' entity (path + orientation + point)
      - Child sensor/event packets.

    This includes event_value, event_free_text, vehicleRealtimeDualHDGrabData.filename_2_value
    for events, if present in the CSV rows.
    """
    if not data:
        return []

    start_time = data[0]["Timestamp"]
    end_time = data[-1]["Timestamp"]

    # Document packet must be first in CZML
    document_packet = {
        "id": "document",
        "name": "Hercules ROV Mission",
        "version": "1.0",
        "clock": {
            "interval": f"{start_time}/{end_time}",
            "currentTime": start_time,
            "multiplier": 10,
            "range": "LOOP_STOP",
            "step": "SYSTEM_CLOCK_MULTIPLIER"
        }
    }

    position_list = []
    orientation_list = []

    prev_heading = None
    print(f"Processing {len(data)} total data points")

    for i, row in enumerate(data):
        # Basic position check
        if all(row.get(k) is not None for k in ["Timestamp", "Latitude", "Longitude", "Depth"]):
            offset_sec = seconds_between(start_time, row["Timestamp"])
            position_list.extend([
                offset_sec,
                row["Longitude"],
                row["Latitude"],
                row["Depth"]
            ])

            heading = row.get("Heading")
            if heading is not None:
                try:
                    heading = float(heading)
                    if prev_heading is not None:
                        heading_change = abs(heading - prev_heading)
                        heading_change = min(heading_change, 360 - heading_change)
                        if heading_change > 30:
                            print(f"Significant heading change at row {i}: {prev_heading}° -> {heading}° (Δ{heading_change:.1f}°)")
                    prev_heading = heading

                    pitch = row.get("Pitch", 0.0) or 0.0
                    roll  = row.get("Roll", 0.0)  or 0.0

                    qx, qy, qz, qw = euler_to_quaternion(heading, pitch, roll)
                    orientation_list.extend([offset_sec, qx, qy, qz, qw])

                    # Throttle debug prints
                    if i % 1000 == 0:
                        print(f"Row {i}: Heading={heading}°, Quaternion=[{qx:.3f}, {qy:.3f}, {qz:.3f}, {qw:.3f}]")
                except Exception as e:
                    print(f"Error calculating orientation at row {i}: {e}")
            else:
                print(f"Warning: Missing heading data at row {i}")

    if not position_list:
        print("No valid position data found. Returning doc only.")
        return [document_packet]

    print(f"Generated {len(position_list)//4} position points")
    print(f"Generated {len(orientation_list)//5} orientation quaternions")

    # Main "Hercules" entity
    hercules_packet = {
        "id": "Hercules",
        "name": "Hercules ROV",
        "availability": f"{start_time}/{end_time}",
        "description": "Visualizing the ROV track, orientation, and sensor data.",
        "path": {
            "show": [
                {
                    "interval": f"{start_time}/{end_time}",
                    "boolean": True
                }
            ],
            "width": 2,
            "material": {
                "solidColor": {
                    "color": {
                        "rgba": [255, 255, 255, 255]  # White path
                    }
                }
            },
            "resolution": 2,
            "leadTime": 999999999.0,
            "trailTime": 999999999.0
        },
        "position": {
            "epoch": start_time,
            "interpolationAlgorithm": "LAGRANGE",
            "interpolationDegree": 1,
            "cartographicDegrees": position_list
        },
        "point": {
            "color": {"rgba": [0, 255, 255, 255]},
            "pixelSize": 8,
            "outlineColor": {"rgba": [0, 0, 0, 255]},
            "outlineWidth": 1
        }
    }

    if orientation_list:
        hercules_packet["orientation"] = {
            "epoch": start_time,
            "interpolationAlgorithm": "LINEAR",
            "unitQuaternion": orientation_list
        }

    czml = [document_packet, hercules_packet]

    # Generate sensor & event child packets
    for i, row in enumerate(data):
        timestamp = row.get("Timestamp")
        if not timestamp:
            continue

        dt_start = datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%SZ")
        dt_end   = dt_start + timedelta(seconds=2)
        availability_str = f"{timestamp}/{dt_end.strftime('%Y-%m-%dT%H:%M:%SZ')}"

        # Sensor data label every 5 rows
        if i % 5 == 0:
            o2   = row.get("O2_Concentration")
            temp = row.get("Temperature")
            if o2 is not None and temp is not None:
                # Use a sensor_name column if present, else default "Sensor"
                sensor_name = row.get("sensor_name", "Sensor")
                sensor_id = f"{sensor_name}_{i}"

                sensor_packet = {
                    "id": sensor_id,
                    "parent": "Hercules",
                    "availability": availability_str,
                    "position": {"reference": "Hercules#position"},
                    "label": {
                        "style": "FILL_AND_OUTLINE",
                        "scale": 0.5,
                        "horizontalOrigin": "LEFT",
                        "show": True,
                        "text": (
                            f"{sensor_name}\n"
                            f"O2: {o2:.2f} mg/L\n"
                            f"Temp: {temp:.2f}°C"
                        ),
                        "disableDepthTestDistance": 9999999999,
                        "pixelOffset": {"cartesian2": [5, -30]},
                        "fillColor": {"rgba": [255, 255, 255, 255]},
                        "verticalOrigin": "CENTER",
                        "font": "bold 15pt Calibri",
                        "distanceDisplayCondition": {
                            "distanceDisplayCondition": [100, 9999999]
                        },
                        "outlineWidth": 2,
                        "outlineColor": {"rgba": [0, 0, 0, 255]}
                    }
                }
                czml.append(sensor_packet)

        # Event billboard if event_value is present
        if row.get("event_value") and row["event_value"].strip():
            event_type = row["event_value"].strip()
            event_text = row.get("event_free_text", "")
            image_path = row.get("vehicleRealtimeDualHDGrabData.filename_2_value", "")
            if not image_path:
                continue

            if event_type == "FREE_FORM":
                rgba = [0, 100, 0, 179]
                scale = 0.5
            elif event_type == "HIGHLIGHT":
                rgba = [184, 134, 11, 179]
                scale = 0.6
            else:
                rgba = [255, 255, 255, 179]
                scale = 0.5

            safe_time = timestamp.replace(":", "").replace("-", "").replace("T", "_")
            event_id = f"Event_{event_type}_{safe_time}"

            event_packet = {
                "id": event_id,
                "parent": "Hercules",
                "availability": availability_str,
                "position": {"reference": "Hercules#position"},
                "billboard": {
                    "scale": scale,
                    "horizontalOrigin": "RIGHT",
                    "eyeOffset": {"cartesian": [0, 0, 0]},
                    "image": image_path,
                    "show": True,
                    "pixelOffset": {"cartesian2": [0, 0]},
                    "verticalOrigin": "CENTER",
                    "distanceDisplayCondition": {
                        "distanceDisplayCondition": [100, 9999999]
                    },
                    "disableDepthTestDistance": 9999999999,
                    "color": {"rgba": rgba}
                },
                "label": {
                    "style": "FILL_AND_OUTLINE",
                    "scale": 0.5,
                    "horizontalOrigin": "LEFT",
                    "show": True,
                    "text": event_text,
                    "disableDepthTestDistance": 9999999999,
                    "pixelOffset": {"cartesian2": [5, -50]},
                    "fillColor": {"rgba": [255, 255, 255, 255]},
                    "verticalOrigin": "CENTER",
                    "font": "bold 15pt Calibri",
                    "distanceDisplayCondition": {
                        "distanceDisplayCondition": [100, 9999999]
                    },
                    "outlineWidth": 2,
                    "outlineColor": {"rgba": [0, 0, 0, 255]}
                }
            }
            czml.append(event_packet)

    return czml

def main():
    """
    Main function:
      1) Prompt user for CSV path or use default
      2) Prompt for output directory & dive name, or use defaults
      3) Optionally subset rows
      4) Build the CZML & write to file

    Note: This includes event_value, event_free_text, and
          vehicleRealtimeDualHDGrabData.filename_2_value for event billboards.
    """
    # 1) CSV path (hard-coded or let user specify)
    default_csv = r"E:\RUMI\NAUTILUS-CRUISE-COPY2\NA156\RUMI_processed\H2021\NA156_H2021_offset.csv"
    csv_in = input(f"CSV input file path? [default: {default_csv}]: ").strip()
    if not csv_in:
        csv_in = default_csv

    # 2) Output directory + dive name
    default_output_dir = r"C:\Users\produ\PycharmProjects\ROV2CZML"
    print(f"Default output directory is: {default_output_dir}")
    custom_out_dir = input("Enter a custom output directory or press Enter to use default: ").strip()
    if not custom_out_dir:
        custom_out_dir = default_output_dir

    default_dive_name = "H2021"
    dive_name_input = input(f"Enter the dive name (default: {default_dive_name}): ").strip()
    if not dive_name_input:
        dive_name_input = default_dive_name

    # Append today's date to file
    today_str = date.today().strftime("%Y-%m-%d")
    output_file = Path(custom_out_dir) / f"{dive_name_input}_{today_str}.czml"

    print(f"Will generate CZML to: {output_file}")

    # 3) Parse data
    data = parse_csv(csv_in)
    if not data:
        print("No data parsed from CSV. Exiting.")
        return

    # Optional row subsetting
    subset_choice = input("Do you want to generate a CZML from only a subset of rows? (y/n): ").strip().lower()
    if subset_choice == 'y':
        try:
            start_idx = int(input(f"Enter the start row index (0 to {len(data) - 1}): "))
            end_idx   = int(input(f"Enter the end row index (1 to {len(data)}): "))
            if 0 <= start_idx < end_idx <= len(data):
                print(f"Subsetting data from rows {start_idx} through {end_idx - 1}")
                data = data[start_idx:end_idx]
            else:
                print("Invalid range; using full dataset instead.")
        except ValueError:
            print("Invalid input; using full dataset instead.")

    # 4) Build the CZML
    czml_list = build_czml(data)
    if not czml_list:
        print("Failed to build CZML. Exiting.")
        return

    # 5) Write to .czml
    try:
        with output_file.open("w", encoding="utf-8") as f:
            json.dump(czml_list, f, indent=2)
        print(f"CZML file successfully created: {output_file}")
    except Exception as e:
        print(f"Error writing CZML file: {e}")

if __name__ == "__main__":
    main()
