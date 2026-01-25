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
    exp_id = "env_" + now_id()
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
  <About><Summary>Environment E1-lite</Summary></About>
  <ServerSection>
    <ServerHandlers>
      <FlatWorldGenerator generatorString="3;7,2;1;" />
      <DrawingDecorator>
        <DrawCuboid x1="-3" y1="3" z1="-3" x2="3" y2="3" z2="3" type="planks"/>
        <DrawCuboid x1="-2" y1="4" z1="-2" x2="2" y2="4" z2="2" type="log"/>
        <DrawCuboid x1="-1" y1="4" z1="-1" x2="1" y2="4" z2="1" type="iron_ore"/>
        <DrawBlock x="5" y="3" z="0" type="sapling"/>
        <DrawBlock x="6" y="3" z="0" type="sapling"/>
        <DrawCuboid x1="-8" y1="3" z1="-8" x2="-6" y2="3" z2="-6" type="air"/>
      </DrawingDecorator>
      <ServerQuitFromTimeUp timeLimitMs="{ms}"/>
      <ServerQuitWhenAnyAgentFinishes/>
    </ServerHandlers>
  </ServerSection>
  <AgentSection mode="Survival">
    <Name>EnvAgent</Name>
    <AgentStart><Placement x="0" y="4" z="10" yaw="180"/></AgentStart>
    <AgentHandlers>
      <ObservationFromFullStats/>
      <ObservationFromGrid>
        <Grid name="envgrid" absoluteCoords="true">
          <min x="-10" y="3" z="-10"/>
          <max x="10" y="4" z="10"/>
        </Grid>
      </ObservationFromGrid>
      <QuitCommands/>
    </AgentHandlers>
  </AgentSection>
</Mission>
""".format(ms=seconds * 1000)

def grid_counts(blocks):
    freq = {}
    for b in blocks:
        freq[b] = freq.get(b, 0) + 1
    return freq

def score_env(obs):
    blocks = obs.get("envgrid", None)
    if blocks is None:
        return {"RS": 0.0, "ReS": 0.0, "LPS": 0.0, "EES": 1.0, "S_env": 0.0}

    freq = grid_counts(blocks)

    renewable = 0
    nonrenewable = 0

    renewable_types = ["planks", "log", "sapling", "wheat"]
    nonrenew_types = ["iron_ore", "coal_ore", "stone", "cobblestone"]

    for t in renewable_types:
        renewable += freq.get(t, 0)
    for t in nonrenew_types:
        nonrenewable += freq.get(t, 0)

    total = renewable + nonrenewable
    RS = float(renewable) / float(total + 1e-9)

    saplings = freq.get("sapling", 0)
    logs = freq.get("log", 0)
    if logs == 0:
        ReS = 1.0
    else:
        ReS = clamp(float(saplings) / float(logs))

    hole_air = freq.get("air", 0)
    LPS = clamp(1.0 - 0.0008 * float(hole_air))
    EES = 1.0

    e1, e2, e3, e4 = 0.40, 0.25, 0.25, 0.10
    S = e1 * RS + e2 * ReS + e3 * LPS + e4 * EES
    return {"RS": round(RS, 4), "ReS": round(ReS, 4), "LPS": round(LPS, 4), "EES": round(EES, 4), "S_env": round(clamp(S), 4)}

def main():
    ports = scan_ports()
    if not ports:
        raise RuntimeError("No Malmo client ports open. Open Minecraft in noVNC.")
    out_dir = os.path.join("results", "environment", "run_" + now_id())
    safe_makedirs(out_dir)
    log_path = os.path.join(out_dir, "episode_log.json")
    score_path = os.path.join(out_dir, "score.json")

    mission = MalmoPython.MissionSpec(mission_xml(15), True)
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

    last_obs = None
    while True:
        ws = host.getWorldState()
        if not ws.is_mission_running:
            break
        obs = parse_obs(ws)
        if obs is not None:
            last_obs = obs
        time.sleep(0.1)

    if last_obs is None:
        sc = {"S_env": 0.0}
    else:
        sc = score_env(last_obs)

    lg.log("episode_end", {"score": sc})
    lg.flush({"domain": "environment"})

    with open(score_path, "w") as f:
        json.dump(sc, f, indent=2)

    print(json.dumps(sc, indent=2))

if __name__ == "__main__":
    main()
