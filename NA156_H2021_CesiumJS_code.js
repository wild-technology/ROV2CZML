﻿// Set the access token
Cesium.Ion.defaultAccessToken = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJqdGkiOiJhYTJkYjIyOS1hNWFlLTRmMTAtOTU1YS1hM2YzODVlNjljMjQiLCJpZCI6MTQ4NTYyLCJpYXQiOjE3NDExMDkxMTZ9.D2HdhLSFyS5ZpnQPjSbQaawpXkNfCKzDUpks74xO-30";

(async function () {
  // Create a color ramp element for the bathymetry visualization
  const colorRampElement = document.createElement('canvas');
  colorRampElement.id = "colorRamp";
  colorRampElement.width = 100;
  colorRampElement.height = 15;
  document.body.appendChild(colorRampElement);

  // Create the viewer with bathymetry
  const viewer = new Cesium.Viewer("cesiumContainer", {
    timeline: true,
    animation: true,
    terrainProvider: await Cesium.createWorldBathymetryAsync({
      requestVertexNormals: true,
    }),
  });

  // Set to a good base layer for underwater visualization
  viewer.baseLayerPicker.viewModel.selectedImagery =
    viewer.baseLayerPicker.viewModel.imageryProviderViewModels[11];

  const scene = viewer.scene;
  const globe = scene.globe;

  // Enable lighting and high resolution terrain
  globe.enableLighting = true;
  globe.maximumScreenSpaceError = 1.0;
  globe.depthTestAgainstTerrain = false; // Let the ROV be visible through terrain

  // Prevent the user from tilting beyond the ellipsoid surface
  scene.screenSpaceCameraController.maximumTiltAngle = Math.PI / 2.0;

  // Light the scene with a hillshade effect
  scene.light = new Cesium.DirectionalLight({
    direction: new Cesium.Cartesian3(1, 0, 0), // Updated dynamically
  });

  const camera = scene.camera;
  const cameraMaxHeight = globe.ellipsoid.maximumRadius * 2;
  const scratchNormal = new Cesium.Cartesian3();

  // Update light direction based on camera position
  scene.preRender.addEventListener(function (scene, time) {
    const surfaceNormal = globe.ellipsoid.geodeticSurfaceNormal(
      camera.positionWC,
      scratchNormal,
    );
    const negativeNormal = Cesium.Cartesian3.negate(surfaceNormal, surfaceNormal);
    scene.light.direction = Cesium.Cartesian3.normalize(
      Cesium.Cartesian3.add(negativeNormal, camera.rightWC, surfaceNormal),
      scene.light.direction,
    );

    const zoomMagnitude =
      Cesium.Cartesian3.magnitude(camera.positionWC) / cameraMaxHeight;

    updateGlobeMaterialUniforms(zoomMagnitude);
  });

  // ===== Globe material setup (color ramp and contour lines) =====
  const minHeight = -10000.0;
  const seaLevel = 0.0;
  const maxHeight = 2000.0;
  const countourLineSpacing = 500.0;
  let showContourLines = true;
  let showElevationColorRamp = true;
  let invertContourLines = false;

  const range = maxHeight - minHeight;
  const d = (height) => (height - minHeight) / range;

  // Create a color ramp for ocean depths
  function getColorRamp() {
    const ramp = document.getElementById("colorRamp");
    ramp.width = 100;
    ramp.height = 15;
    const ctx = ramp.getContext("2d");
    const grd = ctx.createLinearGradient(0, 0, 100, 0);

    // Deep ocean color scale (cmocean 'deep')
    grd.addColorStop(d(maxHeight), "#B79E6C");
    grd.addColorStop(d(100.0), "#FBFFEE");
    grd.addColorStop(d(0.0), "#F9FCCA");
    grd.addColorStop(d(-500.0), "#BDE7AD");
    grd.addColorStop(d(-1000.0), "#81D2A3");
    grd.addColorStop(d(-1500.0), "#5AB7A4");
    grd.addColorStop(d(-2000.0), "#4C9AA0");
    grd.addColorStop(d(-2500.0), "#437D9A");
    grd.addColorStop(d(-4000.0), "#3E6194");
    grd.addColorStop(d(-5000.0), "#424380");
    grd.addColorStop(d(-8000.0), "#392D52");
    grd.addColorStop(d(minHeight), "#291C2F");

    ctx.fillStyle = grd;
    ctx.fillRect(0, 0, ramp.width, ramp.height);

    return ramp;
  }

  function getElevationContourMaterial() {
    // Creates a composite material with both elevation shading and contour lines
    return new Cesium.Material({
      fabric: {
        type: "ElevationColorContour",
        materials: {
          contourMaterial: {
            type: "ElevationContour",
          },
          elevationRampMaterial: {
            type: "ElevationRamp",
          },
        },
        components: {
          diffuse:
            "(1.0 - contourMaterial.alpha) * elevationRampMaterial.diffuse + contourMaterial.alpha * contourMaterial.diffuse",
          alpha: "max(contourMaterial.alpha, elevationRampMaterial.alpha)",
        },
      },
      translucent: false,
    });
  }

  function updateGlobeMaterialUniforms(zoomMagnitude) {
    const material = globe.material;
    if (!Cesium.defined(material)) {
      return;
    }

    const spacing = 5.0 * Math.pow(10, Math.floor(4 * zoomMagnitude));
    if (showContourLines) {
      const uniforms = showElevationColorRamp
        ? material.materials.contourMaterial.uniforms
        : material.uniforms;

      uniforms.spacing = spacing * scene.verticalExaggeration;
    }

    if (showElevationColorRamp) {
      const uniforms = showContourLines
        ? material.materials.elevationRampMaterial.uniforms
        : material.uniforms;
      uniforms.spacing = spacing * scene.verticalExaggeration;
      uniforms.minimumHeight = minHeight * scene.verticalExaggeration;
      uniforms.maximumHeight = maxHeight * scene.verticalExaggeration;
    }
  }

  function updateGlobeMaterial() {
    let material;
    if (showContourLines) {
      if (showElevationColorRamp) {
        material = getElevationContourMaterial();
        let shadingUniforms = material.materials.elevationRampMaterial.uniforms;
        shadingUniforms.image = getColorRamp();
        shadingUniforms.minimumHeight = minHeight * scene.verticalExaggeration;
        shadingUniforms.maximumHeight = maxHeight * scene.verticalExaggeration;
        shadingUniforms = material.materials.contourMaterial.uniforms;
        shadingUniforms.width = 1.0;
        shadingUniforms.spacing = countourLineSpacing * scene.verticalExaggeration;
        shadingUniforms.color = invertContourLines
          ? Cesium.Color.WHITE.withAlpha(0.5)
          : Cesium.Color.BLACK.withAlpha(0.5);
        globe.material = material;
        return;
      }

      material = Cesium.Material.fromType("ElevationContour");
      const shadingUniforms = material.uniforms;
      shadingUniforms.width = 1.0;
      shadingUniforms.spacing = countourLineSpacing * scene.verticalExaggeration;
      shadingUniforms.color = invertContourLines
        ? Cesium.Color.WHITE
        : Cesium.Color.BLACK;
      globe.material = material;
      return;
    }

    if (showElevationColorRamp) {
      material = Cesium.Material.fromType("ElevationRamp");
      const shadingUniforms = material.uniforms;
      shadingUniforms.image = getColorRamp();
      shadingUniforms.minimumHeight = minHeight * scene.verticalExaggeration;
      shadingUniforms.maximumHeight = maxHeight * scene.verticalExaggeration;
      globe.material = material;
      return;
    }

    globe.material = undefined;
  }

  // Set up vertical exaggeration controls
  const viewModel = {
    exaggeration: 0.5,
    minHeight: minHeight,
    maxHeight: maxHeight,
  };

  function updateExaggeration() {
    scene.verticalExaggeration = Number(viewModel.exaggeration);
    updateGlobeMaterial(); // Update the material when exaggeration changes
  }

  // Setup Knockout bindings for sliders
  Cesium.knockout.track(viewModel);
  const toolbar = document.getElementById("toolbar");
  if (toolbar) {
    Cesium.knockout.applyBindings(viewModel, toolbar);
    for (const name in viewModel) {
      if (viewModel.hasOwnProperty(name)) {
        Cesium.knockout.getObservable(viewModel, name).subscribe(updateExaggeration);
      }
    }
  }

  // Apply the initial globe material
  updateGlobeMaterial();

  // ===== Debug Panel Setup =====
  // Create a debug panel to show orientation information
  const debugPanel = document.createElement('div');
  debugPanel.id = 'debugPanel';
  debugPanel.style.position = 'absolute';
  debugPanel.style.bottom = '30px';
  debugPanel.style.right = '10px';
  debugPanel.style.padding = '10px';
  debugPanel.style.backgroundColor = 'rgba(0, 0, 0, 0.7)';
  debugPanel.style.color = 'white';
  debugPanel.style.borderRadius = '5px';
  debugPanel.style.fontFamily = 'monospace';
  debugPanel.style.fontSize = '12px';
  debugPanel.style.maxWidth = '300px';
  debugPanel.style.maxHeight = '200px';
  debugPanel.style.overflow = 'auto';
  debugPanel.innerHTML = `
    <h3>ROV Orientation Info</h3>
    <div id="orientationInfo">
      <div>Local Heading: <span id="headingValue">N/A</span>°</div>
      <div>Local Pitch: <span id="pitchValue">N/A</span>°</div>
      <div>Local Roll: <span id="rollValue">N/A</span>°</div>
      <div>Local Quaternion: <span id="quaternionValue">N/A</span></div>
      <div>Position: <span id="positionValue">N/A</span></div>
      <div>Velocity: <span id="velocityValue">N/A</span></div>
      <div>ECEF Quaternion: <span id="ecefQuaternionValue">N/A</span></div>
      <div>Debug Status: <span id="debugStatus">Initializing...</span></div>
    </div>
    <button id="visualizeDirectionBtn" style="margin-top:10px">Show Direction Vectors</button>
  `;
  document.body.appendChild(debugPanel);

  // Direction vector visualization state
  window.showDirectionVector = false;

  // Create console log element for debugging
  const consoleLog = document.createElement('div');
  consoleLog.id = 'consoleLog';
  consoleLog.style.position = 'absolute';
  consoleLog.style.top = '10px';
  consoleLog.style.left = '10px';
  consoleLog.style.padding = '10px';
  consoleLog.style.backgroundColor = 'rgba(0, 0, 0, 0.7)';
  consoleLog.style.color = 'white';
  consoleLog.style.borderRadius = '5px';
  consoleLog.style.fontFamily = 'monospace';
  consoleLog.style.fontSize = '12px';
  consoleLog.style.maxWidth = '500px';
  consoleLog.style.maxHeight = '300px';
  consoleLog.style.overflow = 'auto';
  consoleLog.style.zIndex = '1000';
  consoleLog.innerHTML = '<h3>Debug Console</h3><div id="logContent"></div>';
  document.body.appendChild(consoleLog);

  // Custom logging function that shows in both console and on-screen
  function logDebug(message, type = 'info') {
    console.log(message);
    const logContent = document.getElementById('logContent');
    if (logContent) {
      const logEntry = document.createElement('div');
      logEntry.className = `log-${type}`;
      logEntry.textContent = message;
      logContent.appendChild(logEntry);
      // Keep only the last 20 entries
      while (logContent.children.length > 20) {
        logContent.removeChild(logContent.firstChild);
      }
      // Auto-scroll to bottom
      logContent.scrollTop = logContent.scrollHeight;
    }
  }

  // Load and display the CZML
  try {
    logDebug("Starting CZML loading process...");

    // Try to load from local file first (most reliable for debugging)
    let czmlDataSource = null;
    let loadSuccess = false;

    try {
      // Direct loading of in-memory CZML data
      logDebug("Loading CZML from in-memory data...");
      const czmlData = JSON.parse(document.querySelector('[source="NA156_H2021_2025-03-14_1130.json"] [document_content]').textContent);
      czmlDataSource = new Cesium.CzmlDataSource();
      await czmlDataSource.process(czmlData);
      logDebug("Successfully loaded CZML from in-memory data");
      loadSuccess = true;
    } catch (memoryError) {
      logDebug(`Error loading from in-memory data: ${memoryError.message}`, 'error');

      // Try to load the latest CZML file with today's date
      const today = new Date().toISOString().split('T')[0]; // YYYY-MM-DD
      logDebug(`Looking for CZML file with date: ${today}`);

      // Define potential file paths to try
      const filePaths = [
        `./NA156_H2021_2025-03-14_1130.json`,
        `./NA156_H2021_${today}.czml`,
        "./NA156_H2021_manual.czml",
      ];

      logDebug("Attempting to load CZML from the following paths:", filePaths);

      // Try each file path until one works
      for (const filePath of filePaths) {
        if (loadSuccess) break;

        try {
          logDebug(`Trying to load: ${filePath}`);
          const czmlResource = new Cesium.Resource({
            url: filePath,
            proxy: new Cesium.DefaultProxy('/proxy/')
          });

          czmlDataSource = await Cesium.CzmlDataSource.load(czmlResource);
          logDebug(`Successfully loaded: ${filePath}`);
          loadSuccess = true;
        } catch (error) {
          logDebug(`Failed to load: ${filePath}`, 'error');
        }
      }

      // If no local files worked, try from Ion
      if (!loadSuccess) {
        logDebug("Local CZML not found, using Ion asset instead...");
        try {
          const ionResource = await Cesium.IonResource.fromAssetId(3216192);
          czmlDataSource = await Cesium.CzmlDataSource.load(ionResource);
          logDebug("Successfully loaded CZML from Ion");
          loadSuccess = true;
        } catch (ionError) {
          logDebug(`Failed to load from Ion: ${ionError.message}`, 'error');
        }
      }
    }

    if (!loadSuccess || !czmlDataSource) {
      throw new Error("Failed to load any CZML source");
    }

    await viewer.dataSources.add(czmlDataSource);
    logDebug("CZML added to viewer");

    // Get the Hercules entity
    const herculesEntity = czmlDataSource.entities.getById("Hercules");

    if (herculesEntity) {
      logDebug("Found Hercules entity in CZML");

      // Check if orientation is available
      if (!herculesEntity.orientation) {
        logDebug("WARNING: Hercules entity has no orientation property!", 'error');
      } else {
        logDebug("Hercules entity has orientation property");
      }

      // Use the clock settings from the CZML
      viewer.clock.multiplier = 10;

      // Log clock info
      logDebug(`Clock range: ${viewer.clock.startTime.toString()} to ${viewer.clock.stopTime.toString()}`);
      logDebug(`Current time: ${viewer.clock.currentTime.toString()}`);
      logDebug(`Clock multiplier: ${viewer.clock.multiplier}`);

      // Check initial orientation value
      try {
        const initialTime = viewer.clock.currentTime;
        const initialOrientation = herculesEntity.orientation.getValue(initialTime);
        if (initialOrientation) {
          logDebug(`Initial orientation at ${initialTime.toString()}: [${initialOrientation.x.toFixed(6)}, ${initialOrientation.y.toFixed(6)}, ${initialOrientation.z.toFixed(6)}, ${initialOrientation.w.toFixed(6)}]`);
        } else {
          logDebug("Initial orientation is null or undefined!", 'error');
        }
      } catch (orientationError) {
        logDebug(`Error getting initial orientation: ${orientationError.message}`, 'error');
      }

      // Add listener to display orientation changes
      viewer.clock.onTick.addEventListener(function () {
        const statusElement = document.getElementById('debugStatus');

        if (herculesEntity.orientation) {
          try {
            // Get the current ECEF orientation quaternion
            const orientationECEF = herculesEntity.orientation.getValue(viewer.clock.currentTime);

            if (!orientationECEF) {
              statusElement.textContent = "Orientation is null at current time";
              return;
            }

            // Update ECEF quaternion display
            document.getElementById('ecefQuaternionValue').textContent =
              `[${orientationECEF.x.toFixed(3)}, ${orientationECEF.y.toFixed(3)}, ${orientationECEF.z.toFixed(3)}, ${orientationECEF.w.toFixed(3)}]`;

            // Convert the entity position to geodetic to obtain the current local frame
            const position = herculesEntity.position.getValue(viewer.clock.currentTime);
            if (!position) {
              statusElement.textContent = "Position is null at current time";
              return;
            }

            // Use Cesium's built-in transform for local east-north-up
            const enuToEcefMatrix = Cesium.Transforms.eastNorthUpToFixedFrame(position);

            // Extract the rotation (upper 3x3) as a quaternion
            const rotationMatrix = new Cesium.Matrix3();
            Cesium.Matrix4.getMatrix3(enuToEcefMatrix, rotationMatrix);
            const q_transform = new Cesium.Quaternion();
            Cesium.Quaternion.fromRotationMatrix(rotationMatrix, q_transform);

            // The inverse of a unit quaternion is its conjugate
            const q_transform_inv = Cesium.Quaternion.conjugate(q_transform, new Cesium.Quaternion());

            // Convert the ECEF quaternion into the local ENU frame
            const q_local = new Cesium.Quaternion();
            Cesium.Quaternion.multiply(q_transform_inv, orientationECEF, q_local);

            // Extract quaternion components
            const qx = q_local.x;
            const qy = q_local.y;
            const qz = q_local.z;
            const qw = q_local.w;

            // For a pure yaw (rotation about local Z), the heading is:
            let heading = Math.atan2(
              2 * (qw * qz + qx * qy),
              1 - 2 * (qy * qy + qz * qz)
            );
            heading = heading * (180 / Math.PI); // Convert to degrees
            if (heading < 0) heading += 360;

            // Extract pitch from the local quaternion
            let pitch = Math.asin(2 * (qw * qy - qz * qx));
            pitch = pitch * (180 / Math.PI); // Convert to degrees

            // Extract roll from the local quaternion
            let roll = Math.atan2(
              2 * (qw * qx + qy * qz),
              1 - 2 * (qx * qx + qy * qy)
            );
            roll = roll * (180 / Math.PI); // Convert to degrees

            // Get position (convert from ECEF to geodetic for display)
            const geo = Cesium.Cartographic.fromCartesian(position);
            const lat = Cesium.Math.toDegrees(geo.latitude).toFixed(6);
            const lon = Cesium.Math.toDegrees(geo.longitude).toFixed(6);
            const alt = geo.height.toFixed(2);

            // Get velocity (if available)
            let velocity = "N/A";
            if (herculesEntity.velocity) {
              try {
                const vel = herculesEntity.velocity.getValue(viewer.clock.currentTime);
                if (vel) {
                  const speed = Cesium.Cartesian3.magnitude(vel);
                  velocity = speed.toFixed(2) + " m/s";
                }
              } catch (e) {
                // Velocity might not be available
              }
            }

            // Update debug panel with local heading, pitch, roll and quaternion
            document.getElementById('headingValue').textContent = heading.toFixed(1);
            document.getElementById('pitchValue').textContent = pitch.toFixed(1);
            document.getElementById('rollValue').textContent = roll.toFixed(1);
            document.getElementById('quaternionValue').textContent =
              `[${qx.toFixed(3)}, ${qy.toFixed(3)}, ${qz.toFixed(3)}, ${qw.toFixed(3)}]`;
            document.getElementById('positionValue').textContent =
              `Lat: ${lat}°, Lon: ${lon}°, Alt: ${alt}m`;
            document.getElementById('velocityValue').textContent = velocity;
            statusElement.textContent = "Updated at " + new Date().toLocaleTimeString();
          } catch (error) {
            statusElement.textContent = "Error: " + error.message;
            console.error("Error updating orientation debug:", error);
          }
        } else {
          statusElement.textContent = "No orientation property found";
        }
      });

      // Load the ROV model
      try {
        logDebug("Loading ROV model from Ion...");
        const modelResource = await Cesium.IonResource.fromAssetId(3163466);

        // Create model
        herculesEntity.model = new Cesium.ModelGraphics({
          uri: modelResource,
          scale: 0.04, // Scale to represent approximately 4 meters in length
          minimumPixelSize: 64,
          maximumScale: 20,
          runAnimations: true,
          debugShowBoundingVolume: true, // Show bounding volume for debugging
          debugWireframe: true, // Show wireframe for debugging
        });

        // Add direction arrows to visualize orientation
        let directionArrows = {
          forward: viewer.entities.add({
            name: 'Forward Direction',
            position: new Cesium.CallbackProperty(function(time) {
              return herculesEntity.position.getValue(time);
            }, false),
            orientation: new Cesium.CallbackProperty(function(time) {
              return herculesEntity.orientation.getValue(time);
            }, false),
            polyline: {
              show: new Cesium.CallbackProperty(function() {
                return window.showDirectionVector;
              }, false),
              positions: new Cesium.CallbackProperty(function(time) {
                const position = herculesEntity.position.getValue(time);
                const orientation = herculesEntity.orientation.getValue(time);
                if (!position || !orientation) return [position, position];

                // X-axis: Forward
                const headingMatrix = Cesium.Matrix3.fromQuaternion(orientation);
                const direction = new Cesium.Cartesian3(1, 0, 0);
                const rotatedDirection = Cesium.Matrix3.multiplyByVector(
                  headingMatrix, direction, new Cesium.Cartesian3()
                );

                const length = 10.0;
                const scaledDirection = Cesium.Cartesian3.multiplyByScalar(
                  rotatedDirection, length, new Cesium.Cartesian3()
                );

                const endPoint = Cesium.Cartesian3.add(
                  position, scaledDirection, new Cesium.Cartesian3()
                );

                return [position, endPoint];
              }, false),
              width: 5,
              material: new Cesium.PolylineArrowMaterialProperty(Cesium.Color.RED)
            }
          }),

          right: viewer.entities.add({
            name: 'Right Direction',
            position: new Cesium.CallbackProperty(function(time) {
              return herculesEntity.position.getValue(time);
            }, false),
            orientation: new Cesium.CallbackProperty(function(time) {
              return herculesEntity.orientation.getValue(time);
            }, false),
            polyline: {
              show: new Cesium.CallbackProperty(function() {
                return window.showDirectionVector;
              }, false),
              positions: new Cesium.CallbackProperty(function(time) {
                const position = herculesEntity.position.getValue(time);
                const orientation = herculesEntity.orientation.getValue(time);
                if (!position || !orientation) return [position, position];

                // Y-axis: Right
                const headingMatrix = Cesium.Matrix3.fromQuaternion(orientation);
                const direction = new Cesium.Cartesian3(0, 1, 0);
                const rotatedDirection = Cesium.Matrix3.multiplyByVector(
                  headingMatrix, direction, new Cesium.Cartesian3()
                );

                const length = 8.0;
                const scaledDirection = Cesium.Cartesian3.multiplyByScalar(
                  rotatedDirection, length, new Cesium.Cartesian3()
                );

                const endPoint = Cesium.Cartesian3.add(
                  position, scaledDirection, new Cesium.Cartesian3()
                );

                return [position, endPoint];
              }, false),
              width: 5,
              material: new Cesium.PolylineArrowMaterialProperty(Cesium.Color.GREEN)
            }
          }),

          up: viewer.entities.add({
            name: 'Up Direction',
            position: new Cesium.CallbackProperty(function(time) {
              return herculesEntity.position.getValue(time);
            }, false),
            orientation: new Cesium.CallbackProperty(function(time) {
              return herculesEntity.orientation.getValue(time);
            }, false),
            polyline: {
              show: new Cesium.CallbackProperty(function() {
                return window.showDirectionVector;
              }, false),
              positions: new Cesium.CallbackProperty(function(time) {
                const position = herculesEntity.position.getValue(time);
                const orientation = herculesEntity.orientation.getValue(time);
                if (!position || !orientation) return [position, position];

                // Z-axis: Up
                const headingMatrix = Cesium.Matrix3.fromQuaternion(orientation);
                const direction = new Cesium.Cartesian3(0, 0, 1);
                const rotatedDirection = Cesium.Matrix3.multiplyByVector(
                  headingMatrix, direction, new Cesium.Cartesian3()
                );

                const length = 6.0;
                const scaledDirection = Cesium.Cartesian3.multiplyByScalar(
                  rotatedDirection, length, new Cesium.Cartesian3()
                );

                const endPoint = Cesium.Cartesian3.add(
                  position, scaledDirection, new Cesium.Cartesian3()
                );

                return [position, endPoint];
              }, false),
              width: 5,
              material: new Cesium.PolylineArrowMaterialProperty(Cesium.Color.BLUE)
            }
          })
        };

        // Add click handler for direction visualization button
        document.getElementById('visualizeDirectionBtn').addEventListener('click', function() {
          window.showDirectionVector = !window.showDirectionVector;
          this.textContent = window.showDirectionVector ?
            "Hide Direction Vectors" : "Show Direction Vectors";
        });

        // Track the ROV with the camera
        viewer.trackedEntity = herculesEntity;

        // Add buttons to set specific times
        const timeControlPanel = document.createElement('div');
        timeControlPanel.style.position = 'absolute';
        timeControlPanel.style.bottom = '30px';
        timeControlPanel.style.left = '10px';
        timeControlPanel.style.padding = '10px';
        timeControlPanel.style.backgroundColor = 'rgba(0, 0, 0, 0.7)';
        timeControlPanel.style.color = 'white';
        timeControlPanel.style.borderRadius = '5px';
        timeControlPanel.innerHTML = `
          <h3>Time Controls</h3>
          <button id="startTimeBtn">Go to Start</button>
          <button id="time30Btn">Go to +30s</button>
          <button id="playpauseBtn">Play/Pause</button>
        `;
        document.body.appendChild(timeControlPanel);

        document.getElementById('startTimeBtn').addEventListener('click', function() {
          viewer.clock.currentTime = viewer.clock.startTime;
        });

        document.getElementById('time30Btn').addEventListener('click', function() {
          const newTime = Cesium.JulianDate.addSeconds(
            viewer.clock.startTime,
            30,
            new Cesium.JulianDate()
          );
          viewer.clock.currentTime = newTime;
        });

        document.getElementById('playpauseBtn').addEventListener('click', function() {
          if (viewer.clock.shouldAnimate) {
            viewer.clock.shouldAnimate = false;
            this.textContent = "Play";
          } else {
            viewer.clock.shouldAnimate = true;
            this.textContent = "Pause";
          }
        });

        // Adjust camera settings for better viewing
        viewer.trackedEntityChanged.addEventListener(function() {
          viewer.zoomTo(herculesEntity, new Cesium.HeadingPitchRange(
            0, // Use the entity's orientation for heading
            -Math.PI / 6, // Look down slightly
            15 // 15 meters range for better visibility
          ));
        });

        viewer.scene.screenSpaceCameraController.minimumZoomDistance = 2;
        viewer.scene.screenSpaceCameraController.maximumZoomDistance = 100;
      } catch (modelError) {
        logDebug(`Failed to load ROV model: ${modelError.message}`, 'error');
      }
    } else {
      logDebug("Hercules entity not found in CZML data", 'error');
    }
  } catch (err) {
    logDebug(`Error loading data: ${err.message}`, 'error');
  }

  // Add UI controls for toggling visualization features
  if (typeof Sandcastle !== 'undefined') {
    Sandcastle.addToggleButton("Lighting enabled", true, function (checked) {
      globe.enableLighting = checked;
    });
  }
})();