# THIS DOCUMENTS SUMMARIZE ALL OUR (ALMOST-POINTLESS) EFFORT IN IMPLEMENTING A LEFT-HAND TRAFFIC (LHT) STYLE WORLD IN CARLA 0.9.15. HOWEVER, CARLA 0.9.26 (UP AND RUNNING) SOLVES THIS.

# LEFT_HAND_DRIVING_VERIFICATION

CARLA 0.9.15 does not natively support left-hand traffic maps.
Reference: https://github.com/carla-simulator/carla/issues/8124

This implementation uses Traffic Manager lane offsets to simulate left-hand driving on right-hand maps.

Purpose: Verify that left-hand (Japanese) driving is correctly configured across:
- `bosch_utils/japanese_driving_autopilot_cameras_mp.py`
- `team_code/data_agent_japanese.py`

**Summary**: Both files implement geometry-aware left-hand driving using `enforce_driving_side()` which computes a lane offset and applies it to the CARLA Traffic Manager via `global_lane_offset` and `vehicle_lane_offset(...)`. NPCs, the ego vehicle, and traffic lights are configured to obey traffic lights where possible.

**Approach**: Since CARLA maps are designed for right-hand traffic, left-hand driving is achieved by applying negative lane offsets to shift vehicles to the left side of their lanes, configuring traffic manager to enforce traffic light obedience, and ensuring all vehicles use consistent offsets.

---

## CRITICAL ISSUE: Traffic Signs & Lights Orientation

**Problem**: CARLA 0.9.15 maps (Town01-13) are designed for right-hand traffic. Traffic signs (speed limits, stop signs) and traffic light poles are oriented to face **right-hand lanes**. When vehicles drive in left lanes:
- **Traffic lights**: May only be visible from behind (light faces away)
- **Speed limit signs**: Face wrong direction (readable only from opposite lanes)
- **Stop signs**: Positioned for right-hand approach

**CARLA API Limitations**:
- `world.get_level_bbs(carla.CityObjectLabel.TrafficSigns)` returns static mesh bounding boxes but **cannot modify orientations**
- Traffic signs are baked into map geometry (not dynamic actors)
- Only traffic light **actors** can be queried via `world.get_actors().filter('traffic.traffic_light')`
- Traffic light **poles and housings** are static meshes and cannot be rotated at runtime

**Attempted Solutions**:
1. **Flip static signs**: Not supported—CARLA does not expose API to rotate static map objects
2. **Respawn traffic lights**: Traffic lights are tied to map topology (OpenDRIVE); destroying/respawning breaks junction logic
3. **Mirror detection workaround**: Detect when ego is in left lane and infer sign/light states from road topology (implemented below)
4. **Moving the movable**: Physically relocate traffic lights and signs to face left-hand lanes for proper camera visibility. `flip_world_infrastructure_for_lht()`
    ```python
    moveable_types = ['traffic.traffic_light', 'traffic.stop', 'traffic.yield']
    moveable_count = 0
    for actor in all_actors:
        if any(t_type in actor.type_id for t_type in moveable_types):
            transform = actor.get_transform()

            transform.location.y *= -1
            transform.rotation.yaw = (transform.rotation.yaw + 180) % 360
            actor.set_transform(transform)
            moveable_count += 1
    ```

**Implemented**: 
1) [DEBUG] `detect_traffic_infrastructure_issues()`
- Scans all traffic lights within 50m of ego vehicle
- Checks if light's forward vector is facing **away** from ego (dot product < 0)
- Logs warnings for back-facing lights (potential missed detections)
- Uses map topology to infer correct light state even when visual is obscured
- **Limitation**: Does not solve training data quality issue; vision models still see wrong angles
2) [REAL] `flip_world_infrastructure_for_lht()` via `export FLIP_INFRASTRUCTURE=1`.
1. Movable actors (traffic lights, stop/yield): Mirror Y-position and rotate 180°
2. Static landmarks (speed limit signs): Spawn new actors at mirrored positions
3. Tracks spawned actors in `self._flipped_actors` for cleanup
*Benefits:*
- RGB images show front-facing signals (colored lens visible)
- Vision models learn correct associations
- Dramatically improved training data quality
*Trade-offs:*
- Traffic Manager may ignore relocated signals (uses OpenDRIVE topology)
- Y-axis mirroring assumes map symmetry (works for Town01-03, may fail for others)
- Not reversible; happens once at initialization

