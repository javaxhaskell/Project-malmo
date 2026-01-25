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
    exp_id = "beauty_" + now_id()
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
  <About><Summary>Beauty B1-lite</Summary></About>
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
        <DrawCuboid x1="-1" y1="5" z1="-4" x2="1" y2="5" z2="-4" type="glass"/>
        <DrawCuboid x1="-1" y1="5" z1="4" x2="1" y2="5" z2="4" type="glass"/>
        <DrawCuboid x1="-4" y1="5" z1="-1" x2="-4" y2="5" z2="1" type="glass"/>
        <DrawCuboid x1="4" y1="5" z1="-1" x2="4" y2="5" z2="1" type="glass"/>
        <DrawBlock x="0" y="4" z="-3" type="glowstone"/>
        <DrawBlock x="0" y="4" z="0" type="chest"/>
      </DrawingDecorator>
      <ServerQuitFromTimeUp timeLimitMs="{ms}"/>
      <ServerQuitWhenAnyAgentFinishes/>
    </ServerHandlers>
  </ServerSection>
  <AgentSection mode="Survival">
    <Name>BeautyAgent</Name>
    <AgentStart><Placement x="8" y="4" z="0" yaw="90"/></AgentStart>
    <AgentHandlers>
      <ObservationFromFullStats/>
      <ObservationFromGrid>
        <Grid name="build" absoluteCoords="true">
          <min x="-6" y="3" z="-6"/>
          <max x="6" y="7" z="6"/>
        </Grid>
      </ObservationFromGrid>
      <QuitCommands/>
    </AgentHandlers>
  </AgentSection>
</Mission>
""".format(ms=seconds * 1000)

def grid_to_map(blocks, x0, y0, z0, x1, y1, z1):
    dx = x1 - x0 + 1
    dy = y1 - y0 + 1
    dz = z1 - z0 + 1
    m = {}
    idx = 0
    for y in range(dy):
        for z in range(dz):
            for x in range(dx):
                m[(x0 + x, y0 + y, z0 + z)] = blocks[idx]
                idx += 1
    return m

def symmetry_score(m, x0, x1, y0, y1, z0, z1):
    tot = 0
    okx = 0
    okz = 0
    for y in range(y0, y1 + 1):
        for z in range(z0, z1 + 1):
            for x in range(x0, x1 + 1):
                a = m.get((x, y, z), "air")
                mx = x0 + x1 - x
                mz = z0 + z1 - z
                bx = m.get((mx, y, z), "air")
                bz = m.get((x, y, mz), "air")
                tot += 1
                if a == bx:
                    okx += 1
                if a == bz:
                    okz += 1
    if tot == 0:
        return 0.0
    return 0.5 * (float(okx) / float(tot) + float(okz) / float(tot))

def pattern_score(m, x0, x1, z0, z1, y):
    tot = 0
    ok = 0
    for z in range(z0, z1):
        for x in range(x0, x1):
            a = m.get((x, y, z), "air")
            b = m.get((x + 1, y, z), "air")
            c = m.get((x, y, z + 1), "air")
            d = m.get((x + 1, y, z + 1), "air")
            tot += 1
            if a == b and a == c and a == d:
                ok += 1
    if tot == 0:
        return 0.0
    return float(ok) / float(tot)

def context_fit_score(m, x0, x1, y0, y1, z0, z1):
    freq = {}
    for y in range(y0, y1 + 1):
        for z in range(z0, z1 + 1):
            for x in range(x0, x1 + 1):
                b = m.get((x, y, z), "air")
                if b == "air":
                    continue
                freq[b] = freq.get(b, 0) + 1
    items = sorted(freq.items(), key=lambda kv: kv[1], reverse=True)
    top = set([kv[0] for kv in items[:3]])
    house_total = 0
    house_ok = 0
    for y in range(3, 7 + 1):
        for z in range(-4, 4 + 1):
            for x in range(-4, 4 + 1):
                b = m.get((x, y, z), "air")
                if b == "air":
                    continue
                house_total += 1
                if b in top:
                    house_ok += 1
    if house_total == 0:
        return 0.0
    return float(house_ok) / float(house_total)

def fhs_score(m):
    need = ["chest", "glowstone", "glass", "planks"]
    have = 0
    for t in need:
        found = False
        for k in m:
            if m[k] == t:
                found = True
                break
        if found:
            have += 1
    return float(have) / float(len(need))

def score_beauty(obs):
    blocks = obs.get("build", None)
    if blocks is None:
        return {"SS": 0.0, "PS": 0.0, "CFS": 0.0, "FHS": 0.0, "ODS": 0.5, "S_beauty": 0.0}

    x0, y0, z0 = -6, 3, -6
    x1, y1, z1 = 6, 7, 6
    m = grid_to_map(blocks, x0, y0, z0, x1, y1, z1)

    SS = symmetry_score(m, -4, 4, 3, 7, -4, 4)
    PS = pattern_score(m, -4, 4, -4, 4, 3)
    CFS = context_fit_score(m, -6, 6, 3, 7, -6, 6)
    FHS = fhs_score(m)
    ODS = 0.5

    b1, b2, b3, b4, b5 = 0.30, 0.15, 0.20, 0.25, 0.10
    S = b1 * SS + b2 * PS + b3 * CFS + b4 * FHS + b5 * ODS
    return {"SS": round(SS, 4), "PS": round(PS, 4), "CFS": round(CFS, 4), "FHS": round(FHS, 4), "ODS": round(ODS, 4), "S_beauty": round(clamp(S), 4)}

def main():
    ports = scan_ports()
    if not ports:
        raise RuntimeError("No Malmo client ports open. Open Minecraft in noVNC.")
    out_dir = os.path.join("results", "beauty", "run_" + now_id())
    safe_makedirs(out_dir)
    log_path = os.path.join(out_dir, "episode_log.json")
    score_path = os.path.join(out_dir, "score.json")

    mission = MalmoPython.MissionSpec(mission_xml(20), True)
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
        sc = {"S_beauty": 0.0}
    else:
        sc = score_beauty(last_obs)

    lg.log("episode_end", {"score": sc})
    lg.flush({"domain": "beauty"})

    with open(score_path, "w") as f:
        json.dump(sc, f, indent=2)

    print(json.dumps(sc, indent=2))

if __name__ == "__main__":
    main()
