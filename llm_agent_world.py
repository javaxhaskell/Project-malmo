#!/usr/bin/env python3
"""LLM agent harness for a small key-and-door grid world.

The file is intentionally dependency-free. The LLM policy uses the OpenAI
Responses API through the Python standard library so the harness is easy to run
in a clean environment.
"""

from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.request
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


ACTION_SPACE = (
    "move_forward",
    "turn_left",
    "turn_right",
    "pick_up",
    "open_door",
    "look",
    "wait",
)

DIRECTIONS = ("N", "E", "S", "W")
DELTAS = {
    "N": (0, -1),
    "E": (1, 0),
    "S": (0, 1),
    "W": (-1, 0),
}
FACING_MARKERS = {
    "N": "^",
    "E": ">",
    "S": "v",
    "W": "<",
}

DEFAULT_LAYOUT = (
    "##########",
    "#A..K...##",
    "#.###.#..#",
    "#...#.#..#",
    "#.#.D.G..#",
    "#........#",
    "##########",
)


@dataclass
class AgentState:
    x: int
    y: int
    facing: str = "E"
    inventory: List[str] = field(default_factory=list)


@dataclass
class PolicyDecision:
    action: str
    reason: str
    raw_response: Optional[Dict[str, Any]] = None
    source: str = "unknown"


class GridWorld:
    """A deterministic 2D world with a key, a locked door, and a goal."""

    def __init__(self, layout: Sequence[str] = DEFAULT_LAYOUT) -> None:
        self.layout = [list(row) for row in layout]
        self.height = len(self.layout)
        self.width = len(self.layout[0])
        self.walls = set()
        self.key_position: Optional[Tuple[int, int]] = None
        self.door_position: Optional[Tuple[int, int]] = None
        self.goal_position: Optional[Tuple[int, int]] = None
        self.door_open = False

        start: Optional[Tuple[int, int]] = None
        for y, row in enumerate(self.layout):
            if len(row) != self.width:
                raise ValueError("All layout rows must have equal width.")
            for x, cell in enumerate(row):
                if cell == "#":
                    self.walls.add((x, y))
                elif cell == "A":
                    start = (x, y)
                    self.layout[y][x] = "."
                elif cell == "K":
                    self.key_position = (x, y)
                    self.layout[y][x] = "."
                elif cell == "D":
                    self.door_position = (x, y)
                    self.layout[y][x] = "."
                elif cell == "G":
                    self.goal_position = (x, y)
                    self.layout[y][x] = "."

        if start is None or self.key_position is None or self.door_position is None or self.goal_position is None:
            raise ValueError("Layout must include A, K, D, and G.")

        self.agent = AgentState(start[0], start[1])
        self.steps = 0
        self.invalid_actions = 0
        self.events: List[Dict[str, Any]] = []

    def cell_at(self, x: int, y: int) -> str:
        if x < 0 or y < 0 or x >= self.width or y >= self.height:
            return "out_of_bounds"
        if (x, y) in self.walls:
            return "wall"
        if self.key_position == (x, y):
            return "key"
        if self.door_position == (x, y):
            return "open_door" if self.door_open else "locked_door"
        if self.goal_position == (x, y):
            return "goal"
        return "empty"

    def front_position(self) -> Tuple[int, int]:
        dx, dy = DELTAS[self.agent.facing]
        return self.agent.x + dx, self.agent.y + dy

    def valid_actions(self) -> List[str]:
        valid = ["turn_left", "turn_right", "look", "wait"]
        front = self.cell_at(*self.front_position())
        if front in {"empty", "key", "goal", "open_door"}:
            valid.append("move_forward")
        if self.key_position == (self.agent.x, self.agent.y):
            valid.append("pick_up")
        if front == "locked_door" and "key" in self.agent.inventory:
            valid.append("open_door")
        return [action for action in ACTION_SPACE if action in set(valid)]

    def observe(self, radius: int = 2) -> Dict[str, Any]:
        visible_cells = []
        for dy in range(-radius, radius + 1):
            for dx in range(-radius, radius + 1):
                x = self.agent.x + dx
                y = self.agent.y + dy
                visible_cells.append(
                    {
                        "x": x,
                        "y": y,
                        "dx": dx,
                        "dy": dy,
                        "cell": self.cell_at(x, y),
                        "agent": dx == 0 and dy == 0,
                    }
                )

        gx, gy = self.goal_position or (-1, -1)
        kx, ky = self.key_position or (-1, -1)
        dx_goal = gx - self.agent.x
        dy_goal = gy - self.agent.y
        dx_key = kx - self.agent.x
        dy_key = ky - self.agent.y
        fx, fy = self.front_position()

        return {
            "step": self.steps,
            "objective": "Collect the key, open the locked door, and reach the goal.",
            "position": {"x": self.agent.x, "y": self.agent.y},
            "facing": self.agent.facing,
            "inventory": list(self.agent.inventory),
            "front": {"x": fx, "y": fy, "cell": self.cell_at(fx, fy)},
            "direction_to_key": None if self.key_position is None else {"dx": dx_key, "dy": dy_key},
            "direction_to_goal": {"dx": dx_goal, "dy": dy_goal},
            "door": {
                "position": {"x": self.door_position[0], "y": self.door_position[1]},
                "open": self.door_open,
            },
            "valid_actions": self.valid_actions(),
            "action_space": list(ACTION_SPACE),
            "legend": {
                "#": "wall",
                ".": "empty",
                "K": "key",
                "D": "locked door",
                "d": "open door",
                "G": "goal",
                "^>v<": "agent facing direction",
            },
            "map": self.render().splitlines(),
            "visible_cells": visible_cells,
        }

    def render(self) -> str:
        rows: List[str] = []
        for y in range(self.height):
            cells: List[str] = []
            for x in range(self.width):
                if (x, y) == (self.agent.x, self.agent.y):
                    cells.append(FACING_MARKERS[self.agent.facing])
                elif (x, y) in self.walls:
                    cells.append("#")
                elif self.key_position == (x, y):
                    cells.append("K")
                elif self.door_position == (x, y):
                    cells.append("d" if self.door_open else "D")
                elif self.goal_position == (x, y):
                    cells.append("G")
                else:
                    cells.append(".")
            rows.append("".join(cells))
        return "\n".join(rows)

    def step(self, action: str) -> Dict[str, Any]:
        self.steps += 1
        valid = action in self.valid_actions()
        message = "ok"

        if not valid:
            self.invalid_actions += 1
            message = "invalid action ignored"
        elif action == "turn_left":
            self.agent.facing = DIRECTIONS[(DIRECTIONS.index(self.agent.facing) - 1) % len(DIRECTIONS)]
        elif action == "turn_right":
            self.agent.facing = DIRECTIONS[(DIRECTIONS.index(self.agent.facing) + 1) % len(DIRECTIONS)]
        elif action == "move_forward":
            nx, ny = self.front_position()
            self.agent.x = nx
            self.agent.y = ny
        elif action == "pick_up":
            self.agent.inventory.append("key")
            self.key_position = None
            message = "key collected"
        elif action == "open_door":
            self.door_open = True
            message = "door opened"
        elif action in {"look", "wait"}:
            message = "no-op"

        success = (self.agent.x, self.agent.y) == self.goal_position and self.door_open
        result = {
            "valid": valid,
            "message": message,
            "success": success,
            "done": success,
            "position": {"x": self.agent.x, "y": self.agent.y},
            "facing": self.agent.facing,
            "inventory": list(self.agent.inventory),
            "door_open": self.door_open,
        }
        self.events.append({"step": self.steps, "action": action, "result": result})
        return result

    def passable_for_planning(self, x: int, y: int, allow_closed_door: bool = False) -> bool:
        cell = self.cell_at(x, y)
        return cell in {"empty", "key", "goal", "open_door"} or (allow_closed_door and cell == "locked_door")


