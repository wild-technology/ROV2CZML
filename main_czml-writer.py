import json
import csv
import math
from pathlib import Path
from datetime import datetime, timedelta
import pyproj

# WGS84 ellipsoid constants are no longer needed as we use pyproj for transformations

# We'll initialize our transformers dynamically based on the first lat/long in the data

def parse_csv(file_path):
	"""
	Parse a CSV containing ROV data, converting numeric fields to floats.
	Expected columns include:
	  - Timestamp (YYYY-mm-ddTHH:MM:SSZ)
	  - Latitude, Longitude (for UTM zone calculation)
	  - UTM_X, UTM_Y, Depth, Heading, Pitch, Roll
	  - O2_Concentration, Temperature, Salinity, Pressure
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
					'Latitude', 'Longitude', 'UTM_X', 'UTM_Y', 'Depth', 'Heading', 'Pitch', 'Roll',
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

def get_utm_zone(lat, lon):
	"""
	Calculate the UTM zone for a given latitude and longitude.

	Args:
		lat: Latitude in decimal degrees
		lon: Longitude in decimal degrees

	Returns:
		UTM zone number
	"""
	if 56.0 <= lat < 64.0 and 3.0 <= lon < 12.0:
		return 32  # Special case for Norway

	if 72.0 <= lat < 84.0:  # Special case for Svalbard
		if 0.0 <= lon < 9.0:
			return 31
		elif 9.0 <= lon < 21.0:
			return 33
		elif 21.0 <= lon < 33.0:
			return 35
		elif 33.0 <= lon < 42.0:
			return 37

	return math.floor((lon + 180) / 6) + 1

def initialize_transformers(data):
	"""
	Initialize UTM to ECEF transformers based on the first lat/long in the data.

	Args:
		data: List of data rows with Latitude and Longitude

	Returns:
		tuple of (utm_to_ecef, utm_to_geodetic) transformers
	"""
	# Find the first valid lat/long
	for row in data:
		if row.get('Latitude') is not None and row.get('Longitude') is not None:
			lat = row['Latitude']
			lon = row['Longitude']

			# Determine UTM zone
			utm_zone = get_utm_zone(lat, lon)
			hemisphere = 'north' if lat >= 0 else 'south'

			print(f"Calculated UTM zone: {utm_zone}{hemisphere[0].upper()} for coordinates Lat: {lat}, Lon: {lon}")

			# Create transformers
			utm_to_ecef = pyproj.Transformer.from_crs(
				f"+proj=utm +zone={utm_zone} +{hemisphere} +datum=WGS84 +units=m +no_defs",
				"+proj=geocent +datum=WGS84 +units=m +no_defs",
				always_xy=True
			)

			utm_to_geodetic = pyproj.Transformer.from_crs(
				f"+proj=utm +zone={utm_zone} +{hemisphere} +datum=WGS84 +units=m +no_defs",
				"+proj=longlat +datum=WGS84 +no_defs",
				always_xy=True
			)

			return utm_to_ecef, utm_to_geodetic

	# Default to UTM zone 4N if no valid lat/long found
	print("Warning: No valid latitude/longitude found. Defaulting to UTM zone 4N.")
	utm_to_ecef = pyproj.Transformer.from_crs(
		"+proj=utm +zone=4 +north +datum=WGS84 +units=m +no_defs",
		"+proj=geocent +datum=WGS84 +units=m +no_defs",
		always_xy=True
	)

	utm_to_geodetic = pyproj.Transformer.from_crs(
		"+proj=utm +zone=4 +north +datum=WGS84 +units=m +no_defs",
		"+proj=longlat +datum=WGS84 +no_defs",
		always_xy=True
	)

	return utm_to_ecef, utm_to_geodetic

def utm_to_cartesian(utm_x, utm_y, depth, utm_to_ecef_transformer):
	"""
	Convert UTM coordinates and depth to ECEF Cartesian coordinates.

	Args:
		utm_x: Easting coordinate in UTM (meters)
		utm_y: Northing coordinate in UTM (meters)
		depth: Depth below sea level (already negative values) in meters
		utm_to_ecef_transformer: Transformer for UTM to ECEF conversion

	Returns:
		List of [x, y, z] coordinates in ECEF
	"""
	# For UTM, we need an ellipsoidal height, not a depth
	# Assuming an approximate height adjustment from MSL to ellipsoid
	# A general approximation of geoid height is around -30m

	# Since depth is already stored as negative values, we don't need to negate it again
	# Just adjust for the geoid height
	ellipsoidal_height = depth - 30.0  # Keep the negative depth value and adjust for geoid

	# Convert from UTM to ECEF
	x, y, z = utm_to_ecef_transformer.transform(utm_x, utm_y, ellipsoidal_height)
	return [x, y, z]

def enu_to_ecef_matrix(utm_x, utm_y, utm_to_geodetic_transformer):
	"""
	Compute the rotation matrix from the local ENU coordinate system
	to the ECEF coordinate system for given UTM coordinates.

	Returns a 3x3 rotation matrix as a list of 3 column vectors, not row vectors.
	"""
	# First, we need to convert UTM to geodetic (lat/lon)
	lon_deg, lat_deg = utm_to_geodetic_transformer.transform(utm_x, utm_y)
	lon_rad = math.radians(lon_deg)
	lat_rad = math.radians(lat_deg)

	# Now compute ENU to ECEF rotation matrix
	sinLon = math.sin(lon_rad)
	cosLon = math.cos(lon_rad)
	sinLat = math.sin(lat_rad)
	cosLat = math.cos(lat_rad)

	# Column vectors for proper rotation
	# First column (transforming East basis vector)
	col1 = [-sinLon, -sinLat * cosLon, cosLat * cosLon]
	# Second column (transforming North basis vector)
	col2 = [cosLon, -sinLat * sinLon, cosLat * sinLon]
	# Third column (transforming Up basis vector)
	col3 = [0, cosLat, sinLat]

	return [col1, col2, col3]

def matrix_to_quaternion(m):
	"""
	Convert a 3x3 rotation matrix (list of 3 lists) to a quaternion [x, y, z, w].
	"""
	trace = m[0][0] + m[1][1] + m[2][2]
	if trace > 0:
		s = math.sqrt(trace + 1.0) * 2  # s = 4 * qw
		qw = 0.25 * s
		qx = (m[2][1] - m[1][2]) / s
		qy = (m[0][2] - m[2][0]) / s
		qz = (m[1][0] - m[0][1]) / s
	elif (m[0][0] > m[1][1]) and (m[0][0] > m[2][2]):
		s = math.sqrt(1.0 + m[0][0] - m[1][1] - m[2][2]) * 2  # s = 4 * qx
		qw = (m[2][1] - m[1][2]) / s
		qx = 0.25 * s
		qy = (m[0][1] + m[1][0]) / s
		qz = (m[0][2] + m[2][0]) / s
	elif m[1][1] > m[2][2]:
		s = math.sqrt(1.0 + m[1][1] - m[0][0] - m[2][2]) * 2  # s = 4 * qy
		qw = (m[0][2] - m[2][0]) / s
		qx = (m[0][1] + m[1][0]) / s
		qy = 0.25 * s
		qz = (m[1][2] + m[2][1]) / s
	else:
		s = math.sqrt(1.0 + m[2][2] - m[0][0] - m[1][1]) * 2  # s = 4 * qz
		qw = (m[1][0] - m[0][1]) / s
		qx = (m[0][2] + m[2][0]) / s
		qy = (m[1][2] + m[2][1]) / s
		qz = 0.25 * s
	return [qx, qy, qz, qw]

def quaternion_multiply(q1, q2):
	"""
	Multiply two quaternions.
	q1 and q2 are lists [x, y, z, w].
	Returns their product as [x, y, z, w].
	"""
	x1, y1, z1, w1 = q1
	x2, y2, z2, w2 = q2
	x = w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2
	y = w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2
	z = w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2
	w = w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2
	return [x, y, z, w]

def quaternion_conjugate(q):
	"""
	Returns the conjugate of a quaternion [x, y, z, w].
	"""
	x, y, z, w = q
	return [-x, -y, -z, w]

def euler_to_quaternion(heading_deg, pitch_deg, roll_deg):
	"""
	Convert Euler angles in degrees to a quaternion.
	- Heading (yaw) is measured clockwise from North
	- Pitch is positive nose up
	- Roll is positive right side down

	Returns quaternion as [x, y, z, w]
	"""
	# Print original input values for debugging
	print(f"Original Euler angles: Heading={heading_deg}°, Pitch={pitch_deg}°, Roll={roll_deg}°")

	# Convert angles to radians
	# In ENU: North = 0°, East = 90°, South = 180°, West = 270°
	yaw = math.radians((90 - heading_deg) % 360.0)  # Convert from navigation heading to ENU yaw
	pitch = math.radians(pitch_deg)
	roll = math.radians(roll_deg)

	# Compute half angles
	cy = math.cos(yaw * 0.5)
	sy = math.sin(yaw * 0.5)
	cp = math.cos(pitch * 0.5)
	sp = math.sin(pitch * 0.5)
	cr = math.cos(roll * 0.5)
	sr = math.sin(roll * 0.5)

	# Compute quaternion components using ZYX rotation order (yaw, pitch, roll)
	qw = cr * cp * cy + sr * sp * sy
	qx = sr * cp * cy - cr * sp * sy
	qy = cr * sp * cy + sr * cp * sy
	qz = cr * cp * sy - sr * sp * cy

	# Print resulting quaternion for debugging
	print(f"Local quaternion: [{qx:.6f}, {qy:.6f}, {qz:.6f}, {qw:.6f}]")

	return [qx, qy, qz, qw]

def get_precise_model_correction():
	"""
	Returns identity quaternion (no additional correction)
	"""
	print("Using identity quaternion for model correction (no correction applied)")
	return [0, 0, 0, 1]  # Identity quaternion (no rotation)

def build_czml(data):
	"""
	Create a list of CZML packets with dynamic orientation.

	For each row:
	  - Convert UTM coordinates and depth to ECEF Cartesian coordinates
	  - Compute a quaternion in the local ENU frame using heading, pitch, and roll,
		then transform that quaternion into the ECEF frame.
	"""
	if not data:
		return []

	# Initialize transformers based on the first lat/long in the data
	utm_to_ecef_transformer, utm_to_geodetic_transformer = initialize_transformers(data)

	start_time = data[0]["Timestamp"]
	end_time = data[-1]["Timestamp"]

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

	position_list = []  # Will hold [time, x, y, z] in ECEF
	orientation_list = []  # Will hold [time, qx, qy, qz, qw] in ECEF

	prev_heading = None
	print(f"Processing {len(data)} total data points")

	# Get the model correction quaternion (identity quaternion)
	model_correction = get_precise_model_correction()
	print(f"Using model correction quaternion: {model_correction}")

	# For the first few rows, print detailed debug info
	debug_detail_limit = 5

	for i, row in enumerate(data):
		if all(row.get(k) is not None for k in ["Timestamp", "UTM_X", "UTM_Y", "Depth"]):
			offset_sec = seconds_between(start_time, row["Timestamp"])

			utm_x = row["UTM_X"]
			utm_y = row["UTM_Y"]
			depth = row["Depth"]  # Depth is negative below sea level

			# Convert UTM coordinates to ECEF
			xyz = utm_to_cartesian(utm_x, utm_y, depth, utm_to_ecef_transformer)
			position_list.extend([offset_sec] + xyz)

			# Special handling for the first 20 points - force them to be level flight pointing north
			if i < 20:  # First 20 rows should be level flight pointing north
				if i < debug_detail_limit:
					print(f"\n--- SPECIAL HANDLING FOR ROW {i}: FORCING LEVEL FLIGHT NORTH ---")

				# For a vehicle pointing North in ENU frame, we use identity quaternion
				q_north = [0.0, 0.0, 0.0, 1.0]  # [x, y, z, w] - identity quaternion

				# Convert directly to ECEF using UTM coordinates
				enu_matrix = enu_to_ecef_matrix(utm_x, utm_y, utm_to_geodetic_transformer)
				q_transform = matrix_to_quaternion(enu_matrix)

				if i < debug_detail_limit:
					print(f"Forcing level flight pointing north")
					print(
						f"North-pointing local quaternion: [{q_north[0]:.6f}, {q_north[1]:.6f}, {q_north[2]:.6f}, {q_north[3]:.6f}]")
					print(
						f"ENU to ECEF quaternion: [{q_transform[0]:.6f}, {q_transform[1]:.6f}, {q_transform[2]:.6f}, {q_transform[3]:.6f}]")

				# Transform the local north-pointing quaternion to ECEF frame
				q_global = quaternion_multiply(q_transform, q_north)

				if i < debug_detail_limit:
					print(
						f"Final ECEF quaternion: [{q_global[0]:.6f}, {q_global[1]:.6f}, {q_global[2]:.6f}, {q_global[3]:.6f}]")
					print(f"--- END SPECIAL HANDLING FOR ROW {i} ---\n")

				orientation_list.extend([offset_sec] + q_global)

				if i % 5 == 0:
					print(f"Row {i}: FORCING Heading=0°, Pitch=0°, Roll=0°, " +
						  f"Quaternion=[{q_global[0]:.3f}, {q_global[1]:.3f}, {q_global[2]:.3f}, {q_global[3]:.3f}] " +
						  f"at offset {offset_sec:.2f}s")
				continue  # Skip the rest of the loop for these first points

			# Normal processing for remaining points
			# Get all orientation angles
			heading = row.get("Heading")
			pitch = row.get("Pitch", 0.0)  # Default to 0 if not present
			roll = row.get("Roll", 0.0)  # Default to 0 if not present

			if heading is not None:
				try:
					heading = float(heading)
					pitch = float(pitch)
					roll = float(roll)

					if i < debug_detail_limit:
						print(f"\n--- DETAILED DEBUG FOR ROW {i} ---")
						print(f"Raw values: Heading={heading}°, Pitch={pitch}°, Roll={roll}°")

					if prev_heading is not None:
						heading_change = abs(heading - prev_heading)
						heading_change = min(heading_change, 360 - heading_change)
						if heading_change > 30:
							print(
								f"Significant heading change at row {i}: {prev_heading}° -> {heading}° (Δ{heading_change:.1f}°)")
					prev_heading = heading

					# Compute quaternion from all three Euler angles
					if i < debug_detail_limit:
						print(f"Computing local quaternion from Euler angles")
					q_local = euler_to_quaternion(heading, pitch, roll)

					# Apply the model correction - multiply the correction first (pre-multiply)
					if i < debug_detail_limit:
						print(f"Applying model correction quaternion")
					q_local_corrected = quaternion_multiply(model_correction, q_local)
					if i < debug_detail_limit:
						print(
							f"Corrected local quaternion: [{q_local_corrected[0]:.6f}, {q_local_corrected[1]:.6f}, {q_local_corrected[2]:.6f}, {q_local_corrected[3]:.6f}]")

					# Convert to ECEF frame using UTM coordinates
					if i < debug_detail_limit:
						print(f"Computing ENU to ECEF transformation matrix for UTM_X={utm_x}, UTM_Y={utm_y}")
					enu_matrix = enu_to_ecef_matrix(utm_x, utm_y, utm_to_geodetic_transformer)
					if i < debug_detail_limit:
						print(f"ENU matrix: {enu_matrix}")
					q_transform = matrix_to_quaternion(enu_matrix)
					if i < debug_detail_limit:
						print(
							f"ENU to ECEF quaternion: [{q_transform[0]:.6f}, {q_transform[1]:.6f}, {q_transform[2]:.6f}, {q_transform[3]:.6f}]")

					q_global = quaternion_multiply(q_transform, q_local_corrected)
					if i < debug_detail_limit:
						print(
							f"Final ECEF quaternion: [{q_global[0]:.6f}, {q_global[1]:.6f}, {q_global[2]:.6f}, {q_global[3]:.6f}]")
						print(f"--- END DETAILED DEBUG FOR ROW {i} ---\n")

					orientation_list.extend([offset_sec] + q_global)

					if i % 1000 == 0:
						print(f"Row {i}: Heading={heading}°, Pitch={pitch}°, Roll={roll}°, " +
							  f"Quaternion=[{q_global[0]:.3f}, {q_global[1]:.3f}, {q_global[2]:.3f}, {q_global[3]:.3f}] " +
							  f"at offset {offset_sec:.2f}s")
				except Exception as e:
					print(f"Error processing orientation at row {i}: {e}")
			else:
				print(f"Warning: Missing heading data at row {i}")

	if not position_list:
		print("No valid position data found. Returning document-only CZML.")
		return [document_packet]

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
			"cartesian": position_list
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
		print(f"Generated {len(orientation_list) // 5} orientation samples.")
	else:
		print("Warning: No heading data was found; orientation will be omitted.")

	czml = [document_packet, hercules_packet]

	# Generate sensor and event packets
	for i, row in enumerate(data):
		timestamp = row.get("Timestamp")
		if not timestamp:
			continue

		dt_start = datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%SZ")
		dt_end = dt_start + timedelta(seconds=2)
		availability_str = f"{timestamp}/{dt_end.strftime('%Y-%m-%dT%H:%M:%SZ')}"

		if i % 5 == 0:
			o2 = row.get("O2_Concentration")
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

		# Handle event data if present
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
    default_csv = r"E:\RUMI\NAUTILUS-CRUISE-COPY2\NA156\RUMI_processed\H2021\NA156_H2021_filtered_offset_final.csv"
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

    p = Path(csv_in)
    expedition = p.parts[p.parts.index("RUMI_processed") - 1] if "RUMI_processed" in p.parts else "EXPEDITION"

    now_str = datetime.now().strftime("%Y-%m-%d_%H%M")
    output_file = Path(custom_out_dir) / f"{expedition}_{dive_name_input}_{now_str}.czml"
    print(f"Will generate CZML to: {output_file}")

    data = parse_csv(csv_in)
    if not data:
        print("No data parsed from CSV. Exiting.")
        return

    subset_choice = input("Do you want to generate a CZML from only a subset of rows? (y/n): ").strip().lower()
    if subset_choice == 'y':
        try:
            start_idx = int(input(f"Enter the start row index (0 to {len(data) - 1}): "))
            end_idx = int(input(f"Enter the end row index (1 to {len(data)}): "))
            if 0 <= start_idx < end_idx <= len(data):
                print(f"Subsetting data from rows {start_idx} through {end_idx - 1}")
                data = data[start_idx:end_idx]
            else:
                print("Invalid range; using full dataset instead.")
        except ValueError:
            print("Invalid input; using full dataset instead.")

    czml_list = build_czml(data)
    if not czml_list:
        print("Failed to build CZML. Exiting.")
        return

    try:
        with output_file.open("w", encoding="utf-8") as f:
            json.dump(czml_list, f, indent=2)
        print(f"CZML file successfully created: {output_file}")
    except Exception as e:
        print(f"Error writing CZML file: {e}")

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