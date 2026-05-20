# LLM Agent in a Virtual World

This repository is a complete submission for the intern challenge. It contains a runnable agent harness that places an LLM-controlled agent inside a small virtual world, gives it structured observations, validates its actions, and records whether it completes a goal-directed task.

The primary implementation is `llm_agent_world.py`: a dependency-free Python grid world where the agent must collect a key, open a locked door, and reach the goal. The LLM policy is implemented with the OpenAI Responses API and returns strict JSON actions that are validated before being applied to the world.

The original Project Malmo benchmark scripts are also included as optional Minecraft-based evaluation tasks.

## Quick start

Run the deterministic smoke test first:

```bash
python llm_agent_world.py --policy scripted --max-steps 80
```

Run the LLM agent:

```bash
OPENAI_API_KEY="sk-..." OPENAI_MODEL="gpt-5.4-mini" \
  python llm_agent_world.py --policy llm --max-steps 80
```

The script prints a score summary and writes a full episode log under `runs/run_<timestamp>/episode_log.json`.

## What the agent sees

Each turn provides a JSON observation with:

- current position and facing direction
- inventory
- front-cell contents
- door state
- direction to key and goal
- a rendered symbolic map
- nearby visible cells
- the valid actions for the current state

Example observation fields:

```json
{
  "objective": "Collect the key, open the locked door, and reach the goal.",
  "position": {"x": 1, "y": 1},
  "facing": "E",
  "inventory": [],
  "front": {"x": 2, "y": 1, "cell": "empty"},
  "valid_actions": ["move_forward", "turn_left", "turn_right", "look", "wait"]
}
```

## Action space

The harness accepts only these actions:

```text
move_forward
turn_left
turn_right
pick_up
open_door
look
wait
```

The environment computes the valid subset at every step. If the model returns an invalid action, the environment rejects it as an invalid no-op, increments the invalid-action count, logs the failure, and continues. This keeps free-form model output from corrupting the episode state while still penalizing bad decisions.

## LLM loop

`OpenAIPolicy` performs the agent loop:

1. Serialize the current observation.
2. Send it to the OpenAI Responses API with a strict JSON schema.
3. Parse the model response as `{ "action": "...", "reason": "..." }`.
4. Validate the action against `observation.valid_actions`.
5. Apply the action to the world.
6. Log the observation, model decision, action result, map, and score.

The model never mutates the world directly. It can only choose from the harness action space; the simulator remains the source of truth.

## Example result

This repository includes a successful episode log:

```text
examples/successful_episode_log.json
```

A successful run has this score shape:

```json
{
  "goal_complete": true,
  "key_collected": true,
  "door_opened": true,
  "steps": 14,
  "invalid_actions": 0,
  "invalid_action_rate": 0.0,
  "score": 1.0,
  "max_steps": 80
}
```

Final map from the included run:

```text
##########
#.......##
#.###.#..#
#...#.#..#
#.#.d.>..#
#........#
##########
```

## Tests

Run the test suite:

```bash
python -m unittest discover -s tests -v
```

The tests verify that:

- the harness exposes usable observations and valid actions
- invalid actions are rejected without moving the agent
- the deterministic policy can complete the full key-door-goal task

## Optional Project Malmo tasks

The repository also contains the original Project Malmo benchmark scripts:

- `align_a1.py`
- `autonomy_au1.py`
- `beauty_b1.py`
- `environment_e1.py`
- `utility_u1.py`

These require a running Project Malmo Minecraft client and Python bindings available as `malmo.MalmoPython`.

Check the binding:

```bash
python -c "from malmo import MalmoPython; print('MalmoPython available')"
```

Run a Malmo task after starting the Minecraft client:

```bash
python autonomy_au1.py
```

Malmo task outputs are written to `results/<domain>/run_<timestamp>/`.

## Design choices

- **Small world, real harness:** The grid world keeps setup simple while still testing the core challenge: perception, action validation, state transitions, and goal completion.
- **Structured observations:** The agent receives symbolic JSON instead of raw screenshots, making behavior inspectable and repeatable.
- **Validated action interface:** The LLM cannot invent arbitrary simulator commands. Every action is checked before execution.
- **Strict model output:** The LLM policy requests a JSON object with an action and reason, reducing parser ambiguity and making logs reviewable.
- **Score from environment state:** Success depends on collecting the key, opening the door, and reaching the goal, not on a textual claim.
- **Deterministic baseline:** `--policy scripted` gives a fast local correctness check for the environment and scoring code.

## Files

- `llm_agent_world.py` - main challenge implementation.
- `tests/test_llm_agent_world.py` - unit tests for the harness.
- `examples/successful_episode_log.json` - example successful episode.
- `.env.example` - environment variable template for LLM runs.
- `malmo-benchmark-suite-paper.pdf` - benchmark reference paper.
- `Artificial_Intelligence_Benchmark_Analysis (3).pdf` - additional benchmark analysis.

## Submission

Repository URL:

```text
https://github.com/javaxhaskell/Project-malmo
```
