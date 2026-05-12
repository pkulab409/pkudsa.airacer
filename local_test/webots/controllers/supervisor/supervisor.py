"""
Webots Supervisor controller (local_test copy).
This is a trimmed copy of the project's supervisor controller; it expects a
`RACE_CONFIG_PATH` environment variable pointing to a JSON config file. For
local standalone runs the runner will generate a minimal `race_config.json`.
"""

import os
import json
import math
import datetime

from controller import Supervisor

# ---------------------------------------------------------------------------
# Init
# ---------------------------------------------------------------------------

robot = Supervisor()
timestep = int(robot.getBasicTimeStep())

config_path = os.environ.get('RACE_CONFIG_PATH', 'race_config.json')
with open(config_path, encoding='utf-8') as f:
    config = json.load(f)

session_id     = config['race_id']
session_type   = config.get('session_type', 'test')
total_laps     = config.get('total_laps', 1)
recording_path = config['recording_path']
cars_config    = config['cars']

# Checkpoints (same defaults used by original supervisor)
CHECKPOINTS = [
    {"id": 0, "cx": 56.0,  "cy": -29.0, "half_w": 4.0, "half_h": 1.0, "track_heading": 0.0},
    {"id": 1, "cx": 199.0, "cy": 0.0,   "half_w": 4.0, "half_h": 1.0, "track_heading": 1.57},
    {"id": 2, "cx": 199.0, "cy": 103.0, "half_w": 4.0, "half_h": 1.0, "track_heading": 1.57},
    {"id": 3, "cx": 158.0, "cy": 160.0, "half_w": 4.0, "half_h": 1.0, "track_heading": 3.14},
    {"id": 4, "cx": 92.0,  "cy": 159.0, "half_w": 4.0, "half_h": 1.0, "track_heading": -1.57},
    {"id": 5, "cx": 47.5,  "cy": 60.0,  "half_w": 4.0, "half_h": 1.0, "track_heading": -1.57},
    {"id": 6, "cx": -5.0,  "cy": 150.0, "half_w": 4.0, "half_h": 1.0, "track_heading": 3.14},
    {"id": 7, "cx": -22.0, "cy": 98.0,  "half_w": 4.0, "half_h": 1.0, "track_heading": -1.0},
    {"id": 8, "cx": -18.0, "cy": 40.0,  "half_w": 4.0, "half_h": 1.0, "track_heading": 0.2},
]

def in_checkpoint(x, y, cp):
    return abs(x - cp['cx']) < cp['half_w'] and abs(y - cp['cy']) < cp['half_h']

def heading_matches(heading, track_heading, tol=math.pi / 2):
    diff = abs((heading - track_heading + math.pi) % (2 * math.pi) - math.pi)
    return diff < tol

TRACK_ROAD_WIDTH = 8.0
TRACK_HALF_WIDTH = TRACK_ROAD_WIDTH / 2.0
GUARDRAIL_FAIL_MARGIN = 0
GUARDRAIL_FAIL_DISTANCE = TRACK_HALF_WIDTH + GUARDRAIL_FAIL_MARGIN
NO_CHECKPOINT_TIMEOUT = 180.0
TRACK_ROUTE = [(cp['cx'], cp['cy']) for cp in CHECKPOINTS]
TRACK_SEGMENTS = list(zip(TRACK_ROUTE, TRACK_ROUTE[1:] + TRACK_ROUTE[:1]))

def point_segment_distance(px, py, ax, ay, bx, by):
    vx = bx - ax
    vy = by - ay
    wx = px - ax
    wy = py - ay
    seg_len_sq = vx * vx + vy * vy
    if seg_len_sq == 0:
        return math.sqrt((px - ax) ** 2 + (py - ay) ** 2)
    t = max(0.0, min(1.0, (wx * vx + wy * vy) / seg_len_sq))
    proj_x = ax + t * vx
    proj_y = ay + t * vy
    return math.sqrt((px - proj_x) ** 2 + (py - proj_y) ** 2)

def distance_to_track_route(x, y):
    return min(
        point_segment_distance(x, y, ax, ay, bx, by)
        for (ax, ay), (bx, by) in TRACK_SEGMENTS
    )

def guardrail_collision_detected(car):
    if car['finish_time'] is not None or car['status'] == 'disqualified':
        return False
    return distance_to_track_route(car['x'], car['y']) > GUARDRAIL_FAIL_DISTANCE

