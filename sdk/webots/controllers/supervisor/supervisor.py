"""
Webots Supervisor controller for AI Racer platform.
Handles race state, checkpoint detection, collision detection,
telemetry recording, and IPC to car controllers via customData.
"""

import os
import json
import math
import datetime
import pathlib

from controller import Supervisor

# ---------------------------------------------------------------------------
# Init
# ---------------------------------------------------------------------------

robot = Supervisor()
timestep = int(robot.getBasicTimeStep())  # 64 ms

config_path = os.environ.get('RACE_CONFIG_PATH', 'race_config.json')
with open(config_path, encoding='utf-8') as f:
    config = json.load(f)

session_id     = config['race_id']
session_type   = config['session_type']
total_laps     = config['total_laps']
recording_path = config['recording_path']
cars_config    = config['cars']  # list of dicts

# ---------------------------------------------------------------------------
# Checkpoints
# TODO: Update checkpoint coordinates after airacer.wbt track is finalized
# ---------------------------------------------------------------------------

CHECKPOINTS = [
    {"id": 0, "cx":  0.0,  "cy":   0.0, "half_w": 4.0, "half_h": 1.0, "track_heading":  0.0},   # CP0 - start/finish
    {"id": 1, "cx": 40.0,  "cy":   0.0, "half_w": 1.0, "half_h": 4.0, "track_heading":  1.57},  # CP1
    {"id": 2, "cx": 50.0,  "cy": -40.0, "half_w": 4.0, "half_h": 1.0, "track_heading":  3.14},  # CP2
    {"id": 3, "cx":  0.0,  "cy": -40.0, "half_w": 1.0, "half_h": 4.0, "track_heading": -1.57},  # CP3
]


def in_checkpoint(x, y, cp):
    return abs(x - cp['cx']) < cp['half_w'] and abs(y - cp['cy']) < cp['half_h']


def heading_matches(heading, track_heading, tol=math.pi / 2):
    diff = abs((heading - track_heading + math.pi) % (2 * math.pi) - math.pi)
    return diff < tol


# ---------------------------------------------------------------------------
# Build car state list
# ---------------------------------------------------------------------------

cars = []
for cc in cars_config:
    node = robot.getFromDef(cc['car_slot'])
    cars.append({
        "team_id":             cc['team_id'],
        "car_slot":            cc['car_slot'],
        "team_name":           cc['team_name'],
        "node":                node,
        "x":                   0.0,
        "y":                   0.0,
        "heading":             0.0,
        "speed":               0.0,
        "lap":                 0,
        "lap_progress":        0.0,
        "status":              "normal",   # "normal" | "stopped" | "disqualified"
        "boost_remaining":     0.0,
        "checkpoint_next":     1,          # After CP0 triggers start, wait for CP1 next
        "lap_started":         False,      # True once the car has crossed CP0 for the first time
        "lap_start_time":      0.0,
        "best_lap_time":       None,
        "collision_major_count": 0,
        "stop_end_time":       None,       # sim time when stop penalty ends
        "finish_time":         None,       # sim time when car completed total_laps
        "laps_data":           [],         # list of lap times (float)
    })

# ---------------------------------------------------------------------------
# IPC helpers
# ---------------------------------------------------------------------------

def send_cmd_to_car(car, cmd_dict):
    field = car['node'].getField('customData')
    field.setSFString(json.dumps(cmd_dict))


def clear_cmd(car):
    send_cmd_to_car(car, {"cmd": "none"})

# ---------------------------------------------------------------------------
# Checkpoint logic
# ---------------------------------------------------------------------------

def check_checkpoints(car, sim_time, events):
    """
    CP0 serves as both the start trigger and the lap-complete trigger.

    State machine:
      - car['lap_started'] == False:
          Waiting for first CP0 crossing to start the lap timer.
          On crossing CP0 → set lap_started=True, record lap_start_time,
          set checkpoint_next=1.
      - car['lap_started'] == True, checkpoint_next == 1/2/3:
          Waiting for intermediate checkpoints in order.
          On crossing the expected CP → advance checkpoint_next.
      - car['lap_started'] == True, checkpoint_next == 0 (back to start/finish):
          Car has completed a full lap circuit.
          On crossing CP0 → count the lap, check for race completion.
    """
    x, y, heading = car['x'], car['y'], car['heading']
    cp_idx = car['checkpoint_next']
    cp = CHECKPOINTS[cp_idx]

    if not in_checkpoint(x, y, cp):
        return
    if not heading_matches(heading, cp['track_heading']):
        return

    if cp_idx == 0 and not car['lap_started']:
        # First crossing of start/finish line — begin lap timing
        car['lap_started'] = True
        car['lap_start_time'] = sim_time
        car['checkpoint_next'] = 1
        car['lap_progress'] = 0.0
        events.append({
            "type": "lap_start",
            "team_id": car['team_id'],
            "sim_time": round(sim_time, 3),
        })

    elif cp_idx != 0:
        # Intermediate checkpoint — progress equals the fraction already covered
        car['checkpoint_next'] = (cp_idx + 1) % len(CHECKPOINTS)
        car['lap_progress'] = cp_idx * 0.25
        events.append({
            "type": "checkpoint",
            "team_id": car['team_id'],
            "checkpoint_id": cp_idx,
            "sim_time": round(sim_time, 3),
        })

    elif cp_idx == 0 and car['lap_started']:
        # Crossed start/finish after completing the full circuit
        lap_time = sim_time - car['lap_start_time']
        car['laps_data'].append(lap_time)
        if car['best_lap_time'] is None or lap_time < car['best_lap_time']:
            car['best_lap_time'] = lap_time
        car['lap'] += 1
        car['lap_start_time'] = sim_time
        car['lap_progress'] = 0.0
        car['checkpoint_next'] = 1

        events.append({
            "type": "lap_complete",
            "team_id": car['team_id'],
            "lap_number": car['lap'],
            "lap_time": round(lap_time, 3),
            "best_lap_time": round(car['best_lap_time'], 3),
        })

        # Check if this car has finished all laps
        if car['lap'] >= total_laps and car['finish_time'] is None:
            car['finish_time'] = sim_time
            events.append({
                "type": "car_finished",
                "team_id": car['team_id'],
                "finish_time": round(sim_time, 3),
                "total_laps": car['lap'],
            })
            if session_type == "qualifying":
                # Permanently stop the car after finishing in qualifying
                send_cmd_to_car(car, {"cmd": "stop", "duration": 9999})
                car['status'] = 'stopped'