## Per-Frame Signal Metadata collection (`left_signal/`)
Collect per-frame metadata about traffic infrastructure orientation for post-processing, training data filtering, and model interpretability.

```
dataset/
├── rgb/
├── .../
└── left_signal/         
    ├── 0000.json.gz
    └── ...
```

**Field Descriptions**:
- `frame`: Frame number (0-indexed, matches rgb/boxes/measurements)
- `timestamp`: ISO 8601 timestamp of data collection
- `ego_position`: Ego vehicle 3D position [x, y, z] in world coordinates
- `ego_rotation`: Ego vehicle rotation [pitch, yaw, roll] in degrees
- `back_facing_count`: Number of signals facing away from ego (dot < -0.3)
- `signals`: Array of all traffic infrastructure within 50m:
  - `id`: CARLA actor ID (unique per simulation run, -1 for static signs)
  - `type`: **"traffic_light"** or **"traffic_sign"**
  - `subtype`: "traffic_light", "unknown_sign", or (future) "speed_limit", "stop_sign"
  - `position`: 3D world coordinates [x, y, z]
  - `distance`: Euclidean distance from ego to signal (meters)
  - `facing_dot`: **CRITICAL FIELD** - Dot product of signal forward vector and (ego - signal) vector
    - **+0.7 to +1.0**: Signal FACES ego directly (**colored lens/text VISIBLE** in camera images)
    - **+0.3 to +0.7**: Signal at angle (partially visible, may be readable)
    - **-0.3 to +0.3**: Signal perpendicular (side view, poor visibility)
    - **-1.0 to -0.3**: Signal FACES AWAY (**approaching from BACK**, only metal housing visible, **NO colored lens/text**)
    - **null**: Orientation unknown (static sign, no actor transform available)
  - `is_back_facing`: Boolean flag (true if `facing_dot < -0.3`, i.e., approaching from behind)
  - `visible_from_ego`: Boolean flag (true if `facing_dot > 0.3`, i.e., facing toward ego with reasonable angle)
  - `state`: Traffic light state ("Red", "Green", "Yellow", "Unknown", "N/A" for signs)
  - `approaching_from`: **"front"** (visible), **"side"** (poor angle), **"back"** (**NOT visible**), or **"unknown"**

**CRITICAL: Approaching from Back**

When `approaching_from: "back"` (or `facing_dot < -0.3`):
- **Traffic Lights**: Camera images show **ONLY the metal housing and wiring on the back**—colored lens (red/green/yellow) is **NOT VISIBLE**
- **Speed Limit Signs**: Camera images show **blank back side**—speed number text is **NOT VISIBLE**
- **Stop Signs**: Camera images show **back of octagonal pole**—"STOP" text is **NOT VISIBLE**

**Use Cases**:
1. **Training Data Filtering**: 
   - Remove frames where `visible_from_ego: false` for any critical signals
   - Filter out frames with `approaching_from: "back"` near intersections
   - Keep only frames where `facing_dot > 0.3` for traffic light detection tasks
2. **Model Debugging**: 
   - Correlate poor traffic light predictions with `is_back_facing=true`
   - Identify systematic failures when `approaching_from: "back"`
3. **Sign Type Detection**:
   - Distinguish between `type: "traffic_light"` (dynamic actors) and `type: "traffic_sign"` (static meshes)
   - Note: `traffic_sign` entries have `facing_dot: null` (orientation unknown in CARLA 0.9.15)

### Detection Method Details

This funtion `detect_traffic_infrastructure_issues(max_distance=50.0)`
- **Location**: `japanese_driving_autopilot_cameras_*.py, data_agent_japanese.py`
- **Output Example** (init):
  ```
  [WARN]: Detected 3 back-facing traffic lights within 50m
  [WARN]: Traffic signs/lights are oriented for RIGHT-hand traffic in CARLA 0.9.15 maps
  [WARN]: Consider upgrading to CARLA 0.9.16+ for native left-hand traffic support
  [WARN]:   Traffic light at (123.4, 56.7) faces AWAY from ego (dist=15.2m, state=Red)
  ```
---

