# Copyright 2026 FlagOS Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

import check_ci_pins
import run_ci_targets
import select_backends
import select_tests


class TemporaryRepositoryTestCase(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.repo_root = Path(self.temporary_directory.name)
        (self.repo_root / "tests/deep/nested").mkdir(parents=True)
        (self.repo_root / "benchmark/deep/nested").mkdir(parents=True)

    def tearDown(self):
        self.temporary_directory.cleanup()

    def make_file(self, relative_path: str) -> None:
        path = self.repo_root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()


class SelectTestsTest(TemporaryRepositoryTestCase):
    def test_environment_and_operator_changes_are_combined(self):
        self.make_file("tests/test_mul.py")

        mode, tests, benchmarks = select_tests.select_targets(
            self.repo_root,
            ["pyproject.toml", "src/flaggems_vllm/ops/mul.py"],
        )

        self.assertEqual(mode, "smoke")
        self.assertEqual(tests, ["tests/test_mul.py"])
        self.assertEqual(benchmarks, [])

    def test_unknown_operator_change_selects_all_tests(self):
        self.make_file("tests/test_first.py")
        self.make_file("tests/deep/nested/test_second.py")

        mode, tests, _ = select_tests.select_targets(
            self.repo_root,
            ["src/flaggems_vllm/ops/unknown_operator.py"],
        )

        self.assertEqual(mode, "selected")
        self.assertEqual(
            tests,
            ["tests/deep/nested/test_second.py", "tests/test_first.py"],
        )

    def test_documentation_change_is_skipped(self):
        self.assertEqual(
            select_tests.select_targets(self.repo_root, ["docs/guide.md"]),
            ("skip", [], []),
        )

    def test_nested_target_with_spaces_is_preserved(self):
        target = "tests/deep/nested/test_space name.py"
        self.make_file(target)

        mode, tests, _ = select_tests.select_targets(self.repo_root, [target])

        self.assertEqual(mode, "selected")
        self.assertEqual(tests, [target])

    def test_reads_null_delimited_unicode_paths(self):
        changed_files = self.repo_root / "changed.bin"
        changed_files.write_bytes("tests/test 空格.py\0docs/a.md\0".encode())
        self.assertEqual(
            select_tests.read_changed_files(str(changed_files)),
            ["tests/test 空格.py", "docs/a.md"],
        )

    def test_missing_changed_files_input_fails(self):
        with self.assertRaises(FileNotFoundError):
            select_tests.read_changed_files(str(self.repo_root / "missing"))


class SelectBackendsTest(unittest.TestCase):
    registry = [
        {
            "backend": "ascend-cann850",
            "runner_label": "ascend",
            "label": "vendor/Ascend",
            "gpu_check": "tools/gpu_check_ascend.sh",
            "enabled": True,
        },
        {
            "backend": "kunlunxin",
            "runner_label": "kunlunxin",
            "label": "vendor/Kunlunxin",
            "gpu_check": "tools/gpu_check_kunlunxin.sh",
            "enabled": True,
        },
        {
            "backend": "nvidia-cuda133",
            "runner_label": "h20",
            "label": "vendor/NVIDIA",
            "gpu_check": "tools/gpu_check_nvidia.sh",
            "enabled": True,
        },
    ]

    def test_pr_label_selects_only_matching_backend(self):
        selected = select_backends.select_backends(
            self.registry, {"vendor/Ascend"}, all_enabled=False
        )
        self.assertEqual([entry["backend"] for entry in selected], ["ascend-cann850"])

    def test_all_enabled_still_excludes_nvidia(self):
        selected = select_backends.select_backends(
            self.registry, set(), all_enabled=True
        )
        self.assertEqual(
            [entry["backend"] for entry in selected],
            ["ascend-cann850", "kunlunxin"],
        )

    def test_label_json_requires_string_array(self):
        with self.assertRaises(ValueError):
            select_backends.parse_labels('{"vendor": "Ascend"}')


class RunCiTargetsTest(TemporaryRepositoryTestCase):
    def test_json_round_trip_and_safe_argv(self):
        target = "tests/deep/nested/test_$(touch pwned) 空格.py"
        self.make_file(target)
        raw = json.dumps(
            {
                "schema_version": 1,
                "mode": "selected",
                "tests": [target],
                "benchmarks": [],
            }
        )

        targets = run_ci_targets.load_targets(raw)
        validated = run_ci_targets.validate_target(self.repo_root, target, "tests")
        command = run_ci_targets.build_commands(targets)[0]

        self.assertEqual(validated, target)
        self.assertEqual(command[-1], target)
        self.assertNotIn("touch", command)

    def test_policy_is_fail_closed_by_default(self):
        targets = {"tests": ["tests/test_op.py"], "benchmarks": []}
        policy = {
            "allow_all_tests": False,
            "tests_allow": [],
            "benchmarks_enabled": False,
            "allow_all_benchmarks": False,
            "benchmarks_allow": [],
        }
        self.assertEqual(
            run_ci_targets.apply_policy(targets, policy),
            {"tests": [], "benchmarks": []},
        )

    def test_benchmark_command_uses_bounded_iterations(self):
        commands = run_ci_targets.build_commands(
            {"tests": [], "benchmarks": ["benchmark/test_op.py"]}
        )
        self.assertIn("--warmup", commands[0])
        self.assertEqual(commands[0][commands[0].index("--warmup") + 1], "1")
        self.assertIn("--iter", commands[0])
        self.assertEqual(commands[0][commands[0].index("--iter") + 1], "1")

    def test_rejects_unsafe_or_malformed_targets(self):
        with self.assertRaises(ValueError):
            run_ci_targets.load_targets(
                '{"schema_version":1,"tests":"tests/test_op.py","benchmarks":[]}'
            )
        with self.assertRaises(ValueError):
            run_ci_targets.validate_target(
                self.repo_root, "tests/../secrets.py", "tests"
            )


class CiPinsTest(unittest.TestCase):
    def test_three_flaggems_pins_are_identical(self):
        repo_root = Path(__file__).resolve().parents[1]
        pins = check_ci_pins.extract_pins(repo_root)
        self.assertEqual(len(pins), 3)
        self.assertEqual(len(set(pins)), 1)


class CiWorkflowPolicyTest(unittest.TestCase):
    def test_all_backend_fanout_requires_an_explicit_request(self):
        repo_root = Path(__file__).resolve().parents[1]
        workflow = (repo_root / ".github/workflows/basic-ci.yml").read_text(
            encoding="utf-8"
        )
        all_enabled = workflow.split("ALL_ENABLED: >-", maxsplit=1)[1].split(
            "run: |", maxsplit=1
        )[0]

        self.assertNotIn("github.event_name == 'push'", all_enabled)
        self.assertIn("inputs.run_non_nvidia == true", all_enabled)
        self.assertIn("'ci/all-vendors'", all_enabled)

    def test_self_hosted_guards_check_the_pull_request_author(self):
        repo_root = Path(__file__).resolve().parents[1]
        workflow = (repo_root / ".github/workflows/basic-ci.yml").read_text(
            encoding="utf-8"
        )
        author_guard = "github.event.pull_request.user.login != 'dependabot[bot]'"

        self.assertEqual(workflow.count(author_guard), 3)
        self.assertNotIn("github.actor != 'dependabot[bot]'", workflow)


class CiSummaryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        repo_root = Path(__file__).resolve().parents[1]
        workflow = (repo_root / ".github/workflows/basic-ci.yml").read_text(
            encoding="utf-8"
        )
        summary = workflow.split("  multi-backend-summary:", maxsplit=1)[1]
        cls.script = textwrap.dedent(
            summary.split("        run: |\n", maxsplit=1)[1]
        ).strip()

    def run_summary(self, **overrides):
        values = {
            "CODE_STYLE_RESULT": "success",
            "SELECT_TARGETS_RESULT": "success",
            "NVIDIA_RESULT": "skipped",
            "NON_NVIDIA_RESULT": "skipped",
            "SHOULD_RUN": "false",
            "HAS_NON_NVIDIA_BACKENDS": "false",
            "EVENT_NAME": "push",
            "TRUSTED_RUN": "true",
        }
        values.update(overrides)
        return subprocess.run(
            ["bash", "-c", self.script],
            env={**os.environ, **values},
            text=True,
            capture_output=True,
            check=False,
        )

    def test_expected_accelerator_results_succeed(self):
        cases = {
            "trusted_nvidia_only": {
                "SHOULD_RUN": "true",
                "NVIDIA_RESULT": "success",
            },
            "trusted_full_matrix": {
                "SHOULD_RUN": "true",
                "HAS_NON_NVIDIA_BACKENDS": "true",
                "NVIDIA_RESULT": "success",
                "NON_NVIDIA_RESULT": "success",
            },
            "pr_backend_preflight_only": {
                "HAS_NON_NVIDIA_BACKENDS": "true",
                "EVENT_NAME": "pull_request",
                "NON_NVIDIA_RESULT": "success",
            },
            "untrusted_fork": {
                "SHOULD_RUN": "true",
                "HAS_NON_NVIDIA_BACKENDS": "true",
                "EVENT_NAME": "pull_request",
                "TRUSTED_RUN": "false",
            },
            "no_targets": {},
        }

        for name, values in cases.items():
            with self.subTest(name=name):
                result = self.run_summary(**values)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_missing_or_unexpected_results_fail(self):
        cases = {
            "preparation_failed": {"CODE_STYLE_RESULT": "failure"},
            "expected_nvidia_skipped": {
                "SHOULD_RUN": "true",
                "NVIDIA_RESULT": "skipped",
            },
            "expected_backend_failed": {
                "SHOULD_RUN": "true",
                "HAS_NON_NVIDIA_BACKENDS": "true",
                "NVIDIA_RESULT": "success",
                "NON_NVIDIA_RESULT": "failure",
            },
            "unexpected_backend_run": {"NON_NVIDIA_RESULT": "success"},
        }

        for name, values in cases.items():
            with self.subTest(name=name):
                result = self.run_summary(**values)
                self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