# ---------------------------------------------------------------------------
# Collision detection
# ---------------------------------------------------------------------------

def check_car_collisions(cars, sim_time, events):
    """Distance-based pairwise collision check."""
    active = [c for c in cars if c['status'] != 'disqualified']
    for i in range(len(active)):
        for j in range(i + 1, len(active)):
            ca, cb = active[i], active[j]
            dist = math.sqrt((ca['x'] - cb['x']) ** 2 + (ca['y'] - cb['y']) ** 2)
            if dist < 0.5:
                rel_speed = abs(ca['speed'] - cb['speed'])
                severity = "major" if rel_speed >= 3.0 else "minor"
                events.append({
                    "type": "collision",
                    "severity": severity,
                    "team_ids": [ca['team_id'], cb['team_id']],
                    "distance": round(dist, 3),
                    "rel_speed": round(rel_speed, 2),
                    "sim_time": round(sim_time, 3),
                })
                if severity == "major":
                    for car in (ca, cb):
                        if car['status'] == 'disqualified':
                            continue
                        car['collision_major_count'] += 1
                        if car['collision_major_count'] >= 3:
                            car['status'] = 'disqualified'
                            send_cmd_to_car(car, {"cmd": "disqualify"})
                            events.append({
                                "type": "disqualified",
                                "team_id": car['team_id'],
                                "reason": "major_collision_threshold",
                                "sim_time": round(sim_time, 3),
                            })
                        else:
                            car['status'] = 'stopped'
                            car['stop_end_time'] = sim_time + 2.0
                            send_cmd_to_car(car, {"cmd": "stop", "duration": 2.0})

    # TODO: add car vs obstacle collision detection


# ---------------------------------------------------------------------------
# Rankings
# ---------------------------------------------------------------------------

def compute_final_rankings(cars):
    finished   = sorted([c for c in cars if c['finish_time'] is not None],
                        key=lambda c: c['finish_time'])
    unfinished = sorted([c for c in cars if c['finish_time'] is None],
                        key=lambda c: (-c['lap'], -c['lap_progress']))
    ranked = finished + unfinished
    return [
        {
            "rank":       i + 1,
            "team_id":    c['team_id'],
            "team_name":  c['team_name'],
            "laps":       c['lap'],
            "best_lap":   round(c['best_lap_time'], 3) if c['best_lap_time'] is not None else None,
            "total_time": round(c['finish_time'], 3) if c['finish_time'] is not None else None,
            "status":     c['status'],
            "collision_major_count": c['collision_major_count'],
        }
        for i, c in enumerate(ranked)
    ]

# ---------------------------------------------------------------------------
# Telemetry
# ---------------------------------------------------------------------------

os.makedirs(recording_path, exist_ok=True)
telemetry_path = os.path.join(recording_path, 'telemetry.jsonl')
tel_file = open(telemetry_path, 'a', encoding='utf-8')
frame_count = 0

# Overhead camera — saves live_view.jpg every 10 steps for the admin panel
_overhead_cam = robot.getDevice("overhead_cam")
if _overhead_cam:
    _overhead_cam.enable(timestep * 10)
_FRAME_SAVE_INTERVAL = 10
_live_view_path = os.path.join(recording_path, 'live_view.jpg')


def snapshot(car):
    return {
        "team_id":         car['team_id'],
        "x":               round(car['x'], 3),
        "y":               round(car['y'], 3),
        "heading":         round(car['heading'], 4),
        "speed":           round(car['speed'], 2),
        "lap":             car['lap'],
        "lap_progress":    car['lap_progress'],
        "status":          car['status'],
        "boost_remaining": round(car['boost_remaining'], 2),
    }


