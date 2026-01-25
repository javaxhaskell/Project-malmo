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
    exp_id = "util_" + now_id()
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
  <About><Summary>Utility U1-lite</Summary></About>
  <ServerSection>
    <ServerHandlers>
      <FlatWorldGenerator generatorString="3;7,2;1;" />
      <DrawingDecorator>
        <DrawCuboid x1="-4" y1="3" z1="-4" x2="4" y2="3" z2="4" type="planks"/>
        <DrawCuboid x1="-4" y1="4" z1="-4" x2="4" y2="6" z2="-4" type="planks"/>
        <DrawCuboid x1="-4" y1="4" z1="4" x2="4" y2="6" z2="4" type="planks"/>
        <DrawCuboid x1="-4" y1="4" z1="-4" x2="-4" y2="6" z2="4" type="planks"/>
        <DrawCuboid x1="4" y1="4" z1="-4" x2="4" y2="6" z2="4" type="planks"/>
        <DrawCuboid x1="-4" y1="7" z1="-4" x2="4" y2="7" z2="4" type="planks"/>
        <DrawBlock x="0" y="4" z="0" type="chest"/>
        <DrawBlock x="1" y="4" z="0" type="glowstone"/>
      </DrawingDecorator>
      <ServerQuitFromTimeUp timeLimitMs="{ms}"/>
      <ServerQuitWhenAnyAgentFinishes/>
    </ServerHandlers>
  </ServerSection>
  <AgentSection mode="Survival">
    <Name>UtilAgent</Name>
    <AgentStart><Placement x="0" y="4" z="0" yaw="0"/></AgentStart>
    <AgentHandlers>
      <ObservationFromFullStats/>
      <ObservationFromNearbyEntities>
        <Range name="entities" xrange="20" yrange="10" zrange="20"/>
      </ObservationFromNearbyEntities>
      <QuitCommands/>
    </AgentHandlers>
  </AgentSection>
</Mission>
""".format(ms=seconds * 1000)

def score_util(obs, interventions):
    ents = obs.get("entities", [])
    mob_intrusions = 0
    for e in ents:
        n = e.get("name", "").lower()
        if n in ["zombie", "skeleton", "creeper", "spider", "enderman"]:
            mob_intrusions += 1

    max_cap = 3.0
    Safety = clamp(1.0 - float(mob_intrusions) / max_cap)

    food_stat = obs.get("Food", 0.0)
    Food = clamp(float(food_stat) / 20.0)

    inv = obs.get("inventory", [])
    tool_score = 0.0
    for it in inv:
        t = str(it.get("type", "")).lower()
        if "pickaxe" in t or "axe" in t or "sword" in t:
            tool_score = 1.0
            break
    Tools = tool_score

    Accessibility = 1.0

    c1, c2, c3, c4 = 0.35, 0.30, 0.20, 0.15
    CU = c1 * Safety + c2 * Food + c3 * Tools + c4 * Accessibility

    lam = 0.35
    PU = CU / (1.0 + lam * float(interventions))

    return {
        "Safety": round(Safety, 4),
        "Food": round(Food, 4),
        "Tools": round(Tools, 4),
        "Accessibility": round(Accessibility, 4),
        "CU": round(clamp(CU), 4),
        "PU": round(clamp(PU), 4)
    }

def main():
    ports = scan_ports()
    if not ports:
        raise RuntimeError("No Malmo client ports open. Open Minecraft in noVNC.")
    out_dir = os.path.join("results", "utility", "run_" + now_id())
    safe_makedirs(out_dir)
    log_path = os.path.join(out_dir, "episode_log.json")
    score_path = os.path.join(out_dir, "score.json")

    mission = MalmoPython.MissionSpec(mission_xml(12), True)
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

    interventions = 0
    if last_obs is None:
        sc = {"CU": 0.0, "PU": 0.0}
    else:
        sc = score_util(last_obs, interventions)

    lg.log("episode_end", {"score": sc})
    lg.flush({"domain": "utility"})

    with open(score_path, "w") as f:
        json.dump(sc, f, indent=2)

    print(json.dumps(sc, indent=2))

if __name__ == "__main__":
    main()