class ScriptedPolicy:
    """Deterministic baseline used for tests and local smoke runs."""

    source = "scripted"

    def decide(self, observation: Dict[str, Any], world: Optional[GridWorld] = None) -> PolicyDecision:
        if world is None:
            return PolicyDecision("look", "No world object supplied to scripted policy.", source=self.source)

        if world.key_position == (world.agent.x, world.agent.y):
            return PolicyDecision("pick_up", "Standing on the key.", source=self.source)

        front = world.front_position()
        if front == world.door_position and "key" in world.agent.inventory and not world.door_open:
            return PolicyDecision("open_door", "Facing the locked door with the key.", source=self.source)

        if "key" not in world.agent.inventory:
            target = world.key_position
        elif not world.door_open:
            target = self._best_door_approach(world)
            if target == (world.agent.x, world.agent.y):
                return self._face_position(world, world.door_position, "Turn toward the door.")
        else:
            target = world.goal_position

        if target is None:
            return PolicyDecision("look", "No target available.", source=self.source)

        next_cell = self._next_cell_toward(world, target)
        if next_cell is None:
            return PolicyDecision("look", "No path found; observe again.", source=self.source)

        return self._move_toward(world, next_cell)

    def _best_door_approach(self, world: GridWorld) -> Tuple[int, int]:
        assert world.door_position is not None
        candidates = []
        dx, dy = world.door_position
        for ox, oy in DELTAS.values():
            pos = (dx + ox, dy + oy)
            if world.passable_for_planning(*pos):
                candidates.append(pos)
        best = None
        best_len = 9999
        for candidate in candidates:
            path = self._path(world, candidate)
            if path and len(path) < best_len:
                best = candidate
                best_len = len(path)
        return best or candidates[0]

    def _next_cell_toward(self, world: GridWorld, target: Tuple[int, int]) -> Optional[Tuple[int, int]]:
        path = self._path(world, target)
        if len(path) >= 2:
            return path[1]
        return None

    def _path(self, world: GridWorld, target: Tuple[int, int]) -> List[Tuple[int, int]]:
        start = (world.agent.x, world.agent.y)
        queue = deque([start])
        came_from: Dict[Tuple[int, int], Optional[Tuple[int, int]]] = {start: None}

        while queue:
            current = queue.popleft()
            if current == target:
                break
            cx, cy = current
            for dx, dy in DELTAS.values():
                nxt = (cx + dx, cy + dy)
                if nxt in came_from:
                    continue
                if not world.passable_for_planning(*nxt):
                    continue
                came_from[nxt] = current
                queue.append(nxt)

        if target not in came_from:
            return []

        path = [target]
        while path[-1] != start:
            parent = came_from[path[-1]]
            assert parent is not None
            path.append(parent)
        path.reverse()
        return path

    def _face_position(
        self,
        world: GridWorld,
        target: Optional[Tuple[int, int]],
        reason: str,
    ) -> PolicyDecision:
        if target is None:
            return PolicyDecision("look", "No target to face.", source=self.source)
        action = self._turn_action(world.agent.facing, self._direction_to((world.agent.x, world.agent.y), target))
        return PolicyDecision(action, reason, source=self.source)

    def _move_toward(self, world: GridWorld, next_cell: Tuple[int, int]) -> PolicyDecision:
        desired = self._direction_to((world.agent.x, world.agent.y), next_cell)
        if desired == world.agent.facing:
            return PolicyDecision("move_forward", "Advance along the planned path.", source=self.source)
        return PolicyDecision(self._turn_action(world.agent.facing, desired), "Turn toward the planned path.", source=self.source)

    def _direction_to(self, start: Tuple[int, int], end: Tuple[int, int]) -> str:
        sx, sy = start
        ex, ey = end
        dx, dy = ex - sx, ey - sy
        for direction, delta in DELTAS.items():
            if delta == (dx, dy):
                return direction
        raise ValueError("Target is not adjacent.")

    def _turn_action(self, current: str, desired: str) -> str:
        ci = DIRECTIONS.index(current)
        di = DIRECTIONS.index(desired)
        if (ci + 1) % len(DIRECTIONS) == di:
            return "turn_right"
        if (ci - 1) % len(DIRECTIONS) == di:
            return "turn_left"
        return "turn_right"