# Build car state list
cars = []
for cc in cars_config:
    node = robot.getFromDef(cc['car_slot'])
    cars.append({
        "team_id": cc['team_id'],
        "car_slot": cc['car_slot'],
        "team_name": cc.get('team_name', cc['team_id']),
        "node": node,
        "x": 0.0,
        "y": 0.0,
        "heading": 0.0,
        "speed": 0.0,
        "lap": 0,
        "lap_progress": 0.0,
        "status": "normal",
        "checkpoints_passed": 0,
        "checkpoint_next": 1,
        "lap_started": False,
        "lap_start_time": 0.0,
        "best_lap_time": None,
        "collision_major_count": 0,
        "stop_end_time": None,
        "finish_time": None,
        "laps_data": [],
    })

os.makedirs(recording_path, exist_ok=True)
telemetry_path = os.path.join(recording_path, 'telemetry.jsonl')
tel_file = open(telemetry_path, 'a', encoding='utf-8')
frame_count = 0

# Print/update interval for on-console status reports (seconds)
PRINT_INTERVAL = 1.0
_last_print_time = 0.0

_overhead_cam = robot.getDevice('overhead_cam') if robot.getDevice else None
if _overhead_cam:
    try:
        _overhead_cam.enable(timestep * 10)
    except Exception:
        pass

_FRAME_SAVE_INTERVAL = 10
_live_view_path = os.path.join(recording_path, 'live_view.jpg')
desired_overhead_height = float(config.get('overhead_height', 60.0))

_overhead_node = robot.getFromDef('OVERHEAD_CAM')

def snapshot(car):
    return {
        "team_id": car['team_id'],
        "x": round(car['x'], 3),
        "y": round(car['y'], 3),
        "heading": round(car['heading'], 4),
        "speed": round(car['speed'], 2),
        "lap": car['lap'],
        "lap_progress": car['lap_progress'],
        "checkpoints_passed": car['checkpoints_passed'],
        "status": car['status'],
    }

def write_telemetry_frame(sim_time, cars, events):
    global frame_count
    frame = {"t": round(sim_time, 3), "cars": [snapshot(c) for c in cars], "events": events}
    tel_file.write(json.dumps(frame, ensure_ascii=False) + '\n')
    tel_file.flush()
    frame_count += 1

def write_metadata(finish_reason, final_rankings):
    meta = {
        "session_id": session_id,
        "session_type": session_type,
        "total_laps": total_laps,
        "recording_path": recording_path,
        "recorded_at": datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "duration_sim": round(robot.getTime(), 3),
        "total_frames": frame_count,
        "teams": [{"team_id": c['team_id'], "team_name": c['team_name']} for c in cars],
        "finish_reason": finish_reason,
        "final_rankings": final_rankings,
    }
    meta_path = os.path.join(recording_path, 'metadata.json')
    with open(meta_path, 'w', encoding='utf-8') as mf:
        json.dump(meta, mf, ensure_ascii=False, indent=2)

grace_started = False
grace_start_time = 0.0
race_finished = False
finish_reason = 'supervisor_stop'
final_rankings = []

def compute_final_rankings(cars):
    finished = sorted([c for c in cars if c['finish_time'] is not None], key=lambda c: c['finish_time'])
    unfinished = sorted([c for c in cars if c['finish_time'] is None], key=lambda c: (-c['lap'], -c['lap_progress']))
    ranked = finished + unfinished
    return [
        {"rank": i + 1, "team_id": c['team_id'], "team_name": c['team_name'], "laps": c['lap'],
         "checkpoints_passed": c['checkpoints_passed'], "best_lap": round(c['best_lap_time'], 3) if c['best_lap_time'] is not None else None,
         "total_time": round(c['finish_time'], 3) if c['finish_time'] is not None else None,
         "status": c['status'], "collision_major_count": c['collision_major_count']}
        for i, c in enumerate(ranked)
    ]

