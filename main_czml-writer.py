import json
import csv
import math
from pathlib import Path
from datetime import datetime, timedelta

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

def seconds_between(start_time_str, current_time_str):
    """
    Compute the difference in seconds between two ISO8601 strings.
    """
    try:
        fmt = "%Y-%m-%dT%H:%M:%SZ"
        start = datetime.strptime(start_time_str, fmt)
        current = datetime.strptime(current_time_str, fmt)
        return (current - start).total_seconds()
    except Exception as ex:
        print(f"Error parsing timestamps: {ex}")
        return 0

def heading_to_quaternion(heading_deg):
    """
    Convert a heading (in degrees) to a quaternion about +Z only.
    Ignores pitch & roll (both zero).
    heading=0 means facing East in a standard ENU frame.
    """
    # Convert heading to radians, modulo 360 to be safe
    yaw_rad = math.radians(heading_deg % 360.0)

    # For yaw-only about Z:
    #   q.w = cos(yaw/2)
    #   q.x = 0
    #   q.y = 0
    #   q.z = sin(yaw/2)
    qw = math.cos(yaw_rad * 0.5)
    qz = math.sin(yaw_rad * 0.5)
    qx = 0.0
    qy = 0.0

    return [qx, qy, qz, qw]

def build_czml(data):
    """
    Create a list of CZML packets with dynamic orientation from heading alone.

    For each row, we compute a quaternion [x,y,z,w] from the heading
    and store it in "orientation.unitQuaternion" alongside the position.
    Pitch and roll are ignored.
    """
    if not data:
        return []

    start_time = data[0]["Timestamp"]
    end_time = data[-1]["Timestamp"]

    # Document packet (global settings)
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

    # We store positions and orientations similarly
    position_list = []
    orientation_list = []

    prev_heading = None

    print(f"Processing {len(data)} total data points")

    for i, row in enumerate(data):
        # Ensure we have valid lat/lon/depth
        if all(row.get(k) is not None for k in ["Timestamp", "Latitude", "Longitude", "Depth"]):
            offset_sec = seconds_between(start_time, row["Timestamp"])

            # Append position
            position_list.extend([
                offset_sec,
                row["Longitude"],  # cartographicDegrees: [lon, lat, height]
                row["Latitude"],
                row["Depth"]
            ])

            # Compute orientation from heading
            heading = row.get("Heading")
            if heading is not None:
                try:
                    heading = float(heading)
                    # Log big heading changes
                    if prev_heading is not None:
                        heading_change = abs(heading - prev_heading)
                        heading_change = min(heading_change, 360 - heading_change)
                        if heading_change > 30:
                            print(
                                f"Significant heading change at row {i}: "
                                f"{prev_heading}° -> {heading}° (Δ{heading_change:.1f}°)"
                            )
                    prev_heading = heading

                    # Convert heading to quaternion
                    qx, qy, qz, qw = heading_to_quaternion(heading)

                    # Append time + quaternion to orientation_list
                    orientation_list.extend([offset_sec, qx, qy, qz, qw])

                    if i % 1000 == 0:
                        print(
                            f"Row {i}: Heading={heading}°, "
                            f"Quaternion=[{qx:.3f}, {qy:.3f}, {qz:.3f}, {qw:.3f}] "
                            f"at time offset {offset_sec:.2f}s"
                        )
                except Exception as e:
                    print(f"Error processing orientation at row {i}: {e}")
            else:
                print(f"Warning: Missing heading data at row {i}")

    if not position_list:
        print("No valid position data found. Returning document-only CZML.")
        return [document_packet]

    # Build the main ROV entity
    hercules_packet = {
        "id": "Hercules",
        "name": "Hercules ROV",
        "availability": f"{start_time}/{end_time}",
        "description": "Visualizing the ROV track, orientation, and sensor data.",
        "path": {
            "show": [{"interval": f"{start_time}/{end_time}", "boolean": True}],
            "width": 2,
            "material": {"solidColor": {"color": {"rgba": [255, 255, 255, 255]}}},
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

    # If we have quaternion data, attach orientation
    if orientation_list:
        hercules_packet["orientation"] = {
            "epoch": start_time,
            "interpolationAlgorithm": "LINEAR",
            "unitQuaternion": orientation_list
        }
        print(f"Generated {len(orientation_list)//5} orientation samples.")
    else:
        print("Warning: No heading data was found; orientation will be omitted.")

    # Combine into a CZML array
    czml = [document_packet, hercules_packet]

    # Generate sensor & event child packets
    for i, row in enumerate(data):
        timestamp = row.get("Timestamp")
        if not timestamp:
            continue

        dt_start = datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%SZ")
        dt_end   = dt_start + timedelta(seconds=2)
        availability_str = f"{timestamp}/{dt_end.strftime('%Y-%m-%dT%H:%M:%SZ')}"

        # Add a sensor label every 5th row (example)
        if i % 5 == 0:
            o2   = row.get("O2_Concentration")
            temp = row.get("Temperature")
            if o2 is not None and temp is not None:
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
                        "text": f"{sensor_name}\nO2: {o2:.2f} mg/L\nTemp: {temp:.2f}°C",
                        "disableDepthTestDistance": 9999999999,
                        "pixelOffset": {"cartesian2": [5, -30]},
                        "fillColor": {"rgba": [255, 255, 255, 255]},
                        "verticalOrigin": "CENTER",
                        "font": "bold 15pt Calibri",
                        "distanceDisplayCondition": {"distanceDisplayCondition": [100, 9999999]},
                        "outlineWidth": 2,
                        "outlineColor": {"rgba": [0, 0, 0, 255]}
                    }
                }
                czml.append(sensor_packet)

        # Process any "event_value" for images or free-form notes
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
                    "distanceDisplayCondition": {"distanceDisplayCondition": [100, 9999999]},
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
                    "distanceDisplayCondition": {"distanceDisplayCondition": [100, 9999999]},
                    "outlineWidth": 2,
                    "outlineColor": {"rgba": [0, 0, 0, 255]}
                }
            }
            czml.append(event_packet)

    return czml

