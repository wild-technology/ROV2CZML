      <div id="cesiumContainer"></div>
          <script type="module">

      // Set the access token
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

    //Removed Setup Knockout bindings for sliders


    // Apply the initial globe material
    updateGlobeMaterial();
    

    // ===== Debug Panel Setup =====
    // Create a debug panel to show orientation information
    const rovOrientationInfo = document.createElement('div');
    rovOrientationInfo.id = 'rovOrientationInfo';
    rovOrientationInfo.style.position = 'absolute';
    rovOrientationInfo.style.bottom = '30px';
    rovOrientationInfo.style.right = '10px';
    rovOrientationInfo.style.padding = '10px';
    rovOrientationInfo.style.backgroundColor = 'rgba(0, 0, 0, 0.7)';
    rovOrientationInfo.style.color = 'white';
    rovOrientationInfo.style.borderRadius = '5px';
    rovOrientationInfo.style.fontFamily = 'monospace';
    rovOrientationInfo.style.fontSize = '12px';
    rovOrientationInfo.style.maxWidth = '300px';
    rovOrientationInfo.style.maxHeight = '200px';
    rovOrientationInfo.style.overflow = 'auto';
    rovOrientationInfo.innerHTML = `
      <h3>ROV Orientation Info</h3>
      <div id="orientationInfo">
        <div>Heading: <span id="headingValue">N/A</span>°</div>
        <div>Quaternion: <span id="quaternionValue">N/A</span></div>
        <div>Position: <span id="positionValue">N/A</span></div>
        <div>Velocity: <span id="velocityValue">N/A</span></div>
      </div>
      <button id="visualizeDirectionBtn" style="margin-top:10px">Show Direction Vector</button>
    `;
    document.body.appendChild(rovOrientationInfo);
    
        // ===== Information Setup =====
    // Create second Panel for Comments aditional data above ROV panel
    const infoPanel = document.createElement('div');
    infoPanel.id = 'rovOrientationInfo';
    infoPanel.style.position = 'absolute';
    infoPanel.style.bottom = '210px';
    infoPanel.style.right = '10px';
    infoPanel.style.padding = '10px';
    infoPanel.style.backgroundColor = 'rgba(0, 0, 0, 0.7)';
    infoPanel.style.color = 'white';
    infoPanel.style.borderRadius = '5px';
    infoPanel.style.fontFamily = 'monospace';
    infoPanel.style.fontSize = '12px';
    infoPanel.style.maxWidth = '300px';
    infoPanel.style.maxHeight = '200px';
    infoPanel.style.overflow = 'auto';
    infoPanel.innerHTML = `
      <h3>ROV Sensor Info</h3>
      <div id="orientationInfo">
        <div>Temperature: <span id="tempValue">N/A</span>°</div>
        <div>Oxygen Levels: <span id="oxyLevel">N/A</span> mg/L</div>
        <div>Comments: <span id="comments">N/A</span></div>
      </div>
      <button id="visualizeDirectionBtn" style="margin-top:10px">Show Direction Vector</button>
    `;
    document.body.appendChild(infoPanel);

    // Direction vector visualization state
    window.showDirectionVector = false;

    // Load and display the CZML
    try {
      // Try to load the latest CZML file with today's date
      const today = new Date().toISOString().split('T')[0]; // YYYY-MM-DD
      console.log(`Looking for CZML file with date: ${today}`);

      // Define potential file paths to try
      const filePaths = [
        `./NA156_H2021_${today}.czml`,
        "./NA156_H2021_manual.czml",
        // Add any other potential file names here
      ];

      console.log("Attempting to load CZML from the following paths:", filePaths);

      let czmlDataSource = null;
      let loadSuccess = false;

      // Try each file path until one works
      for (const filePath of filePaths) {
        if (loadSuccess) break;

        try {
          console.log(`Trying to load: ${filePath}`);
          const czmlResource = new Cesium.Resource({
            url: filePath,
            proxy: new Cesium.DefaultProxy('/proxy/')
          });

          czmlDataSource = await Cesium.CzmlDataSource.load(czmlResource);
          console.log(`Successfully loaded: ${filePath}`);
          loadSuccess = true;
        } catch (error) {
          console.log(`Failed to load: ${filePath}`, error);
        }
      }

      // If no local files worked, try from Ion
      if (!loadSuccess) {
        console.log("Local CZML not found, using Ion asset instead...");
        const ionResource = await Cesium.IonResource.fromAssetId(3216366);
        czmlDataSource = await Cesium.CzmlDataSource.load(ionResource);
        console.log("Successfully loaded CZML from Ion");
        loadSuccess = true;
      }

      if (!loadSuccess || !czmlDataSource) {
        throw new Error("Failed to load any CZML source");
      }

      await viewer.dataSources.add(czmlDataSource);
      console.log("CZML added to viewer");

      // Get the Hercules entity
      const herculesEntity = czmlDataSource.entities.getById("Hercules");

      if (herculesEntity) {
        console.log("Found Hercules entity in CZML");
        // Use the clock settings from the CZML
        viewer.clock.multiplier = 10;

        // Add listener to display orientation changes
        viewer.clock.onTick.addEventListener(function() {
          if (herculesEntity.orientation) {
            try {
              // Get current orientation
              const orientation = herculesEntity.orientation.getValue(viewer.clock.currentTime);
              if (orientation) {
                // Convert quaternion to heading
                const qx = orientation.x;
                const qy = orientation.y;
                const qz = orientation.z;
                const qw = orientation.w;

                // Calculate heading from quaternion
                // For a heading-only quaternion (rotation around z-axis), this formula works:
                let heading = Math.atan2(2 * (qw * qz + qx * qy), 1 - 2 * (qy * qy + qz * qz));
                heading = heading * (180 / Math.PI); // Convert to degrees
                if (heading < 0) heading += 360; // Normalize to 0-360

                // Get position
                const position = herculesEntity.position.getValue(viewer.clock.currentTime);
                const cartographic = Cesium.Cartographic.fromCartesian(position);
                const lat = Cesium.Math.toDegrees(cartographic.latitude).toFixed(6);
                const lon = Cesium.Math.toDegrees(cartographic.longitude).toFixed(6);
                const alt = cartographic.height.toFixed(2);

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

                // Update debug panel
                document.getElementById('headingValue').textContent = heading.toFixed(1);
                document.getElementById('quaternionValue').textContent =
                  `[${qx.toFixed(3)}, ${qy.toFixed(3)}, ${qz.toFixed(3)}, ${qw.toFixed(3)}]`;
                document.getElementById('positionValue').textContent =
                  `Lat: ${lat}°, Lon: ${lon}°, Alt: ${alt}m`;
                document.getElementById('velocityValue').textContent = velocity;

                //Get the temperature from the file TEST
                czmlDataSource.then(function(dataSource){

                const entities = dataSource.entities.values;

                let o2Text = "O2 level not found.";
                entities.forEach(function(entity) {
                    if (entity.label && entity.label.text) {
                        const text = entity.label.text;
                        const o2Regex = /O2:\s([0-9.]+)\smg\/L/;
                        const match = text.match(o2Regex);
                        if (match && match[1]) {
                            // If O2 value is found, update o2Text
                            o2Text = `The O2 level is: ${match[1]} mg/L`;
                        }
                    }
                }
              )
              }
            )
                ;
              
                //const comments;
                
              
               //document.getElementById('tempValue').textContent;
               document.getElementById('oxyLevel').textContent = oxygen;
               // document.getElementById('comment').textContent;

                // Store heading history to detect changes
                const headingHistory = window.headingHistory || [];
                if (headingHistory.length === 0 ||
                    Math.abs(headingHistory[headingHistory.length-1] - heading) > 5) {
                  headingHistory.push(heading);
                  if (headingHistory.length > 10) headingHistory.shift();
                  window.headingHistory = headingHistory;

                  // Log significant heading changes
                  if (headingHistory.length > 1) {
                    const prevHeading = headingHistory[headingHistory.length-2];
                    const headingChange = Math.abs(heading - prevHeading);
                    const normalizedChange = Math.min(headingChange, 360-headingChange);
                    if (normalizedChange > 30) {
                      console.log(`Significant heading change: ${prevHeading.toFixed(1)}° → ${heading.toFixed(1)}° (Δ${normalizedChange.toFixed(1)}°)`);
                    }
                  }
                }
              }
            } catch (error) {
              console.error("Error updating orientation debug:", error);
            }
          }
        });

        
        // Load the ROV model
        try {
          console.log("Loading ROV model from Ion...");
          const modelResource = await Cesium.IonResource.fromAssetId(3163466);

          // Create model with manual orientation adjustment
          herculesEntity.model = new Cesium.ModelGraphics({
            uri: modelResource,
            scale: 0.04, // Scale to represent approximately 4 meters length
            minimumPixelSize: 64,
            maximumScale: 20,
            runAnimations: true,
          });

          // Add a direction arrow to visualize heading
          let directionArrow = viewer.entities.add({
            name: 'Direction Vector',
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

                // Create a direction vector pointing "forward" from the ROV
                // Convert quaternion to heading direction
                const headingMatrix = Cesium.Matrix3.fromQuaternion(orientation);
                const direction = new Cesium.Cartesian3(1, 0, 0);  // "forward" direction
                const rotatedDirection = Cesium.Matrix3.multiplyByVector(
                  headingMatrix, direction, new Cesium.Cartesian3()
                );

                // Scale the direction vector
                const length = 10.0;  // 10 meters
                const scaledDirection = Cesium.Cartesian3.multiplyByScalar(
                  rotatedDirection, length, new Cesium.Cartesian3()
                );

                // Calculate endpoint
                const endPoint = Cesium.Cartesian3.add(
                  position, scaledDirection, new Cesium.Cartesian3()
                );

                return [position, endPoint];
              }, false),
              width: 5,
              material: new Cesium.PolylineArrowMaterialProperty(
                Cesium.Color.YELLOW
              )
            }
          });

          // Add click handler for direction visualization button
          document.getElementById('visualizeDirectionBtn').addEventListener('click', function() {
            window.showDirectionVector = !window.showDirectionVector;
            this.textContent = window.showDirectionVector ?
              "Hide Direction Vector" : "Show Direction Vector";
          });

          // Track the ROV with the camera
          viewer.trackedEntity = herculesEntity;

          // Add a better camera position relative to the ROV
          viewer.trackedEntityChanged.addEventListener(function() {
            viewer.zoomTo(herculesEntity, new Cesium.HeadingPitchRange(
              0, // Use the entity's orientation for heading
              -Math.PI/6, // Look down slightly
              15 // 15 meters range for better visibility
            ));
          });

          // Adjust camera settings for better viewing
          viewer.scene.screenSpaceCameraController.minimumZoomDistance = 2;
          viewer.scene.screenSpaceCameraController.maximumZoomDistance = 100;
        } catch (modelError) {
          console.error("Failed to load ROV model:", modelError);
        }
      } else {
        console.error("Hercules entity not found in CZML data");
      }
    } catch (err) {
      console.error("Error loading data:", err);
    }

    // Add UI controls for toggling visualization features
    if (typeof Sandcastle !== 'undefined') {
      Sandcastle.addToggleButton("Lighting enabled", true, function (checked) {
        globe.enableLighting = checked;
      });

    } else {
      };

  })();
  