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
				for key in ['Latitude', 'Longitude', 'Depth', 'Heading', 'Pitch', 'Roll',
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

def euler_to_quaternion(heading_deg, pitch_deg, roll_deg):
	"""
    Convert Euler angles (heading/yaw, pitch, roll) to quaternion [x,y,z,w].

    Args:
        heading_deg: Heading in degrees (0=North, 90=East)
        pitch_deg: Pitch in degrees (positive=nose up)
        roll_deg: Roll in degrees (positive=right wing down)

    Returns:
        List of quaternion components [x,y,z,w]
    """
	# Convert to radians
	heading_rad = math.radians(heading_deg)
	pitch_rad = math.radians(pitch_deg)
	roll_rad = math.radians(roll_deg)

	# For Cesium, we need to use a different rotation order and axis alignment
	# Rotate around axes in order: Z (heading), X (roll), Y (pitch)
	# This differs from aircraft convention but better matches Cesium's expectations

	# Half angles for quaternion calculation
	hz = heading_rad / 2.0
	px = roll_rad / 2.0  # Roll around X axis
	ry = -pitch_rad / 2.0  # Negative pitch around Y axis

	# Calculate the quaternion components for each rotation axis
	cz = math.cos(hz)
	sz = math.sin(hz)
	cx = math.cos(px)
	sx = math.sin(px)
	cy = math.cos(ry)
	sy = math.sin(ry)

	# Combine the rotations in the correct order (Z-X-Y)
	qw = cz * cx * cy - sz * sx * sy
	qx = cz * sx * cy - sz * cx * sy
	qy = cz * cx * sy + sz * sx * cy
	qz = sz * cx * cy + cz * sx * sy

	# Normalize quaternion
	magnitude = math.sqrt(qw * qw + qx * qx + qy * qy + qz * qz)
	if magnitude > 0:
		qw /= magnitude
		qx /= magnitude
		qy /= magnitude
		qz /= magnitude

	return [qx, qy, qz, qw]

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
	heading_rad = math.radians(heading_deg)
	return [
		0.0,
		0.0,
		math.sin(heading_rad / 2.0),
		math.cos(heading_rad / 2.0)
	]

def build_czml(data):
	"""
    Build a list of CZML packets matching the official spec, including:
      - Document packet (with 'interval' & 'clock')
      - ROV entity with path + orientation
      - Sensor/event child packets referencing the ROV
    """
	if not data:
		return []

	# Start and end times for the entire (sub)mission
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
		}
	}

	# Build arrays for positions/orientation
	position_list = []
	orientation_list = []

	for row in data:
		if all(row.get(k) is not None for k in
			   ["Timestamp", "Latitude", "Longitude", "Depth", "Heading", "Pitch", "Roll"]):
			offset_sec = seconds_between(start_time, row["Timestamp"])
			position_list.extend([
				offset_sec,
				row["Longitude"],
				row["Latitude"],
				row["Depth"]  # negative altitude => below ellipsoid
			])

			# Use all three orientation angles with error handling
			try:
				# Ensure all orientation values are numeric
				heading = float(row["Heading"]) if isinstance(row["Heading"], (int, float, str)) else 0.0
				pitch = float(row["Pitch"]) if isinstance(row["Pitch"], (int, float, str)) else 0.0
				roll = float(row["Roll"]) if isinstance(row["Roll"], (int, float, str)) else 0.0

				qx, qy, qz, qw = euler_to_quaternion(heading, pitch, roll)
			except (ValueError, TypeError) as e:
				print(f"Error converting orientation at timestamp {row['Timestamp']}: {e}")
				# Use default orientation (no rotation)
				qx, qy, qz, qw = 0.0, 0.0, 0.0, 1.0
			orientation_list.extend([offset_sec, qx, qy, qz, qw])

	if not position_list or not orientation_list:
		print("No valid position or orientation data found. Returning doc only.")
		return [document_packet]

	# 2) ROV main entity
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
			"trailTime": 0.0
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
		"point": {
			"color": {"rgba": [0, 255, 255, 255]},  # Cyan
			"pixelSize": 8,
			"outlineColor": {"rgba": [0, 0, 0, 255]},
			"outlineWidth": 1
		}
	}

	czml = [document_packet, hercules_packet]

	# 3) Sensor + Event child packets
	for i, row in enumerate(data):
		timestamp = row.get("Timestamp")
		if not timestamp:
			continue

		# Show sensor data label every 5 rows
		if i % 5 == 0:
			dt_start = datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%SZ")
			dt_end = dt_start + timedelta(seconds=2)
			availability_str = f"{timestamp}/{dt_end.strftime('%Y-%m-%dT%H:%M:%SZ')}"
			if (row.get("O2_Concentration") is not None
					and row.get("Temperature") is not None):
				sensor_id = f"Sensor_{i}"
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
						"text": (f"O2: {row['O2_Concentration']:.2f} mg/L\n"
								 f"Temp: {row['Temperature']:.2f}°C"),
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

def main(csv_path, output_path):
	"""
    Reads ROV data from a CSV, optionally filters rows based on user input,
    builds a custom CZML array, and dumps to JSON.
    """
	data = parse_csv(csv_path)
	if not data:
		return False

	# Ask if user wants to subset the data
	subset_choice = input("Do you want to generate a CZML from only a subset of rows? (y/n): ").strip().lower()
	if subset_choice == 'y':
		try:
			start_idx = int(input(f"Enter the start row index (0 to {len(data) - 1}): "))
			end_idx = int(input(f"Enter the end row index (1 to {len(data)}): "))
			# Basic validation
			if 0 <= start_idx < end_idx <= len(data):
				print(f"Subsetting data from rows {start_idx} through {end_idx - 1}")
				data = data[start_idx:end_idx]
			else:
				print("Invalid range; using full dataset instead.")
		except ValueError:
			print("Invalid input; using full dataset instead.")

	czml_list = build_czml(data)
	if not czml_list:
		return False

	try:
		with open(output_path, "w", encoding="utf-8") as f:
			json.dump(czml_list, f, indent=2)
		print(f"CZML file successfully created: {output_path}")
		return True
	except Exception as ex:
		print(f"Error writing final CZML: {ex}")
		return False

if __name__ == "__main__":
	# Import for date formatting
	from datetime import date

	# Get current date in YYYY-MM-DD format
	today_date = date.today().strftime("%Y-%m-%d")

	CSV_FILE = r"E:\RUMI\NAUTILUS-CRUISE-COPY2\NA156\RUMI_processed\H2021\NA156_H2021_offset.csv"
	OUTPUT_CZML = rf"E:\RUMI\NAUTILUS-CRUISE-COPY2\NA156\RUMI_processed\H2021\NA156_H2021_{today_date}.czml"

	print(f"Output file will be: {OUTPUT_CZML}")
	ok = main(CSV_FILE, OUTPUT_CZML)
	if ok:
		print("CZML generation completed successfully!")
	else:
		print("CZML generation failed.")