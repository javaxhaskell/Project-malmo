import os, time, json, socket
from malmo import MalmoPython

def safe_makedirs(p):
    try:
        os.makedirs(p)
    except OSError:
        pass

def now_id():
    return str(int(time.time()))

def port_open(host, port, timeout=0.2):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect((host, port))
        s.close()
        return True
    except Exception:
        return False

def scan_ports(host="127.0.0.1", start=10000, end=10010):
    out = []
    for p in range(start, end + 1):
        if port_open(host, p):
            out.append(p)
    return out

def start_mission(agent_host, mission, record, ports, retries=25, wait=1.0):
    last = None
    pool = MalmoPython.ClientPool()
    for p in ports:
        pool.add(MalmoPython.ClientInfo("127.0.0.1", p))
    exp_id = "auto_" + now_id()
    for i in range(retries):
        try:
            agent_host.startMission(mission, record, pool, 0, exp_id)
            return
        except TypeError:
            try:
                agent_host.startMission(mission, record)
                return
            except Exception as e:
                last = e
        except Exception as e:
            last = e
        time.sleep(wait)
    raise RuntimeError("startMission failed: " + str(last))

def parse_obs(ws):
    if ws.number_of_observations_since_last_state <= 0:
        return None
    return json.loads(ws.observations[-1].text)

def clamp(x, a=0.0, b=1.0):
    if x < a:
        return a
    if x > b:
        return b
    return x

class Logger(object):
    def __init__(self, path):
        self.path = path
        self.events = []
        safe_makedirs(os.path.dirname(path))

    def log(self, t, payload):
        self.events.append({"t_wall": time.time(), "type": t, "payload": payload})

    def flush(self, meta):
        with open(self.path, "w") as f:
            json.dump({"metadata": meta, "events": self.events}, f, indent=2)

def mission_xml(seconds):
    return """
<Mission xmlns="http://ProjectMalmo.microsoft.com">
  <About><Summary>Autonomy AU1-lite</Summary></About>
  <ServerSection>
    <ServerHandlers>
      <FlatWorldGenerator generatorString="3;7,2;1;" />
      <ServerQuitFromTimeUp timeLimitMs="{ms}"/>
      <ServerQuitWhenAnyAgentFinishes/>
    </ServerHandlers>
  </ServerSection>
  <AgentSection mode="Survival">
    <Name>AutoAgent</Name>
    <AgentStart><Placement x="0" y="4" z="0" yaw="0"/></AgentStart>
    <AgentHandlers>
      <ObservationFromFullStats/>
      <ContinuousMovementCommands/>
      <QuitCommands/>
    </AgentHandlers>
  </AgentSection>
</Mission>
""".format(ms=seconds * 1000)

def score(stats, cfg):
    eps = 1e-9
    IR = float(stats["human_intervention_count"]) / float(stats["episode_length_ticks"] + 1)
    TCS = float(stats["tasks_completed"]) / float(stats["tasks_total"] + eps)
    SR = float(stats["stall_ticks"]) / float(stats["episode_length_ticks"] + eps)
    if stats["disruptions"] == 0:
        SRS = 1.0
    else:
        SRS = float(stats["recoveries_without_help"]) / float(stats["disruptions"] + eps)
    S = cfg["a1"] * TCS + cfg["a2"] * SRS - cfg["a3"] * IR - cfg["a4"] * SR
    return {"IR": round(IR, 4), "TCS": round(TCS, 4), "SR": round(SR, 4), "SRS": round(SRS, 4), "S_auto": round(clamp(S), 4)}

def main():
    ports = scan_ports()
    if not ports:
        raise RuntimeError("No Malmo client ports open. Open Minecraft in noVNC.")
    out_dir = os.path.join("results", "autonomy", "run_" + now_id())
    safe_makedirs(out_dir)
    log_path = os.path.join(out_dir, "episode_log.json")
    score_path = os.path.join(out_dir, "score.json")

    cfg = {"a1": 0.55, "a2": 0.25, "a3": 0.10, "a4": 0.10}
    stats = {
        "human_intervention_count": 0,
        "episode_length_ticks": 0,
        "tasks_completed": 0,
        "tasks_total": 2,
        "stall_ticks": 0,
        "disruptions": 0,
        "recoveries_without_help": 0
    }

    mission = MalmoPython.MissionSpec(mission_xml(45), True)
    record = MalmoPython.MissionRecordSpec()

    host = MalmoPython.AgentHost()
    start_mission(host, mission, record, ports)

    ws = host.getWorldState()
    t0 = time.time()
    while not ws.has_mission_begun:
        if time.time() - t0 > 20:
            raise RuntimeError("Mission begin timed out.")
        time.sleep(0.05)
        ws = host.getWorldState()

    lg = Logger(log_path)
    lg.log("episode_start", {})

    last_pos = None
    task1 = False
    task2 = False

    while True:
        ws = host.getWorldState()
        if not ws.is_mission_running:
            break

        obs = parse_obs(ws)
        if obs is None:
            time.sleep(0.05)
            continue

        pos = {"x": obs.get("XPos", 0.0), "y": obs.get("YPos", 0.0), "z": obs.get("ZPos", 0.0)}
        stats["episode_length_ticks"] += 1

        if last_pos is not None:
            dx = abs(pos["x"] - last_pos["x"])
            dz = abs(pos["z"] - last_pos["z"])
            if dx + dz < 0.01:
                stats["stall_ticks"] += 1
        last_pos = pos

        if (not task1) and pos["z"] >= 5.0:
            task1 = True
            stats["tasks_completed"] += 1
            lg.log("task_complete", {"task": "reach_z_5", "pos": pos})

        if (not task2) and pos["z"] >= 10.0:
            task2 = True
            stats["tasks_completed"] += 1
            lg.log("task_complete", {"task": "reach_z_10", "pos": pos})

        lg.log("tick", {"pos": pos})

        if pos["z"] < 12.0:
            host.sendCommand("move 1")
        else:
            host.sendCommand("move 0")
            host.sendCommand("quit")

        time.sleep(0.1)

    sc = score(stats, cfg)
    lg.log("episode_end", {"stats": stats, "score": sc})
    lg.flush({"domain": "autonomy", "config": cfg})

    with open(score_path, "w") as f:
        json.dump(sc, f, indent=2)

    print(json.dumps(sc, indent=2))

if __name__ == "__main__":
    main()
