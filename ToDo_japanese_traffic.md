# Japanese Traffic Management (left-hand driving)

This project configures CARLA's Traffic Manager to emulate Japanese-style (left-hand) traffic. Below explains how it is implemented and how to change it.

- Where it's configured: `japanese_driving_autopilot.py` in the `setup_left_hand_traffic()` and `spawn_npc_vehicles()` functions.
- Key settings used:
  - `traffic_manager.global_lane_offset = -1.5` — applies a global lateral lane offset (negative shifts vehicles left).
  - `traffic_manager.vehicle_lane_offset(vehicle, -1.5)` — applies the same offset per vehicle after spawn.
  - `traffic_manager.set_global_distance_to_leading_vehicle(2.5)` — sets following distance.
  - `traffic_manager.ignore_lights_percentage(vehicle, 0)` — set to `0` to obey traffic lights (set to higher to have NPCs ignore lights sometimes).

- NPC spawning: `spawn_npc_vehicles(num_vehicles=30)` spawns vehicles at map spawn points, sets autopilot linking them to the Traffic Manager, and sets the lane offset. To reduce traffic set `num_vehicles` lower or add a CLI flag `--npc 0` to disable.

- Player vehicle: `spawn_player_vehicle()` sets the player to autopilot via the Traffic Manager, applies the same lane offset, and optionally calls `traffic_manager.set_path()` to follow a route. This enforces left-side driving for the ego vehicle as well.

- How to tweak quickly:
  - Reduce NPCs: change `num_vehicles` or add CLI `--npc 0`.
  - Change lane offset: set `global_lane_offset` and `vehicle_lane_offset` to `+1.5` for right-hand driving, or change magnitude to adjust centering.
  - Traffic behavior: tune `ignore_lights_percentage`, `set_global_distance_to_leading_vehicle`, or per-vehicle speed/behavior attributes via the Traffic Manager API.

- Disable NPCs entirely (example): in `setup_left_hand_traffic()` replace `self.spawn_npc_vehicles(num_vehicles=30)` with `self.spawn_npc_vehicles(num_vehicles=0)` or comment out the call.