def check_checkpoints(car, sim_time, events):
    x, y, heading = car['x'], car['y'], car['heading']
    cp_idx = car['checkpoint_next']
    cp = CHECKPOINTS[cp_idx]
    if not in_checkpoint(x, y, cp):
        return
    if not heading_matches(heading, cp['track_heading']):
        return
    if cp_idx == 0 and not car['lap_started']:
        car['lap_started'] = True
        car['lap_start_time'] = sim_time
        car['checkpoint_next'] = 1
        car['lap_progress'] = 0.0
        car['checkpoints_passed'] += 1
        events.append({"type": "lap_start", "team_id": car['team_id'], "sim_time": round(sim_time, 3)})
    elif cp_idx != 0:
        car['checkpoint_next'] = (cp_idx + 1) % len(CHECKPOINTS)
        car['lap_progress'] = cp_idx * 0.25
        car['checkpoints_passed'] += 1
        events.append({"type": "checkpoint", "team_id": car['team_id'], "checkpoint_id": cp_idx, "sim_time": round(sim_time, 3)})
    elif cp_idx == 0 and car['lap_started']:
        lap_time = sim_time - car['lap_start_time']
        car['laps_data'].append(lap_time)
        if car['best_lap_time'] is None or lap_time < car['best_lap_time']:
            car['best_lap_time'] = lap_time
        car['lap'] += 1
        car['lap_start_time'] = sim_time
        car['lap_progress'] = 0.0
        car['checkpoint_next'] = 1
        car['checkpoints_passed'] += 1
        events.append({"type": "lap_complete", "team_id": car['team_id'], "lap_number": car['lap'], "lap_time": round(lap_time, 3), "best_lap_time": round(car['best_lap_time'], 3)})
        if car['lap'] >= total_laps and car['finish_time'] is None:
            car['finish_time'] = sim_time
            events.append({"type": "car_finished", "team_id": car['team_id'], "finish_time": round(sim_time, 3), "total_laps": car['lap']})
            if session_type == 'qualifying':
                send_cmd_to_car(car, {"cmd": "stop", "duration": 9999})
                car['status'] = 'stopped'

def send_cmd_to_car(car, cmd_dict):
    try:
        field = car['node'].getField('customData')
        field.setSFString(json.dumps(cmd_dict))
    except Exception:
        pass

def check_car_collisions(cars, sim_time, events):
    active = [c for c in cars if c['status'] != 'disqualified']
    for i in range(len(active)):
        for j in range(i + 1, len(active)):
            ca, cb = active[i], active[j]
            dist = math.sqrt((ca['x'] - cb['x']) ** 2 + (ca['y'] - cb['y']) ** 2)
            if dist < 0.5:
                rel_speed = abs(ca['speed'] - cb['speed'])
                severity = 'major' if rel_speed >= 3.0 else 'minor'
                events.append({"type": "collision", "severity": severity, "team_ids": [ca['team_id'], cb['team_id']], "distance": round(dist, 3), "rel_speed": round(rel_speed, 2), "sim_time": round(sim_time, 3)})
                if severity == 'major':
                    for car in (ca, cb):
                        if car['status'] == 'disqualified':
                            continue
                        car['collision_major_count'] += 1
                        if car['collision_major_count'] >= 3:
                            car['status'] = 'disqualified'
                            send_cmd_to_car(car, {"cmd": "disqualify"})
                            events.append({"type": "disqualified", "team_id": car['team_id'], "reason": "major_collision_threshold", "sim_time": round(sim_time, 3)})
                        else:
                            car['status'] = 'stopped'
                            car['stop_end_time'] = sim_time + 2.0
                            send_cmd_to_car(car, {"cmd": "stop", "duration": 2.0})