class OpenAIPolicy:
    """LLM policy backed by the OpenAI Responses API."""

    source = "openai_responses_api"

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: int = 30,
    ) -> None:
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        self.model = model or os.environ.get("OPENAI_MODEL", "gpt-5.4-mini")
        self.base_url = (base_url or os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")).rstrip("/")
        self.timeout = timeout
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY is required for --policy llm.")

    def decide(self, observation: Dict[str, Any], world: Optional[GridWorld] = None) -> PolicyDecision:
        schema = {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "action": {"type": "string", "enum": list(ACTION_SPACE)},
                "reason": {"type": "string"},
            },
            "required": ["action", "reason"],
        }
        prompt = {
            "task": "Choose exactly one valid action for the agent in the grid world.",
            "rules": [
                "Use only actions listed in observation.valid_actions.",
                "Collect the key before opening the door.",
                "Open the door before trying to reach the goal.",
                "Prefer the shortest safe route.",
            ],
            "observation": observation,
        }
        payload = {
            "model": self.model,
            "instructions": (
                "You are the policy for an embodied agent in a deterministic grid world. "
                "Return one JSON object with an action and a brief reason. Do not include prose outside JSON."
            ),
            "input": json.dumps(prompt, separators=(",", ":")),
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "grid_agent_action",
                    "description": "The next validated action for the grid-world agent.",
                    "strict": True,
                    "schema": schema,
                }
            },
            "max_output_tokens": 200,
        }
        data = self._post_json("/responses", payload)
        output_text = self._extract_output_text(data)
        try:
            parsed = json.loads(output_text)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Model returned non-JSON output: %r" % output_text) from exc

        action = parsed.get("action")
        reason = parsed.get("reason", "")
        if action not in observation["valid_actions"]:
            return PolicyDecision(
                action=str(action),
                reason="Model chose invalid action %r; environment will reject it." % action,
                raw_response=data,
                source=self.source,
            )
        return PolicyDecision(action=action, reason=reason, raw_response=data, source=self.source)

    def _post_json(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            self.base_url + path,
            data=body,
            headers={
                "Authorization": "Bearer " + self.api_key,
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError("OpenAI API request failed: %s %s" % (exc.code, detail)) from exc

    def _extract_output_text(self, response: Dict[str, Any]) -> str:
        if isinstance(response.get("output_text"), str):
            return response["output_text"]

        fragments: List[str] = []
        for item in response.get("output", []):
            for content in item.get("content", []):
                if isinstance(content.get("text"), str):
                    fragments.append(content["text"])
        if fragments:
            return "".join(fragments)
        raise RuntimeError("No text output found in model response.")


class AutoPolicy:
    """Use the LLM when credentials exist; otherwise use the deterministic policy."""

    def __init__(self, model: Optional[str] = None) -> None:
        if os.environ.get("OPENAI_API_KEY"):
            self.policy = OpenAIPolicy(model=model)
        else:
            self.policy = ScriptedPolicy()
        self.source = self.policy.source

    def decide(self, observation: Dict[str, Any], world: Optional[GridWorld] = None) -> PolicyDecision:
        return self.policy.decide(observation, world)


def score_episode(world: GridWorld, success: bool, max_steps: int) -> Dict[str, Any]:
    key_collected = "key" in world.agent.inventory
    door_opened = world.door_open
    invalid_rate = float(world.invalid_actions) / float(max(world.steps, 1))
    score = 0.70 * float(success) + 0.15 * float(key_collected) + 0.15 * float(door_opened)
    score -= min(0.20, invalid_rate)
    return {
        "goal_complete": success,
        "key_collected": key_collected,
        "door_opened": door_opened,
        "steps": world.steps,
        "invalid_actions": world.invalid_actions,
        "invalid_action_rate": round(invalid_rate, 4),
        "score": round(max(0.0, score), 4),
        "max_steps": max_steps,
    }


def run_episode(
    policy: Any,
    max_steps: int = 60,
    output_path: Optional[Path] = None,
    write_log: bool = True,
) -> Dict[str, Any]:
    world = GridWorld()
    events: List[Dict[str, Any]] = []
    success = False

    for _ in range(max_steps):
        observation = world.observe()
        decision = policy.decide(observation, world)
        result = world.step(decision.action)
        events.append(
            {
                "step": world.steps,
                "observation": observation,
                "decision": {
                    "source": decision.source,
                    "action": decision.action,
                    "reason": decision.reason,
                },
                "result": result,
                "map_after_action": world.render().splitlines(),
            }
        )
        if result["done"]:
            success = True
            break

    summary = score_episode(world, success, max_steps)
    log = {
        "metadata": {
            "created_at_unix": int(time.time()),
            "world": "2d_key_door_grid",
            "policy": getattr(policy, "source", policy.__class__.__name__),
            "observation_format": "structured JSON with map, position, facing, inventory, front cell, landmarks, and valid actions",
            "action_space": list(ACTION_SPACE),
            "objective": "Collect the key, open the locked door, and reach the goal.",
        },
        "summary": summary,
        "initial_map": GridWorld().render().splitlines(),
        "final_map": world.render().splitlines(),
        "events": events,
    }

    if write_log:
        if output_path is None:
            run_dir = Path("runs") / ("run_%d" % int(time.time()))
            run_dir.mkdir(parents=True, exist_ok=True)
            output_path = run_dir / "episode_log.json"
        else:
            output_path.parent.mkdir(parents=True, exist_ok=True)
        log["metadata"]["log_path"] = str(output_path)
        output_path.write_text(json.dumps(log, indent=2), encoding="utf-8")

    return log


def build_policy(args: argparse.Namespace) -> Any:
    if args.policy == "scripted":
        return ScriptedPolicy()
    if args.policy == "llm":
        return OpenAIPolicy(model=args.model, timeout=args.timeout)
    if args.policy == "auto":
        return AutoPolicy(model=args.model)
    raise ValueError("Unknown policy: %s" % args.policy)


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run an LLM agent in a key-and-door grid world.")
    parser.add_argument("--policy", choices=["llm", "scripted", "auto"], default="auto")
    parser.add_argument("--model", default=os.environ.get("OPENAI_MODEL", "gpt-5.4-mini"))
    parser.add_argument("--max-steps", type=int, default=60)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--output", type=Path, default=None, help="Path for the episode JSON log.")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    policy = build_policy(args)
    log = run_episode(policy, max_steps=args.max_steps, output_path=args.output)
    print(json.dumps(log["summary"], indent=2))
    print("\nFinal map:")
    print("\n".join(log["final_map"]))
    if "log_path" in log["metadata"]:
        print("\nEpisode log: %s" % log["metadata"]["log_path"])
    return 0 if log["summary"]["goal_complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