def write_telemetry_frame(sim_time, cars, events):
    global frame_count
    frame = {
        "t":      round(sim_time, 3),
        "cars":   [snapshot(c) for c in cars],
        "events": events,
    }
    tel_file.write(json.dumps(frame, ensure_ascii=False) + '\n')
    tel_file.flush()
    frame_count += 1


def write_metadata(finish_reason, final_rankings):
    meta = {
        "session_id":     session_id,
        "session_type":   session_type,
        "total_laps":     total_laps,
        "recording_path": recording_path,
        "recorded_at":    datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "duration_sim":   round(robot.getTime(), 3),
        "total_frames":   frame_count,
        "teams": [
            {"team_id": c['team_id'], "team_name": c['team_name']}
            for c in cars
        ],
        "finish_reason":   finish_reason,
        "final_rankings":  final_rankings,
    }
    meta_path = os.path.join(recording_path, 'metadata.json')
    with open(meta_path, 'w', encoding='utf-8') as mf:
        json.dump(meta, mf, ensure_ascii=False, indent=2)

# ---------------------------------------------------------------------------
# Grace period / race-end state
# ---------------------------------------------------------------------------

grace_started    = False
grace_start_time = 0.0
leader_team_id   = None
race_finished    = False
finish_reason    = "supervisor_stop"
final_rankings   = []


def check_race_end(cars, sim_time, events):
    global grace_started, grace_start_time, leader_team_id
    global race_finished, finish_reason, final_rankings

    # Detect newly finished cars
    for car in cars:
        if car['lap'] >= total_laps and car['finish_time'] is not None:
            if not grace_started and session_type != "qualifying":
                grace_started    = True
                grace_start_time = car['finish_time']
                leader_team_id   = car['team_id']
                events.append({
                    "type":         "leader_finished",
                    "team_id":      car['team_id'],
                    "finish_time":  round(car['finish_time'], 3),
                    "grace_end_time": round(car['finish_time'] + 60.0, 3),
                })

    # Group race: end after 60-second grace period
    if session_type != "qualifying" and grace_started:
        if sim_time - grace_start_time >= 60.0:
            final_rankings = compute_final_rankings(cars)
            events.append({
                "type":            "race_end",
                "reason":          "grace_period_expired",
                "final_rankings":  final_rankings,
            })
            finish_reason = "grace_period_expired"
            race_finished = True

    # Qualifying: end when all cars have finished or are stopped/disqualified,
    # or when the global timeout (5 minutes) is reached.
    if session_type == "qualifying":
        QUALIFYING_TIMEOUT = 300.0  # seconds
        timed_out = sim_time >= QUALIFYING_TIMEOUT
        all_done = all(
            c['finish_time'] is not None or c['status'] in ('stopped', 'disqualified')
            for c in cars
        )
        if all_done or timed_out:
            final_rankings = compute_final_rankings(cars)
            reason = "all_cars_done" if all_done else "timeout"
            events.append({
                "type":           "race_end",
                "reason":         reason,
                "final_rankings": final_rankings,
            })
            finish_reason = reason
            race_finished = True

# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

while robot.step(timestep) != -1:
    sim_time = robot.getTime()
    events_this_frame = []

    # --- Update car states ---
    for car in cars:
        pos = car['node'].getPosition()
        car['x'], car['y'] = pos[0], pos[1]          # x/y ground plane in ENU

        ori = car['node'].getOrientation()            # row-major 3x3 rotation matrix
        car['heading'] = math.atan2(-ori[3], ori[0])

        vel = car['node'].getVelocity()               # [vx, vy, vz, wx, wy, wz]
        car['speed'] = math.sqrt(vel[0] ** 2 + vel[1] ** 2)

        # Expire stop penalty
        if car['status'] == 'stopped' and car['stop_end_time'] is not None:
            if sim_time >= car['stop_end_time']:
                car['status'] = 'normal'
                car['stop_end_time'] = None
                clear_cmd(car)

        # Drain boost timer
        if car['boost_remaining'] > 0:
            car['boost_remaining'] = max(0.0, car['boost_remaining'] - timestep / 1000.0)

    # --- Checkpoint detection (skip disqualified) ---
    for car in cars:
        if car['status'] != 'disqualified':
            check_checkpoints(car, sim_time, events_this_frame)

    # --- Collision detection ---
    check_car_collisions(cars, sim_time, events_this_frame)

    # --- Race-end check ---
    check_race_end(cars, sim_time, events_this_frame)

    # --- Write telemetry ---
    write_telemetry_frame(sim_time, cars, events_this_frame)

    # --- Save overhead camera frame every N steps ---
    if _overhead_cam and frame_count % _FRAME_SAVE_INTERVAL == 0:
        try:
            _overhead_cam.saveImage(_live_view_path, 75)
        except Exception:
            pass

    # Admin graceful-stop signal
    if not race_finished and os.path.exists(os.path.join(recording_path, 'STOP')):
        final_rankings = compute_final_rankings(cars)
        finish_reason  = "admin_stop"
        race_finished  = True

    if race_finished:
        break

# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------

tel_file.close()
write_metadata(finish_reason, final_rankings)