def check_race_end(cars, sim_time, events):
    global race_finished, finish_reason, final_rankings, grace_started, grace_start_time
    for car in cars:
        if guardrail_collision_detected(car):
            car['status'] = 'disqualified'
            send_cmd_to_car(car, {"cmd": "disqualify"})
            final_rankings = compute_final_rankings(cars)
            events.append({"type": "race_end", "reason": "guardrail_collision", "team_id": car['team_id'], "distance_to_route": round(distance_to_track_route(car['x'], car['y']), 3), "final_rankings": final_rankings})
            finish_reason = 'guardrail_collision'
            race_finished = True
            return

    if sim_time >= NO_CHECKPOINT_TIMEOUT and not any(c['checkpoints_passed'] > 0 for c in cars):
        final_rankings = compute_final_rankings(cars)
        events.append({"type": "race_end", "reason": "no_checkpoint_timeout", "timeout_seconds": NO_CHECKPOINT_TIMEOUT, "final_rankings": final_rankings})
        finish_reason = 'no_checkpoint_timeout'
        race_finished = True
        return

    for car in cars:
        if car['lap'] >= total_laps and car['finish_time'] is not None:
            if not grace_started and session_type != 'qualifying':
                grace_started = True
                grace_start_time = car['finish_time']
                events.append({"type": "leader_finished", "team_id": car['team_id'], "finish_time": round(car['finish_time'], 3), "grace_end_time": round(car['finish_time'] + 60.0, 3)})

    if session_type != 'qualifying' and grace_started:
        if robot.getTime() - grace_start_time >= 60.0:
            final_rankings = compute_final_rankings(cars)
            events.append({"type": "race_end", "reason": "grace_period_expired", "final_rankings": final_rankings})
            finish_reason = 'grace_period_expired'
            race_finished = True

    if session_type == 'qualifying':
        timed_out = robot.getTime() >= NO_CHECKPOINT_TIMEOUT
        all_done = all(c['finish_time'] is not None or c['status'] in ('stopped', 'disqualified') for c in cars)
        if all_done or timed_out:
            final_rankings = compute_final_rankings(cars)
            reason = 'all_cars_done' if all_done else ('no_checkpoint_timeout' if not any(c['checkpoints_passed'] > 0 for c in cars) else 'timeout')
            events.append({"type": "race_end", "reason": reason, "final_rankings": final_rankings})
            finish_reason = reason
            race_finished = True

# Main loop
while robot.step(timestep) != -1:
    sim_time = robot.getTime()
    events_this_frame = []

    for car in cars:
        if car['node'] is None:
            continue
        pos = car['node'].getPosition()
        car['x'], car['y'] = pos[0], pos[1]
        ori = car['node'].getOrientation()
        car['heading'] = math.atan2(-ori[3], ori[0])
        vel = car['node'].getVelocity()
        car['speed'] = math.sqrt(vel[0] ** 2 + vel[1] ** 2)
        if car['status'] == 'stopped' and car['stop_end_time'] is not None:
            if sim_time >= car['stop_end_time']:
                car['status'] = 'normal'
                car['stop_end_time'] = None
                send_cmd_to_car(car, {"cmd": "none"})

    for car in cars:
        if car['status'] != 'disqualified':
            check_checkpoints(car, sim_time, events_this_frame)

    check_car_collisions(cars, sim_time, events_this_frame)
    check_race_end(cars, sim_time, events_this_frame)
    write_telemetry_frame(sim_time, cars, events_this_frame)
    # Periodically print a short status line to the Webots console (approximately once per second)
    try:
        if sim_time - _last_print_time >= PRINT_INTERVAL:
            status_parts = []
            for c in cars:
                # show team, speed and checkpoints passed
                status_parts.append(f"{c['team_id']}: speed={c['speed']:.2f} m/s cp={c['checkpoints_passed']}")
            print('[Supervisor] ' + ' | '.join(status_parts))
            _last_print_time = sim_time
    except Exception:
        pass
    if _overhead_node and len(cars) > 0:
        try:
            car0 = cars[0]
            tx = float(car0['x'])
            ty = float(car0['y'])
            h = float(desired_overhead_height)
            try:
                _overhead_node.getField('translation').setSFVec3f([tx, ty, h])
            except Exception:
                try:
                    _overhead_node.getField('position').setSFVec3f([tx, ty, h])
                except Exception:
                    pass
            try:
                _overhead_node.getField('rotation').setSFRotation([1.0, 0.0, 0.0, -1.5708])
            except Exception:
                try:
                    _overhead_node.getField('orientation').setSFRotation([1.0, 0.0, 0.0, -1.5708])
                except Exception:
                    pass
        except Exception:
            pass

    if _overhead_cam and frame_count % _FRAME_SAVE_INTERVAL == 0:
        try:
            _overhead_cam.saveImage(_live_view_path, 75)
        except Exception:
            pass

    if os.path.exists(os.path.join(recording_path, 'STOP')):
        final_rankings = compute_final_rankings(cars)
        finish_reason = 'admin_stop'
        race_finished = True

    if race_finished:
        break

tel_file.close()
try:
    # Print a final summary to the Webots console before writing metadata
    print(f"[Supervisor] Race finished: reason={finish_reason}, duration={round(robot.getTime(),3)}s")
    for c in cars:
        print(f"[Supervisor] Team {c['team_id']}: checkpoints={c['checkpoints_passed']}, laps={c['lap']}, status={c['status']}")
except Exception:
    pass

write_metadata(finish_reason, final_rankings)

