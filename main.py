"""
================================================================================
Hercules ROV to CZML Conversion Script
--------------------------------------------------------------------------------
This script parses a CSV with ROV (Hercules) telemetry data (timestamped lat/lon,
depth, heading, sensor readings, etc.) and produces a Cesium CZML file. The CZML
describes:

  - Time-dynamic 3D positions, referencing the start/end times from CSV
  - Orientation (heading, ignoring pitch/roll)
  - Billboard/label elements for sensor readings
  - Billboard markers for notable 'events'
  - A 3D model reference from Cesium Ion (AssetID 3163466, with the provided token)

KEY POINTS & DEBUGGING:
--------------------------------------------------------------------------------
1) Czml3 Versions:
   - If you see an error about "ImportError: cannot import name 'Reference'" then
     your local czml3 is too old. You have two options:
       (a) Install a newer czml3 from GitHub:
           pip uninstall czml3
           pip install git+https://github.com/Stoops-ML/czml3.git
       (b) Remove usage of 'Reference(...)' and just pass a plain string
           (if your older czml3 supports that). But the GitHub version is recommended.

2) Negative Depth:
   - Depth is stored in the CSV as a negative altitude. Cesium interprets this
     as below the WGS84 ellipsoid. If your true seafloor is offset from the
     ellipsoid, the ROV model may appear 'floating' or 'under' the surface. For
     a broad demonstration, negative altitude is typically acceptable.

3) Heading to Quaternion:
   - Currently we only transform heading into orientation. Pitch and roll are
     ignored. If you need complete orientation, implement a 3D rotation to
     quaternion conversion (heading, pitch, roll).

4) Usage:
   - Update `input_csv` and `output_czml` in the `if __name__ == "__main__":`
     block to your desired CSV input and output path.
   - Run with Python:  python3 main.py
   - Upon success, load the resulting CZML in Cesium Ion or a local Cesium JS
     viewer to verify the track, model, and label events.

5) Debugging / QA:
   - If the script completes but the output in Cesium is not correct, check the
     console for any exceptions or warnings.
   - Inspect the generated .czml file (open in text editor). Confirm presence
     of "Hercules" entity, "position" array, "orientation" array, "billboard"
     references for events, etc.
   - If you get “No valid position or orientation data found,” ensure your CSV
     columns match the script's expected fields: "Timestamp", "Longitude",
     "Latitude", "Depth", "Heading", etc.
================================================================================
"""

from pathlib import Path
import csv
import math
from datetime import datetime, timedelta

import czml3
from czml3.core import Document, Packet
from czml3.properties import (
    Billboard, Clock, Color, Label, Position, Orientation, Point, Model
)
from czml3.types import TimeInterval

# If your czml3 version supports it (GitHub version):
# from czml3.properties import Reference
# If you see "ImportError: cannot import name 'Reference'", you must upgrade 
# or remove usage of Reference below.

try:
    from czml3.properties import Reference
except ImportError:
    # If an older czml3 is installed, define a fallback.
    class Reference(str):
        """
        Stub fallback if older czml3 is installed.
        If you see pydantic errors with this fallback, upgrade czml3.
        """
        pass


def parse_csv(file_path):
    """
    Parse the CSV file into a list of dictionaries.
    Each row is converted to the correct data types (float for numeric fields).
    """
    data = []
    try:
        file_path = Path(file_path)
        with file_path.open('r', newline='') as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Convert numeric fields to float, ignoring ValueError for blank/invalid.
                for key in [
                    'Latitude', 'Longitude', 'Depth', 'O2_Concentration',
                    'Temperature', 'Heading', 'Salinity', 'Pressure'
                ]:
                    if key in row:
                        try:
                            row[key] = float(row[key]) if row[key] else None
                        except ValueError:
                            row[key] = None
                data.append(row)
        print(f"Successfully loaded {len(data)} rows from {file_path}")
        return data
    except Exception as e:
        print(f"Error loading CSV file {file_path}: {e}")
        return []


def seconds_between(start_time, current_time):
    """
    Calculate seconds between two ISO 8601 timestamps (YYYY-mm-ddTHH:MM:SSZ).

    For example:
      start_time = '2023-11-01T21:47:50Z'
      current_time = '2023-11-01T21:47:55Z'
      => returns 5.0
    """
    try:
        start = datetime.strptime(start_time, '%Y-%m-%dT%H:%M:%SZ')
        current = datetime.strptime(current_time, '%Y-%m-%dT%H:%M:%SZ')
        return (current - start).total_seconds()
    except ValueError as e:
        print(f"Error parsing timestamps: {e}")
        return 0


