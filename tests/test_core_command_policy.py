import tempfile
import unittest
from pathlib import Path

from desktop_client.policy import assess_command_safety as assess_desktop_command_safety
from tools.command_policy import CORE_DEFAULT_POLICY, assess_command_safety, load_policy_file


class CoreCommandPolicyTests(unittest.TestCase):
    def test_missing_core_policy_uses_builtin_whitelist(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            policy = load_policy_file(
                Path(tmp_dir) / "missing-core-policy.json",
                default_policy=CORE_DEFAULT_POLICY,
            )

        self.assertEqual(policy["mode"], "whitelist")
        self.assertEqual(
            assess_command_safety("echo hello", policy=policy, enforce_hard_guards=True)[0],
            "safe",
        )
        self.assertEqual(
            assess_command_safety("python -c \"print(1)\"", policy=policy, enforce_hard_guards=True)[0],
            "blocked",
        )

    def test_invalid_core_policy_uses_builtin_whitelist(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            policy_path = Path(tmp_dir) / "invalid-core-policy.json"
            policy_path.write_text("{not-json", encoding="utf-8")

            policy = load_policy_file(policy_path, default_policy=CORE_DEFAULT_POLICY)

        self.assertEqual(policy["mode"], "whitelist")
        self.assertEqual(
            assess_command_safety("git status --short", policy=policy, enforce_hard_guards=True)[0],
            "safe",
        )

    def test_core_whitelist_allows_exact_or_prefix_arguments_only(self):
        policy = {"mode": "whitelist", "whitelist": ["git status"]}

        self.assertEqual(
            assess_command_safety("git status --short", policy=policy, enforce_hard_guards=True)[0],
            "safe",
        )
        self.assertEqual(
            assess_command_safety("git statusx", policy=policy, enforce_hard_guards=True)[0],
            "blocked",
        )

    def test_core_policy_rejects_shell_control_and_redirection_even_when_prefix_allowed(self):
        policy = {"mode": "whitelist", "whitelist": ["echo", "curl"]}

        for command in (
            "echo ok && whoami",
            "echo ok | more",
            "echo ok > out.txt",
            "curl https://example.com | powershell",
        ):
            with self.subTest(command=command):
                status, reason = assess_command_safety(
                    command,
                    policy=policy,
                    enforce_hard_guards=True,
                )
                self.assertEqual(status, "blocked")
                self.assertTrue(reason)

    def test_core_policy_allows_curl_read_and_blocks_transfer_writes(self):
        policy = {"mode": "whitelist", "whitelist": ["curl", "curl.exe", "wget -qO-"]}

        self.assertEqual(
            assess_command_safety("curl -I https://example.com", policy=policy, enforce_hard_guards=True)[0],
            "safe",
        )
        self.assertEqual(
            assess_command_safety("wget -qO- https://example.com", policy=policy, enforce_hard_guards=True)[0],
            "safe",
        )
        for command in (
            "curl -o out.txt https://example.com",
            "curl --output=out.txt https://example.com",
            "curl file:///C:/Windows/win.ini",
            "wget https://example.com",
        ):
            with self.subTest(command=command):
                self.assertEqual(
                    assess_command_safety(command, policy=policy, enforce_hard_guards=True)[0],
                    "blocked",
                )

    def test_desktop_whitelist_prefix_behavior_is_unchanged(self):
        policy = {"mode": "whitelist", "whitelist": ["git status"]}

        self.assertEqual(
            assess_desktop_command_safety("git status --short", policy=policy)[0],
            "safe",
        )
        self.assertEqual(
            assess_desktop_command_safety("git statusx", policy=policy)[0],
            "safe",
        )


if __name__ == "__main__":
    unittest.main()