## ENFORCING THE LEFT SIDE GUIDANCE 

I will list here all the strategy implemented to create a left-driving scenario.

**1) bosch_utils/japanese_driving_autopilot_cameras_mp.py**

- `setup_left_hand_traffic()` (Line 461-477)
  - Parameters:
    - `set_global_distance_to_leading_vehicle(2.5)` meters
    - Calls `enforce_driving_side(side='left', margin=0.10)`
    - Fallback: `global_lane_offset = -0.8` meters

- `enforce_driving_side(side='left', margin=0.10)` (Line 479-575)
  - Input Parameters:
    - `side` = 'left' (or 'right')
    - `margin` = 0.10 meters (clearance from curb)
  - Computed Values:
    - `dir_sign` = -1.0 for left, 1.0 for right
    - `lane_w` = 3.5 meters (default fallback) or queried from waypoint
    - `vehicle_half_w` = 0.9 meters (default) or from bounding_box.extent.y
    - `max_safe` = max(0.02, lane_w / 2.0 - 0.02)
    - `desired` = dir_sign * (lane_w / 2.0 - vehicle_half_w - margin)
  - Safety Constraints:
    - Clamped to [-max_safe, +max_safe]
    - Hard limit: [-2.5, +2.5] meters
    - Must be finite (checked with math.isfinite())
  - Applied To:
    - `traffic_manager.global_lane_offset = desired`
    - `traffic_manager.vehicle_lane_offset(player_vehicle, desired)` if vehicle exists
    - `traffic_manager.ignore_lights_percentage(player_vehicle, 0)` obey all lights
  - Stored: `self._driving_side_offset = desired`

- `detect_traffic_infrastructure_issues(max_distance=50.0)` (NEW - added after enforce_driving_side)
  - **Purpose**: Detect traffic lights facing away from ego vehicle (back-facing)
  - **Method**: Compute dot product between light's forward vector and ego direction
  - **Threshold**: dot < -0.3 indicates back-facing (angle > ~107°)
  - **Returns**: dict with `back_facing_lights` (count) and `warnings` (list)
  - **Called**: After `spawn_player_vehicle()` and autopilot enabled
  - **Logs**: Warnings for first 3 back-facing lights with location, distance, state

- `spawn_npc_vehicles(num_vehicles=30)` (Line 949-993)
  - NPC Configuration:
    - Uses stored `self._driving_side_offset` or computes via `enforce_driving_side()`
    - Fallback: -0.8 meters if computation fails
    - Per-NPC: `traffic_manager.vehicle_lane_offset(vehicle, offset)`
    - Traffic lights: `traffic_manager.ignore_lights_percentage(vehicle, 0)` obey

- `spawn_player_vehicle()` (Line 1052-1176)
  - Ego Vehicle Configuration:
    - `ego_offset = getattr(self, '_driving_side_offset', -1.5)` meters
    - `traffic_manager.vehicle_lane_offset(player_vehicle, ego_offset)`
    - `traffic_manager.ignore_lights_percentage(player_vehicle, 0)` obey
  - **NEW**: Calls `detect_traffic_infrastructure_issues()` after autopilot enabled

---

**2) team_code/data_agent_japanese.py**

- Initial Values (Line 208-210)
  - `self.enforce_left_hand_traffic = True` flag
  - `self._driving_side_offset = -1.5` meters (initial, overwritten by enforce_driving_side)

- `_init(hd_map)` (Line 290-317)
  - Called AFTER vehicle spawn in leaderboard lifecycle
  - Parameters:
    - `tm.set_global_distance_to_leading_vehicle(2.5)` meters
    - Calls `enforce_driving_side(side='left', margin=0.10)`
    - Fallback: `self._driving_side_offset = -0.8` meters

