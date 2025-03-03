import json
import math
import csv
from pathlib import Path
from datetime import datetime, timedelta

def parse_csv(file_path):
    """
    Parses the CSV, converting numeric fields to float where needed.
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
                # Convert numeric fields
                for key in ['Latitude', 'Longitude', 'Depth', 'Heading',
                            'O2_Concentration', 'Temperature', 'Salinity', 'Pressure']:
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
    Returns the difference in seconds between two ISO8601 strings:
      e.g. '2023-11-01T21:47:50Z'
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
    Convert heading (0=North, 90=East) to [x,y,z,w]. Pitch/roll are ignored.
    """
    heading_rad = math.radians(90 - heading_deg)
    return [
        0.0,
        0.0,
        math.sin(heading_rad / 2.0),
        math.cos(heading_rad / 2.0)
    ]

def build_czml(data):
    """
    Build a list of CZML packets matching the official spec, including:
      - Document packet (with 'viewFrom', 'interval', etc.)
      - ROV packet with path + orientation + model
      - Sensor and event packets referencing the ROV
    """
    if not data:
        return []

    # Start and end times for the entire mission
    start_time = data[0]["Timestamp"]
    end_time = data[-1]["Timestamp"]

    # 1) Document packet
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
        },
        # Optional: place a 'viewFrom' at the top level (some apps allow this).
        # More commonly, 'viewFrom' goes on the main entity. We'll do it in the entity.
    }

    # Build arrays for positions/orientation
    position_list = []
    orientation_list = []

    for row in data:
        if all(row.get(k) is not None for k in ["Timestamp", "Latitude", "Longitude", "Depth", "Heading"]):
            offset_sec = seconds_between(start_time, row["Timestamp"])
            position_list.extend([
                offset_sec,
                row["Longitude"],
                row["Latitude"],
                row["Depth"]  # negative altitude => below ellipsoid
            ])
            qx, qy, qz, qw = heading_to_quaternion(row["Heading"])
            orientation_list.extend([offset_sec, qx, qy, qz, qw])

    if not position_list or not orientation_list:
        print("No valid position or orientation data found. Returning doc only.")
        return [document_packet]

    # 2) Create the main ROV packet (similar to the "Drone" example).
    hercules_packet = {
        "id": "Hercules",
        "name": "Hercules ROV",
        "availability": f"{start_time}/{end_time}",
        "description": "Visualizing the ROV track, orientation, and sensor data.",
        # Show entire path from start_time to end_time
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
            # leadTime / trailTime set to 0 => entire path visible
            "leadTime": 999999999.0,
            "trailTime": 0.0
        },
        # "viewFrom": sets the default camera offset behind the ROV by ~100m
        # The cartesian is ECEF. If you want a local offset behind the heading direction,
        # you'd need to dynamically compute it. This is a simple static offset.
        "viewFrom": {
            "cartesian": [0, -100, 50]
        },
        "position": {
            "epoch": start_time,
            "interpolationAlgorithm": "LAGRANGE",
            "interpolationDegree": 1,
            "cartographicDegrees": position_list
        },
        "orientation": {
            "epoch": start_time,
            "interpolationAlgorithm": "LINEAR",
            "unitQuaternion": orientation_list
        },
        "model": {
            # We mimic the example by specifying an array with intervals,
            # but a single object is typically okay. We'll do a single object:
            "gltf": "https://assets.cesium.com/3163466/scene.gltf?access_token=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJqdGkiOiIyMjA1Y2ZhZC1hM2IwLTQ4MzQtYWYwZi00MTFmZTEwYjJjMDMiLCJpZCI6MTQ4NTYyLCJpYXQiOjE3MzU4ODQ1Nzh9.jqwp1s3lkvA4Us0vA0skO03kqVya7Sj22kJJKWV6D8M",
            "runAnimations": True,
            "scale": 1.0,
            "show": True
        },
        # Optionally add a small point or billboard to confirm location
        "point": {
            "color": {"rgba": [0, 255, 255, 255]},  # Cyan
            "pixelSize": 8,
            "outlineColor": {"rgba": [0, 0, 0, 255]},
            "outlineWidth": 1
        }
    }

    czml = [document_packet, hercules_packet]

    # 3) Sensor + Event Packets
    for i, row in enumerate(data):
        timestamp = row.get("Timestamp")
        if not timestamp:
            continue

        # Show sensor data label every 5 rows
        if i % 5 == 0:
            dt_start = datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%SZ")
            dt_end = dt_start + timedelta(seconds=2)
            availability_str = f"{timestamp}/{dt_end.strftime('%Y-%m-%dT%H:%M:%SZ')}"
            if (row.get("O2_Concentration") is not None and
                row.get("Temperature") is not None):
                sensor_id = f"Sensor_{i}"
                sensor_packet = {
                    "id": sensor_id,
                    "parent": "Hercules",
                    "availability": availability_str,
                    "position": {"reference": "Hercules#position"},
                    "label": {
                        "text": (f"O2: {row['O2_Concentration']:.2f} mg/L\n"
                                 f"Temp: {row['Temperature']:.2f}°C"),
                        "fillColor": {"rgba": [255, 255, 255, 255]},
                        "pixelOffset": {"cartesian2": [0, -30]},
                        "show": True,
                        "font": "12pt sans-serif",
                        "horizontalOrigin": "CENTER",
                        "verticalOrigin": "BOTTOM",
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

            dt_start = datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%SZ")
            dt_end = dt_start + timedelta(seconds=2)
            availability_str = f"{timestamp}/{dt_end.strftime('%Y-%m-%dT%H:%M:%SZ')}"

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
                    "image": image_path,
                    "scale": scale,
                    "color": {"rgba": rgba},
                    "horizontalOrigin": "CENTER",
                    "verticalOrigin": "BOTTOM",
                    "pixelOffset": {"cartesian2": [0, 0]}
                },
                "label": {
                    "text": event_text,
                    "fillColor": {"rgba": [255, 255, 255, 255]},
                    "pixelOffset": {"cartesian2": [0, -50]},
                    "show": True,
                    "font": "14pt sans-serif",
                    "horizontalOrigin": "CENTER",
                    "verticalOrigin": "BOTTOM",
                    "outlineWidth": 2,
                    "outlineColor": {"rgba": [0, 0, 0, 255]}
                }
            }
            czml.append(event_packet)

    return czml

def main(csv_path, output_path):
    """
    Reads ROV data from a CSV, builds a custom CZML array, and dumps to JSON.
    """
    data = parse_csv(csv_path)
    if not data:
        return False

    czml_list = build_czml(data)
    if not czml_list:
        return False

    try:
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(czml_list, f, indent=2)
        print(f"Successfully wrote updated CZML to {output_path}")
        return True
    except Exception as ex:
        print(f"Error writing final CZML: {ex}")
        return False

if __name__ == "__main__":
    CSV_FILE = r"E:\RUMI\NAUTILUS-CRUISE-COPY2\NA156\RUMI_processed\H2021\NA156_H2021_offset.csv"
    OUTPUT_CZML = r"E:\RUMI\NAUTILUS-CRUISE-COPY2\NA156\RUMI_processed\H2021\NA156_H2021_manual.czml"

    ok = main(CSV_FILE, OUTPUT_CZML)
    if ok:
        print("CZML generation completed successfully!")
    else:
        print("CZML generation failed.")