def heading_to_quaternion(heading_deg):
    """
    Convert heading in degrees to a quaternion [x, y, z, w].
    Heading 0° = North, 90° = East, etc. (clockwise from North).

    NOTE: This ignores pitch and roll. If your ROV data includes pitch/roll,
    you must extend this for a full 3D orientation.
    """
    # Adjust heading so 0° heading points along the Y-axis in Cesium.
    heading_rad = math.radians(90 - heading_deg)
    return [
        0,  # x
        0,  # y
        math.sin(heading_rad / 2.0),  # z
        math.cos(heading_rad / 2.0)   # w
    ]


def get_event_duration(seconds=2):
    """
    Creates a short duration for events (billboard pop-ups) to be visible.
    Adjust 'seconds' as desired, or specify a different time interval logic.
    """
    return seconds


def create_czml_document(data):
    """
    Create a CZML document from the CSV data.

    - Builds a "document" packet with mission info and clock range.
    - Builds a "Hercules" packet with time-dynamic position and orientation.
    - Adds sensor labels every 5th row, referencing Hercules' position.
    - Adds event billboards if event_value is populated.

    Returns a czml3.core.Document object or None if no valid data found.
    """
    if not data:
        print("No data to process. Exiting.")
        return None

    # Get time bounds from the data (start_time & end_time).
    start_time = data[0]['Timestamp']
    end_time = data[-1]['Timestamp']

    # Replaced interval=TimeInterval(...) with startTime= and stopTime= for Clock
    document_packet = Packet(
        id="document",
        name="Hercules ROV Mission",
        version="1.0",
        description="ROV Hercules undersea mission visualization",
        clock=Clock(
            startTime=start_time,
            stopTime=end_time,
            currentTime=start_time,
            multiplier=10,
            range="LOOP_STOP",
            step="SYSTEM_CLOCK_MULTIPLIER"
        )
    )

    position_data = []
    orientation_data = []

    # Build the time-tagged positions & quaternions in czml3 format:
    #   position_data => [t0, lon0, lat0, height0, t1, lon1, lat1, height1, ...]
    #   orientation_data => [t0, qx0, qy0, qz0, qw0, t1, qx1, qy1, qz1, qw1, ...]
    for row in data:
        if (row.get('Timestamp') and
            row.get('Longitude') is not None and
            row.get('Latitude') is not None and
            row.get('Depth') is not None and
            row.get('Heading') is not None):

            time_offset = seconds_between(start_time, row['Timestamp'])
            position_data.extend([
                time_offset,
                row['Longitude'],
                row['Latitude'],
                row['Depth']  # Negative depth => below WGS84 ellipsoid
            ])

            # Convert heading to quaternion (ignoring pitch & roll).
            qx, qy, qz, qw = heading_to_quaternion(row['Heading'])
            orientation_data.extend([time_offset, qx, qy, qz, qw])

    if not position_data or not orientation_data:
        print("No valid position or orientation data found. Cannot create CZML.")
        return None

    # ROV "Hercules" entity with dynamic position, orientation, and Ion model.
    hercules_packet = Packet(
        id="Hercules",
        name="Hercules",
        description="ROV Hercules tracking data",
        availability=TimeInterval(start=start_time, end=end_time),
        position=Position(
            epoch=start_time,
            cartographicDegrees=position_data
        ),
        orientation=Orientation(
            epoch=start_time,
            unitQuaternion=orientation_data
        ),
        point=Point(
            color=Color(rgba=[0, 255, 255, 255]),  # Cyan
            pixelSize=8,
            outlineColor=Color(rgba=[0, 0, 0, 255]),  # Black outline
            outlineWidth=1
        ),
        model=Model(
            # Ion Asset #3163466 with a token to access the .gltf
            gltf=(
                "https://assets.cesium.com/3163466/scene.gltf"
                "?access_token=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
                "eyJqdGkiOiIyMjA1Y2ZhZC1hM2IwLTQ4MzQtYWYwZi00MTFmZTEwYjJjMDMiLCJpZCI6MTQ4NTYyLCJpYXQiOjE3MzU4ODQ1Nzh9."
                "jqwp1s3lkvA4Us0vA0skO03kqVya7Sj22kJJKWV6D8M"
            ),
            scale=1.0,
            minimumPixelSize=128,
            show=True
        )
    )

    packets = [document_packet, hercules_packet]

    # Add sensor data & event billboards referencing "Hercules#position".
    for i, row in enumerate(data):
        timestamp = row.get('Timestamp')
        if not timestamp:
            continue

        # Display sensor data label every 5 rows to reduce clutter.
        if i % 5 == 0:
            timestamp_end_dt = datetime.strptime(timestamp, '%Y-%m-%dT%H:%M:%SZ') \
                               + timedelta(seconds=2)
            timestamp_end = timestamp_end_dt.strftime('%Y-%m-%dT%H:%M:%SZ')

            if (row.get('O2_Concentration') is not None
                and row.get('Temperature') is not None):

                sensor_packet = Packet(
                    id=f"Sensor_{i}",
                    parent="Hercules",
                    availability=TimeInterval(start=timestamp, end=timestamp_end),
                    position=Position(reference=Reference("Hercules#position")),
                    label=Label(
                        text=f"O2: {row['O2_Concentration']:.2f} mg/L\n"
                             f"Temp: {row['Temperature']:.2f}°C",
                        fillColor=Color(rgba=[255, 255, 255, 255]),  # White
                        pixelOffset={"values": [0, -30]},
                        show=True,
                        font="12pt sans-serif",
                        horizontalOrigin="CENTER",
                        verticalOrigin="BOTTOM",
                        outlineWidth=2.0,
                        outlineColor=Color(rgba=[0, 0, 0, 255])
                    )
                )
                packets.append(sensor_packet)

        # Handle event billboard if 'event_value' is set (e.g., FREE_FORM, HIGHLIGHT).
        if row.get('event_value') and row.get('event_value').strip():
            event_type = row['event_value']
            event_text = row.get('event_free_text', '')
            image_path = row.get('vehicleRealtimeDualHDGrabData.filename_2_value', '')
            if not image_path:
                # No image, skip billboard creation
                continue

            timestamp_event_end_dt = datetime.strptime(timestamp, '%Y-%m-%dT%H:%M:%SZ') \
                                     + timedelta(seconds=get_event_duration())
            timestamp_event_end = timestamp_event_end_dt.strftime('%Y-%m-%dT%H:%M:%SZ')

            # Color & scale vary by event_type
            if event_type == "FREE_FORM":
                color = [0, 100, 0, 179]  # Dark green, 70% opacity
                scale = 0.5
            elif event_type == "HIGHLIGHT":
                color = [184, 134, 11, 179]  # Dark gold, 70% opacity
                scale = 0.6
            else:
                color = [255, 255, 255, 179]  # Default white, 70% opacity
                scale = 0.5

            safe_timestamp = timestamp.replace(':', '').replace('-', '').replace('T', '_')
            event_id = f"Event_{event_type}_{safe_timestamp}"

            event_packet = Packet(
                id=event_id,
                parent="Hercules",
                availability=TimeInterval(start=timestamp, end=timestamp_event_end),
                position=Position(reference=Reference("Hercules#position")),
                billboard=Billboard(
                    image=image_path,
                    scale=scale,
                    color=Color(rgba=color),
                    horizontalOrigin="CENTER",
                    verticalOrigin="BOTTOM",
                    pixelOffset={"values": [0, 0]}
                ),
                label=Label(
                    text=event_text,
                    fillColor=Color(rgba=[255, 255, 255, 255]),
                    pixelOffset={"values": [0, -50]},
                    show=True,
                    font="14pt sans-serif",
                    horizontalOrigin="CENTER",
                    verticalOrigin="BOTTOM",
                    outlineWidth=2.0,
                    outlineColor=Color(rgba=[0, 0, 0, 255])
                )
            )
            packets.append(event_packet)

    # Return a czml3 Document, which can be .dumps() to a .czml file.
    return Document(packets)