def main():
    # 1) CSV path
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

    # Extract expedition from CSV path (e.g., "NA156" from the folder preceding "RUMI_processed")
    p = Path(csv_in)
    expedition = ""
    if "RUMI_processed" in p.parts:
        idx = p.parts.index("RUMI_processed")
        if idx > 0:
            expedition = p.parts[idx - 1]
    else:
        expedition = "EXPEDITION"

    # Include date and time (hour and minute)
    now_str = datetime.now().strftime("%Y-%m-%d_%H%M")
    output_file = Path(custom_out_dir) / f"{expedition}_{dive_name_input}_{now_str}.czml"
    print(f"Will generate CZML to: {output_file}")

    # 3) Parse data
    data = parse_csv(csv_in)
    if not data:
        print("No data parsed from CSV. Exiting.")
        return

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

    # 4) Build CZML
    czml_list = build_czml(data)
    if not czml_list:
        print("Failed to build CZML. Exiting.")
        return

    # 5) Write CZML to disk
    try:
        with output_file.open("w", encoding="utf-8") as f:
            json.dump(czml_list, f, indent=2)
        print(f"CZML file successfully created: {output_file}")
    except Exception as e:
        print(f"Error writing CZML file: {e}")

    # Additionally, save a copy in the directory of the CSV input file with the new naming convention
    csv_input_dir = Path(csv_in).parent
    copy_file = csv_input_dir / f"{expedition}_{dive_name_input}_{now_str}.czml"
    try:
        with copy_file.open("w", encoding="utf-8") as f:
            json.dump(czml_list, f, indent=2)
        print(f"Copy of CZML file successfully created in CSV directory: {copy_file}")
    except Exception as e:
        print(f"Error writing copy of CZML file: {e}")

if __name__ == "__main__":
    main()
