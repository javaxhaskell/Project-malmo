import unittest

from llm_agent_world import GridWorld, ScriptedPolicy, run_episode


class GridWorldHarnessTests(unittest.TestCase):
    def test_scripted_policy_completes_key_door_goal_task(self):
        log = run_episode(ScriptedPolicy(), max_steps=80, write_log=False)

        self.assertTrue(log["summary"]["goal_complete"])
        self.assertTrue(log["summary"]["key_collected"])
        self.assertTrue(log["summary"]["door_opened"])
        self.assertEqual(0, log["summary"]["invalid_actions"])

    def test_observation_exposes_valid_actions_and_state(self):
        world = GridWorld()
        obs = world.observe()

        self.assertIn("valid_actions", obs)
        self.assertIn("map", obs)
        self.assertIn("front", obs)
        self.assertIn("turn_left", obs["valid_actions"])
        self.assertIn("move_forward", obs["valid_actions"])

    def test_invalid_action_is_rejected_without_changing_position(self):
        world = GridWorld()
        before = (world.agent.x, world.agent.y)
        result = world.step("open_door")
        after = (world.agent.x, world.agent.y)

        self.assertFalse(result["valid"])
        self.assertEqual(before, after)
        self.assertEqual(1, world.invalid_actions)


if __name__ == "__main__":
    unittest.main()