def main(csv_file_path, output_file_path):
    """
    Main function to create CZML from the given CSV file.

    :param csv_file_path: Path to CSV with ROV data (Timestamp, Lat, Lon, Depth, etc.).
    :param output_file_path: Path to the resulting .czml file.

    Steps:
      1) Read CSV into 'data' list.
      2) Build the czml document using create_czml_document().
      3) Write the resulting czml to disk.
    """
    csv_file_path = Path(csv_file_path).resolve()
    output_file_path = Path(output_file_path).resolve()

    if not csv_file_path.exists():
        print(f"Error: Input file not found at {csv_file_path}")
        return False

    output_dir = output_file_path.parent
    if not output_dir.exists():
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            print(f"Created output directory: {output_dir}")
        except Exception as e:
            print(f"Error creating output directory: {e}")
            return False

    data = parse_csv(csv_file_path)
    if not data:
        return False

    czml_doc = create_czml_document(data)
    if not czml_doc:
        return False

    try:
        with output_file_path.open("w", encoding="utf-8") as f:
            f.write(czml_doc.dumps())
        print(f"CZML file successfully created: {output_file_path}")
        return True
    except Exception as e:
        print(f"Error writing CZML file: {e}")
        return False


if __name__ == "__main__":
    # Adjust these to your actual file paths as needed:
    input_csv = Path(r"E:\RUMI\NAUTILUS-CRUISE-COPY2\NA156\RUMI_processed\H2021\NA156_H2021_offset.csv")
    output_czml = Path(r"E:\RUMI\NAUTILUS-CRUISE-COPY2\NA156\RUMI_processed\H2021\NA156_H2021.czml")

    success = main(input_csv, output_czml)

    if success:
        print("CZML generation completed successfully!")
    else:
        print("CZML generation failed. Check the errors above.")