- `enforce_driving_side(side='left', margin=0.10)` (Line 332-420)
  - Input Parameters:
    - `side` = 'left' (or 'right')
    - `margin` = 0.10 meters
  - Computed Values:
    - `dir_sign` = -1.0 for left, 1.0 for right
    - `lane_w` = 3.5 meters (default) or queried from waypoint
    - `vehicle_half_w` = 0.9 meters (default) or from self._vehicle.bounding_box.extent.y
    - `max_safe` = max(0.02, lane_w / 2.0 - 0.02)
    - `desired` = dir_sign * (lane_w / 2.0 - vehicle_half_w - margin)
  - Safety Constraints:
    - Clamped to [-max_safe, +max_safe]
    - Hard limit: [-2.5, +2.5] meters
    - Must be finite (checked with math.isfinite())
  - Applied To:
    - `self.tm.global_lane_offset = desired`
    - `self.tm.vehicle_lane_offset(self._vehicle, desired)` if vehicle exists
    - `self.tm.ignore_lights_percentage(self._vehicle, 0)` obey all lights
  - Stored: `self._driving_side_offset = desired`
  - Returns: `desired` offset value

---

**3) Typical Computed Values**

For standard CARLA lanes (3.5m wide) and vehicles (0.9m half-width):
- Formula: -1.0 * (3.5/2 - 0.9 - 0.10) = -1.0 * (1.75 - 1.0) = -0.75 meters
- Actual range observed: -0.75 to -1.5 meters depending on map geometry and vehicle size
- Negative values shift vehicles LEFT of lane center for left-hand driving simulation

**4) Traffic lights and scene-level behavior** 

_PLEASE REFER_

- Both implementations set `ignore_lights_percentage(vehicle, 0)`:
  - 0 = obey all traffic lights (no violations)
  - Applied to ego vehicle and all NPCs
  - Ensures coherent traffic behavior
- Global TM config: `set_global_distance_to_leading_vehicle(2.5)` meters in both files



**5) Limitations and Visibility Issues**

CARLA 0.9.15 maps are designed for right-hand traffic:
- Traffic light positioning assumes right-hand flow
- Intersection geometry optimized for right turns
- Lane markings and road signs oriented for right-hand driving
- This implementation uses lane offsets as a workaround but does not modify map geometry

**Specific Visibility Problems:**

Traffic Lights:
- Positioned for right-hand traffic (right side of lane or overhead)
- When vehicles shift left via lane offset, lights may be at suboptimal camera angles
- May be occluded by other vehicles or infrastructure from left-driving perspective
- CARLA API can still detect them but camera sensors may have reduced visibility
- Not realistically positioned for left-hand driver viewpoint

Street Signs:
- Face right-hand traffic flow
- Left-driving vehicles may have poor visibility or unnatural viewing angles
- Signs on the "wrong" side of road for left-hand perspective

**Proper Solution (Requires CARLA Upgrade):**

GitHub PR #8951 adds native LHT support via OpenDRIVE `rule="LHT"`:
https://github.com/carla-simulator/carla/pull/8951
- Requires CARLA 0.9.16 or later (current version: 0.9.15)
- Maps must have `rule="LHT"` in OpenDRIVE XML road definitions
- Properly flips: traffic lights, signs, lane markings, intersection geometry, turn priorities
- Example: `<road name="Road 0" id="0" junction="-1" rule="LHT">`

**Current Approach Trade-offs:**

Sufficient for:
- Data collection where CARLA API detects traffic lights/signs regardless of position
- Training models that rely on semantic detection rather than realistic camera views
- Lane-following behavior and basic traffic scenarios

Not suitable for:
- Realistic camera-based perception training (traffic lights/signs at wrong angles)
- Complex intersection behavior requiring proper turn geometry
- Human-in-loop simulation expecting realistic left-hand driver viewpoint



---
---

# Verifying the correct waypoints [SOLVED]

## Own pipeline

```bash
bash script/run_carla_mp_pilot_script.sh --mode autopilot --duration 5 --route urban --town Town02 --weather SoftRainNight --spawn-index 12 --autopilot-long --fps 20

<...>

[INFO]: Initializing GlobalRoutePlanner (alternate mode, dense sampling)...
[DEBUG] get_predefined_route2: enforce_left_hand_traffic=True
[DEBUG] Calling _verify_and_correct_route_for_left_hand_traffic with 1733 waypoints
[DEBUG] _verify_and_correct_route_for_left_hand_traffic ENTERED (got 1733 waypoints)
[INFO] Route already aligned with left-hand traffic

<...>
```
## From simlingo pipeline

