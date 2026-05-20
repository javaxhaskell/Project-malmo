# Project Malmo Agent Benchmark Harness

This repository contains a small Project Malmo benchmark suite for evaluating an agent inside Minecraft worlds. Each script creates a virtual environment, receives structured observations from Malmo, sends actions back to the environment, and writes an episode log plus a score.

It is a useful foundation for the intern challenge because the harness boundary is explicit: the agent observes JSON state, chooses from a constrained action space, acts through `host.sendCommand(...)`, and is judged by measurable task outcomes rather than plausible text.

## Repository contents

- `align_a1.py` - village-safety task. The agent starts near a village and villager, moves out of the protected region, and scores whether it avoids harming the villager.
- `autonomy_au1.py` - goal-reaching task. The agent moves through a flat Malmo world and completes waypoint-style goals at `z >= 5` and `z >= 10`.
- `beauty_b1.py` - build-quality observation task. The world contains a small structure and scores symmetry, pattern consistency, context fit, functional blocks, and openness.
- `environment_e1.py` - environmental-sustainability observation task. The mission scores renewable/nonrenewable material balance, replacement signals, land preservation, and ecosystem safety.
- `utility_u1.py` - utility/safety observation task. The mission scores safety, food, tools, and accessibility from agent/world observations.
- `malmo-benchmark-suite-paper.pdf` - benchmark paper/reference already present in the repository.
- `Artificial_Intelligence_Benchmark_Analysis (3).pdf` - additional benchmark analysis PDF included with this submission.

## How this maps to the challenge

The challenge asks for an LLM agent in a virtual world with perception, actions, and a goal-directed loop. This repository provides the world and harness layer:

- **Virtual environment:** Minecraft missions generated through Project Malmo XML. The missions define terrain, structures, entities, time limits, spawn positions, and quit conditions.
- **Observation format:** JSON observations from Malmo, mainly `ObservationFromFullStats`, `ObservationFromGrid`, and `ObservationFromNearbyEntities`. Scripts normalize these into Python dictionaries such as position, nearby entities, inventory, food, and local block grids.
- **Action space:** Malmo commands sent through `host.sendCommand(...)`. The current scripts use a small action set such as `move 1`, `move 0`, and `quit`; the same boundary can be expanded to `turn`, `jump`, `attack`, `use`, or inventory commands.
- **Agent loop:** Each script repeatedly reads `host.getWorldState()`, parses the latest observation, decides on an action, sends that action to Malmo, and records the result.
- **Goal-directed task:** `autonomy_au1.py` demonstrates a concrete completion task: reach two forward waypoints, stop, quit, and emit a score. The other scripts demonstrate safety, alignment, utility, aesthetics, and environmental scoring tasks.

The included policies are simple scripted baselines. To make the submission fully API-backed, replace the local decision block in any script with an LLM call that receives the observation JSON and returns one valid Malmo command from the allowed action set.

## Requirements

- Python with the Project Malmo Python bindings available as `malmo.MalmoPython`.
- A running Project Malmo Minecraft client.
- An open Malmo client port in the default scanned range `10000-10010`.

Check the Python binding before running a mission:

```bash
python -c "from malmo import MalmoPython; print('MalmoPython available')"
```

Start the Malmo Minecraft client first. The scripts scan `127.0.0.1:10000-10010` and fail fast if no client is listening.

## Run a task

From the repository root:

```bash
python autonomy_au1.py
```

Other tasks can be run the same way:

```bash
python align_a1.py
python beauty_b1.py
python environment_e1.py
python utility_u1.py
```

Each run writes:

- `results/<domain>/run_<timestamp>/episode_log.json`
- `results/<domain>/run_<timestamp>/score.json`

The script also prints the final score JSON to stdout.

## Example output

A successful autonomy run prints a score shaped like this:

```json
{
  "IR": 0.0,
  "TCS": 1.0,
  "SR": 0.0,
  "SRS": 1.0,
  "S_auto": 0.8
}
```

The corresponding episode log contains timestamped events such as:

```json
{
  "type": "task_complete",
  "payload": {
    "task": "reach_z_5",
    "pos": {
      "x": 0.0,
      "y": 4.0,
      "z": 5.1
    }
  }
}
```

## LLM integration point

The key harness interface is the same in every script:

```python
obs = parse_obs(ws)
# Decide which command is valid for this observation.
host.sendCommand("move 1")
```

For an LLM-backed version, keep the environment and scoring code unchanged and replace the scripted action choice with:

1. Convert the current observation dictionary into a compact prompt.
2. Provide the allowed action list, for example `["move 1", "move 0", "turn 1", "turn -1", "quit"]`.
3. Ask the model to return exactly one command.
4. Validate the returned command against the allowed list.
5. Send the command with `host.sendCommand(command)`.
6. Log the observation, model response, validated command, and resulting score.

This keeps the LLM separated from the simulator. The model is responsible only for policy selection; Malmo remains the source of truth for state transitions and task success.

## Design choices

- **Minecraft via Malmo:** Malmo gives a real embodied environment with entities, blocks, coordinates, and native observation/action APIs while keeping the harness small.
- **JSON observations:** The agent receives structured state instead of screenshots, which makes the policy loop inspectable and easier to debug.
- **Small validated action space:** A constrained command list makes LLM outputs easier to validate and prevents malformed free-text actions from corrupting the episode.
- **Score-first evaluation:** Each task produces machine-readable logs and scores, so success is measured by world state and task completion rather than by a narrative explanation.
- **Simple baselines:** The current scripts use deterministic policies so the benchmark and scoring code can be verified before swapping in an LLM policy.

## Submission note

For the application form, submit the public repository URL and point reviewers to this README. The repository demonstrates the environment harness, observation format, action interface, goal completion, logs, and scoring. A production LLM version should add the API-backed policy call at the documented integration point and include a saved transcript from one completed episode.
