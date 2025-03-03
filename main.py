import csv
import os
import math
from datetime import datetime, timedelta
import czml3
from czml3.core import Document, Packet
from czml3.properties import (
	Billboard, Clock, Color, Label, Position, Orientation, Point, Model
)
from czml3.types import TimeInterval

def parse_csv(file_path):
	"""Parse the CSV file into a list of dictionaries."""
	data = []
	try:
		with open(file_path, 'r') as f:
			reader = csv.DictReader(f)
			for row in reader:
				# Convert numeric values to appropriate types
				for key in row:
					if key in ['Latitude', 'Longitude', 'Depth', 'O2_Concentration',
							   'Temperature', 'Heading', 'Salinity', 'Pressure']:
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
	"""Calculate seconds between two ISO 8601 timestamps."""
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
	Heading 0° = North, 90° = East, etc. (clockwise from North)
	"""
	# Convert degrees to radians and adjust for CZML orientation
	# In CZML, the heading needs to be adjusted to match the coordinate system
	heading_rad = math.radians(90 - heading_deg)

	# For a simple heading rotation around the up axis (z-axis in Cartesian)
	# We use [0, 0, sin(heading/2), cos(heading/2)]
	return [
		0,  # x
		0,  # y
		math.sin(heading_rad / 2),  # z
		math.cos(heading_rad / 2)  # w
	]

def get_event_duration(seconds=2):
	"""Creates a short duration for events to be visible."""
	return seconds

def create_czml_document(data):
	"""Create a CZML document from the CSV data."""
	if not data:
		print("No data to process. Exiting.")
		return None

	# Get time bounds
	start_time = data[0]['Timestamp']
	end_time = data[-1]['Timestamp']

	# Create document packet (metadata)
	document_packet = Packet(
		id="document",
		name="Hercules ROV Mission",
		version="1.0",
		description="ROV Hercules undersea mission visualization",
		clock=Clock(
			interval=TimeInterval(start=start_time, end=end_time),
			currentTime=start_time,
			multiplier=10,
			range="LOOP_STOP",
			step="SYSTEM_CLOCK_MULTIPLIER"
		)
	)

	# Create position data and orientation data for Hercules vehicle
	position_data = []
	orientation_data = []

	for row in data:
		# Check for required position data
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
				row['Depth']  # Already negative in the data
			])

			# Add heading data for orientation
			quaternion = heading_to_quaternion(row['Heading'])
			orientation_data.extend([time_offset] + quaternion)

	if not position_data or not orientation_data:
		print("No valid position or orientation data found. Cannot create CZML.")
		return None

	# Create Hercules vehicle packet
	hercules_packet = Packet(
		id="Hercules",
		name="Hercules",
		description="ROV Hercules tracking data",
		availability=TimeInterval(start=start_time, end=end_time),
		position=Position(
			epoch=start_time,
			cartographicDegrees=position_data
		),
		# Using the heading data for orientation
		orientation={
			"epoch": start_time,
			"unitQuaternion": []  # Will be filled with heading data
		},
		point=Point(
			color=Color(rgba=[0, 255, 255, 255]),  # Cyan
			pixelSize=8,
			outlineColor=Color(rgba=[0, 0, 0, 255]),  # Black outline
			outlineWidth=1
		)
	)

	# Initialize the packets list with document and vehicle
	packets = [document_packet, hercules_packet]

	# Add sensor data displays and event billboards
	for i, row in enumerate(data):
		timestamp = row.get('Timestamp')
		if not timestamp:
			continue

		# Only show sensor data every 5 seconds to avoid cluttering
		if i % 5 == 0:
			# Calculate slightly extended time range to make labels visible longer
			# This ensures they're visible for a few seconds instead of just an instant
			timestamp_end = datetime.strptime(timestamp, '%Y-%m-%dT%H:%M:%SZ')
			timestamp_end = (timestamp_end + timedelta(seconds=2)).strftime('%Y-%m-%dT%H:%M:%SZ')

			# Only include this data if O2_Concentration and Temperature exist
			if row.get('O2_Concentration') is not None and row.get('Temperature') is not None:
				sensor_packet = Packet(
					id=f"Sensor_{i}",
					parent="Hercules",
					availability=TimeInterval(start=timestamp, end=timestamp_end),
					position={"reference": "Hercules#position"},
					label=Label(
						text=f"O2: {row['O2_Concentration']:.2f} mg/L\nTemp: {row['Temperature']:.2f}°C",
						fillColor=Color(rgba=[255, 255, 255, 255]),  # White text
						pixelOffset={"cartesian2": [0, -30]},
						show=True,
						font="12pt sans-serif",
						horizontalOrigin="CENTER",
						verticalOrigin="BOTTOM",
						outlineWidth=2.0,
						outlineColor=Color(rgba=[0, 0, 0, 255])  # Black outline for readability
					)
				)
				packets.append(sensor_packet)

		# Add event billboards where event_value exists
		if row.get('event_value') and row.get('event_value').strip():
			event_type = row['event_value']
			event_text = row.get('event_free_text', '')
			image_path = row.get('vehicleRealtimeDualHDGrabData.filename_2_value', '')

			if not image_path:
				continue  # Skip if no image is available

			# Make event visible for a few seconds by extending the end time
			timestamp_event_end = datetime.strptime(timestamp, '%Y-%m-%dT%H:%M:%SZ')
			timestamp_event_end = (timestamp_event_end + timedelta(
				seconds=get_event_duration())).strftime('%Y-%m-%dT%H:%M:%SZ')

			# Color coding based on event type
			if event_type == "FREE_FORM":
				color = [0, 100, 0, 179]  # Dark green with 70% opacity
				scale = 0.5
			elif event_type == "HIGHLIGHT":
				color = [184, 134, 11, 179]  # Dark gold with 70% opacity
				scale = 0.6  # Slightly larger for highlighted events
			else:
				color = [255, 255, 255, 179]  # Default white with 70% opacity
				scale = 0.5

			# Create a safe ID string
			safe_timestamp = timestamp.replace(':', '').replace('-', '').replace('T', '_')
			event_id = f"Event_{event_type}_{safe_timestamp}"

			# Billboard packet for the event
			event_packet = Packet(
				id=event_id,
				parent="Hercules",
				availability=TimeInterval(start=timestamp, end=timestamp_event_end),
				position={"reference": "Hercules#position"},
				billboard=Billboard(
					image=image_path,
					scale=scale,
					color=Color(rgba=color),
					horizontalOrigin="CENTER",
					verticalOrigin="BOTTOM",
					pixelOffset={"cartesian2": [0, 0]}
				),
				label=Label(
					text=event_text,
					fillColor=Color(rgba=[255, 255, 255, 255]),  # White text
					pixelOffset={"cartesian2": [0, -50]},
					show=True,
					font="14pt sans-serif",
					horizontalOrigin="CENTER",
					verticalOrigin="BOTTOM",
					outlineWidth=2.0,
					outlineColor=Color(rgba=[0, 0, 0, 255])  # Black outline for readability
				)
			)
			packets.append(event_packet)

	# Create the CZML document from all packets
	return Document(packets)

def main(csv_file_path, output_file_path):
	"""Main function to create CZML from CSV data."""
	# Validate input path
	if not os.path.exists(csv_file_path):
		print(f"Error: Input file not found at {csv_file_path}")
		return False

	# Create output directory if it doesn't exist
	output_dir = os.path.dirname(output_file_path)
	if output_dir and not os.path.exists(output_dir):
		try:
			os.makedirs(output_dir)
			print(f"Created output directory: {output_dir}")
		except Exception as e:
			print(f"Error creating output directory: {e}")
			return False

	# Parse the CSV data
	data = parse_csv(csv_file_path)
	if not data:
		return False

	# Create the CZML document
	czml_doc = create_czml_document(data)
	if not czml_doc:
		return False

	# Write to file
	try:
		with open(output_file_path, "w") as f:
			f.write(czml_doc.dumps())
		print(f"CZML file successfully created: {output_file_path}")
		return True
	except Exception as e:
		print(f"Error writing CZML file: {e}")
		return False

if __name__ == "__main__":
	# Use the specific file paths
	input_csv = r"E:\RUMI\NAUTILUS-CRUISE-COPY2\NA156\RUMI_processed\H2021\NA156_H2021_offset.csv"
	output_czml = r"E:\RUMI\NAUTILUS-CRUISE-COPY2\NA156\RUMI_processed\H2021\NA156_H2021.czml"
	success = main(input_csv, output_czml)

	if success:
		print("CZML generation completed successfully!")
	else:
		print("CZML generation failed. Check the errors above.")