```bash
bash script/test_data_agent_japanese.sh
<...>
[INFO][DATA_AGENT_JAPANESE] Created output directories in: /workspace/simlingo/database/simlingo_v4_bosch_2025_01_10/data/simlingo/training_3_scenarios/routes_devtest/test_clear_noon/Town03_Rep0_0_route0_01_09_11_40_14
> Running the route
=== [Agent] -- Wallclock = 2026-01-09 11:40:19.356 -- System time = 0.000 -- Game time = 0.050 -- Ratio = 0.000x
Sparse Waypoints: 103
Dense Waypoints: 8058
[DEBUG] data_agent_japanese._init called
[DEBUG] Left-hand traffic enforcement enabled, calling route verification...
[DEBUG] _verify_and_correct_route_for_left_hand_traffic ENTERED
[DEBUG] Has _waypoint_planner: True
[DEBUG] Has route_waypoints: True
[DEBUG] Route waypoints count: 81115
[INFO] Route waypoint 1996: switched from lane 2 to left lane 1 (road 321)
[INFO] Route waypoint 1997: switched from lane 2 to left lane 1 (road 321)
[INFO] Route waypoint 1998: switched from lane 2 to left lane 1 (road 321)
[INFO] Route waypoint 40555: switched from lane 2 to left lane 1 (road 11728)
[INFO] Route waypoint 48666: switched from lane 2 to left lane 1 (road 8763)
[INFO] Route waypoint 81110: switched from lane -2 to left lane -1 (road 242)
[INFO] Left-hand traffic route correction: adjusted 24433/81115 waypoints to use left lanes
[INFO] Route points array regenerated with 81115 corrected waypoints
[INFO] Ego vehicle: road_id=529, lane_id=-1, offset=-1.50m
[DATA_AGENT_JAPANESE] Starting to save data at frame 0
  RGB output: /workspace/simlingo/database/simlingo_v4_bosch_2025_01_10/data/simlingo/training_3_scenarios/routes_devtest/test_clear_noon/Town03_Rep0_0_route0_01_09_11_40_14/rgb/0000/
  Total frames will be saved to: /workspace/simlingo/database/simlingo_v4_bosch_2025_01_10/data/simlingo/training_3_scenarios/routes_devtest/test_clear_noon/Town03_Rep0_0_route0_01_09_11_40_14
=== [Agent] -- Wallclock = 2026-01-09 11:40:46.497 -- System time = 27.141 -- Game time = 0.100 -- Ratio = 0.004x
=== [Agent] -- Wallclock = 2026-01-09 11:40:47.126 -- System time = 27.770 -- Game time = 0.150 -- Ratio = 0.005x
<...>
```

# Migrating to carla-0.9.16 [NEXT STEP]

## Differences

**1. Python API Egg File**
Scripts reference carla-0.9.15-py3.7-linux-x86_64.egg
Must update PYTHONPATH exports in:
start_eval_simlingo.py
setup scripts, test scripts

**2. Docker Image Updates**
Current: carla-bench2drive:0.9.15
Need to rebuild/retag for 0.9.16
Affects `test_data_agent_japanese.sh, run_carla_mp_pilot_script.sh`

**3. API Compatibility**
CARLA 0.9.16 may have API changes/deprecations
Test your traffic manager calls, sensor spawning, map queries
Most common breaking changes: sensor blueprints, actor attributes

**4. Maps & OpenDRIVE**
This is your main benefit: Access to maps with `rule="LHT"` for proper left-hand traffic
May need to download/generate updated map files
Check if Bench2Drive maps have 0.9.16 versions

**5. Leaderboard/ScenarioRunner**
Match versions: ScenarioRunner must match CARLA version (per docs)
May need updated branches from CARLA repos

## Migration Steps
```bash
# 1. Download CARLA 0.9.16
wget https://carla-releases.s3.us-east-005.backblazeb2.com/Linux/CARLA_0.9.16.tar.gz
tar -xzf CARLA_0.9.16.tar.gz -C /path/to/carla0916/

# 2. Update environment
export CARLA_ROOT=/path/to/carla0916
export PYTHONPATH=$PYTHONPATH:${CARLA_ROOT}/PythonAPI/carla/dist/carla-0.9.16-py3.7-linux-x86_64.egg

# 3. Update Python client
pip install carla==0.9.16  # if using pip-installed client

# 4. Test basic connection
python -c "import carla; c=carla.Client('localhost',2000); print(c.get_server_version())"
```
