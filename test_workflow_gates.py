"""Unit tests verifying GitHub Actions workflow gating and integrity."""

from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile
import shlex
import unittest
import yaml  # type: ignore[import-untyped]

REPO_ROOT = Path(__file__).resolve().parent
WORKFLOW_PATH = REPO_ROOT / ".github/workflows/python-install-and-test.yml"
PLAY_WORKFLOW_PATH = REPO_ROOT / ".github/workflows/generate-play-artifact.yml"
PRODUCTION_EVENTS = (
    "github.event_name == 'schedule' || github.event_name == 'workflow_dispatch'"
)


class TestWorkflowGates(unittest.TestCase):
    """Verify that ci-passed aggregate job gates all jobs in the PR workflow."""

    def setUp(self) -> None:
        with open(WORKFLOW_PATH, encoding="utf-8") as f:
            self.workflow = yaml.safe_load(f)
        self.jobs = self.workflow.get("jobs", {})

    def test_ci_passed_job_exists(self) -> None:
        """Verify ci-passed job exists and runs unconditionally with always()."""
        self.assertTrue("ci-passed" in self.jobs)
        ci_passed = self.jobs["ci-passed"]
        self.assertEqual(ci_passed.get("if"), "always()")
        self.assertFalse(
            "strategy" in ci_passed,
            "ci-passed must not use a matrix strategy so its name is version-free",
        )

    def test_ci_passed_gates_every_other_workflow_job(self) -> None:
        """Verify ci-passed depends on every other job in the workflow."""
        ci_passed = self.jobs["ci-passed"]
        needs = set(ci_passed.get("needs", []))
        all_other_jobs = set(self.jobs.keys()) - {"ci-passed"}

        self.assertEqual(
            needs,
            all_other_jobs,
            f"Jobs missing from ci-passed needs: {all_other_jobs - needs}",
        )


class TestRustCiRunsEveryTest(unittest.TestCase):
    """Slow Rust tests are #[ignore]d locally; CI must still run them."""

    def test_rust_test_and_coverage_steps_include_ignored_tests(self) -> None:
        # Catches dropping --include-ignored from either step, which would
        # silently skip the slow tests everywhere.
        with open(WORKFLOW_PATH, encoding="utf-8") as f:
            steps = yaml.safe_load(f)["jobs"]["rust-cfr-inputs"]["steps"]
        commands = {step.get("name"): step.get("run", "") for step in steps}
        # The exact commands, so a narrowing option (such as `--lib`, which
        # skips the integration tests where every slow test lives) or a flag
        # hidden in a comment fails too, and neither step may be allowed to
        # fail. TestRustSlowStepsSkip covers when they may be skipped.
        self.assertEqual(
            shlex.split(commands["Test"], comments=True),
            ["cargo", "test", "--locked", "--release", "--", "--include-ignored"],
        )
        self.assertEqual(
            shlex.split(commands["Check 100% line coverage"], comments=True),
            [
                "cargo",
                "llvm-cov",
                "--locked",
                "--release",
                "--fail-under-lines",
                "100",
                "--show-missing-lines",
                "--",
                "--include-ignored",
            ],
        )
        for step in steps:
            if step.get("name") in ("Test", "Check 100% line coverage"):
                self.assertNotIn("continue-on-error", step)
                # A custom shell (such as `bash -n {0}`) could parse the
                # command without running it.
                self.assertNotIn("shell", step)
        with open(WORKFLOW_PATH, encoding="utf-8") as f:
            workflow = yaml.safe_load(f)
        job = workflow["jobs"]["rust-cfr-inputs"]
        self.assertNotIn("continue-on-error", job)
        for scope in (workflow, job):
            self.assertNotIn("shell", scope.get("defaults", {}).get("run", {}))


class RustCheckout:
    """An origin and a shallow checkout of a PR's merge, as Actions makes one."""

    def __init__(self, folder: str) -> None:
        self.origin = Path(folder) / "origin"
        self.checkout = Path(folder) / "checkout"
        self.output = Path(folder) / "output"
        self.output.touch()
        # A git hook exports GIT_DIR and others, which would point these
        # commands at this repository.
        self.env = {
            key: value for key, value in os.environ.items() if not key.startswith("GIT")
        } | {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull}
        self.origin.mkdir()
        self.git(self.origin, "init", "--quiet", "--initial-branch=main")
        for path in (
            ".gitattributes",
            ".github/workflows/python-install-and-test.yml",
            "README.md",
            "native/cfr/Cargo.toml",
            "native/cfr/src/lib.rs",
        ):
            self.write(path, "main\n")
        self.commit()

    def git(self, folder: Path, *args: str) -> None:
        """Run one git command with a throwaway identity."""
        subprocess.run(
            ["git", "-c", "user.name=T", "-c", "user.email=t@example.com", *args],
            cwd=folder,
            env=self.env,
            capture_output=True,
            check=True,
        )

    def write(self, path: str, text: str) -> None:
        """Write one file in the origin's working tree."""
        file = self.origin / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(text, encoding="utf-8")

    def commit(self) -> None:
        """Commit everything in the origin's working tree."""
        self.git(self.origin, "add", "--all", "--force")
        self.git(self.origin, "commit", "--quiet", "--message=change")

    def check_out_pull_request(self, path: str, base: str = "main") -> None:
        """Change one file on a PR branch and check out its merge into base."""
        self.git(self.origin, "checkout", "--quiet", "-b", "pr", base)
        self.write(path, "pull request\n")
        self.commit()
        self.git(self.origin, "checkout", "--quiet", "--detach", base)
        self.git(self.origin, "merge", "--quiet", "--no-ff", "--message=m", "pr")
        self.git(self.origin, "update-ref", "refs/pull/1/merge", "HEAD")
        self.check_out("refs/pull/1/merge")

    def check_out(self, ref: str) -> None:
        """Fetch one ref as deep as the job's checkout does, and detach there."""
        with open(WORKFLOW_PATH, encoding="utf-8") as f:
            step = yaml.safe_load(f)["jobs"]["rust-cfr-inputs"]["steps"][0]
        depth = f"--depth={step.get('with', {}).get('fetch-depth', 1)}"
        self.checkout.mkdir()
        self.git(self.checkout, "init", "--quiet")
        url = self.origin.as_uri()
        self.git(self.checkout, "fetch", "--quiet", depth, url, ref)
        self.git(self.checkout, "checkout", "--quiet", "--detach", "FETCH_HEAD")

    def run_step(
        self, event: str = "pull_request", base: str = "main", path: str = ""
    ) -> str:
        """Run the workflow's check and return what it wrote as step outputs."""
        with open(WORKFLOW_PATH, encoding="utf-8") as f:
            job = yaml.safe_load(f)["jobs"]["rust-cfr-inputs"]
        step = next(step for step in job["steps"] if step.get("id") == "rust-inputs")
        folder = job["defaults"]["run"]["working-directory"]
        env = self.env | {
            "GITHUB_EVENT_NAME": event,
            "GITHUB_OUTPUT": str(self.output),
            "GITHUB_BASE_REF": base,
        }
        env["PATH"] = path + env["PATH"]
        # Actions' default shell. A nonzero exit would fail the job.
        subprocess.run(
            ["bash", "-e", "-c", step["run"]],
            cwd=self.checkout / step.get("working-directory", folder),
            env=env,
            capture_output=True,
            check=True,
        )
        return self.output.read_text(encoding="utf-8")


@unittest.skipIf(os.name == "nt", "the step runs in bash on Linux")
class TestRustSlowStepsSkip(unittest.TestCase):
    """The slow Rust steps are skipped only when the Rust inputs are main's."""

    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.repo = RustCheckout(folder.name)

    def test_only_the_slow_steps_depend_on_the_check(self) -> None:
        # Catches a condition that skips when the output is unset, a cheap
        # step or the whole job becoming skippable, and a check that could
        # come too late to matter.
        with open(WORKFLOW_PATH, encoding="utf-8") as f:
            job = yaml.safe_load(f)["jobs"]["rust-cfr-inputs"]
        self.assertNotIn("if", job)
        conditions = {step["name"]: step["if"] for step in job["steps"] if "if" in step}
        expected = "steps.rust-inputs.outputs.unchanged != 'true'"
        self.assertEqual(
            conditions, {"Test": expected, "Check 100% line coverage": expected}
        )
        self.assertEqual(
            [step.get("id") for step in job["steps"][:2]], [None, "rust-inputs"]
        )

    def test_a_pull_request_with_main_s_rust_inputs_skips(self) -> None:
        # Catches the check never skipping, which would be safe but useless.
        self.repo.check_out_pull_request("README.md")
        self.assertEqual(self.repo.run_step(), "unchanged=true\n")

    def test_the_package_names_no_file_outside_native(self) -> None:
        # Catches a build or test input that the check does not compare, such
        # as include_str!("../../../x"), a path dependency, a build script
        # reading the repository, or a symlink.
        package = REPO_ROOT / "native" / "cfr"
        files = list(package.glob("*.*"))
        for name in ("src", "tests"):
            files += (package / name).rglob("*")
        self.assertGreater(len(files), 10)
        for path in files:
            with self.subTest(path=path):
                self.assertFalse(path.is_symlink())
                if path.suffix in (".rs", ".toml"):
                    self.assertNotIn("../", path.read_text(encoding="utf-8"))

    def test_a_push_to_main_never_skips(self) -> None:
        # Catches either missing guard. The push is a merge that changes no
        # Rust, so the comparison itself matches; Actions leaves the base
        # empty, but the event alone must be enough.
        self.repo.check_out_pull_request("README.md")
        for base in ("", "main"):
            with self.subTest(base=base):
                self.assertEqual(self.repo.run_step(event="push", base=base), "")

    def test_any_changed_rust_input_runs_the_slow_steps(self) -> None:
        # Catches each path missing from the list, including the files
        # outside native/cfr that Cargo or Git would read, and paths
        # taken relative to native/cfr, which would match nothing.
        for path in (
            ".cargo/config.toml",
            ".gitattributes",
            ".github/workflows/python-install-and-test.yml",
            "Cargo.toml",
            "native/.cargo/config.toml",
            "native/Cargo.toml",
            "native/cfr/Cargo.toml",
            "native/cfr/src/lib.rs",
            "native/cfr/tests/pegging_golden.txt",
        ):
            with self.subTest(path=path), tempfile.TemporaryDirectory() as folder:
                repo = RustCheckout(folder)
                repo.check_out_pull_request(path)
                self.assertEqual(repo.run_step(), "")

    def test_a_stacked_pull_request_runs_the_slow_steps(self) -> None:
        # Catches skipping when the base is not main: the comparison with that
        # base says nothing about main, and changing the base later starts no
        # new run.
        self.repo.check_out_pull_request("README.md")
        self.assertEqual(self.repo.run_step(base="stack"), "")

    def test_a_head_that_is_not_a_merge_runs_the_slow_steps(self) -> None:
        # Catches comparing with HEAD^1 when it is the pull request's own
        # earlier commit, which may hold the Rust change.
        self.repo.write("native/cfr/src/lib.rs", "pull request\n")
        self.repo.commit()
        self.repo.write("README.md", "pull request\n")
        self.repo.commit()
        self.repo.check_out("main")
        self.assertEqual(self.repo.run_step(), "")

    def test_a_failed_comparison_runs_the_slow_steps(self) -> None:
        # Catches treating every diff status but 1 (a difference) as a match,
        # and failing the job instead of running everything. A stand-in git
        # fails on one command, with Git's fatal status.
        self.repo.check_out_pull_request("README.md")
        bin_dir = self.repo.output.with_name("bin")
        bin_dir.mkdir()
        fake = bin_dir / "git"
        for command in ("rev-parse", "diff"):
            fake.write_text(
                f'#!/bin/sh\n[ "$1" = {command} ] && exit 128\n'
                f'exec {shutil.which("git")} "$@"\n'
            )
            fake.chmod(0o755)
            with self.subTest(command=command):
                path = f"{bin_dir}{os.pathsep}"
                self.assertEqual(self.repo.run_step(path=path), "")


class TestRustHooks(unittest.TestCase):
    """The local Rust hooks run at their stated stages, on the right package."""

    def test_hooks_run_at_their_stages(self) -> None:
        # Catches rust-fmt, or any hook without its own stages, running on
        # push as well as on commit, and clippy or the fast tests moving to
        # commit, where they would slow every commit.
        with open(REPO_ROOT / ".pre-commit-config.yaml", encoding="utf-8") as f:
            config = yaml.safe_load(f)
        repos = config["repos"]
        self.assertEqual(
            config["default_install_hook_types"], ["pre-commit", "pre-push"]
        )
        self.assertEqual(config["default_stages"], ["pre-commit"])
        # These four upstream hooks name push in their own manifest, so they
        # must be scoped here or they would run on push too.
        upstream = {
            hook["id"]: hook.get("stages")
            for repo in repos
            for hook in repo["hooks"]
            if hook["id"]
            in (
                "check-shebang-scripts-are-executable",
                "destroyed-symlinks",
                "end-of-file-fixer",
                "trailing-whitespace",
            )
        }
        self.assertEqual(upstream, dict.fromkeys(upstream, ["pre-commit", "manual"]))
        self.assertEqual(len(upstream), 4)
        stages = {
            hook["id"]: hook.get("stages")
            for repo in repos
            for hook in repo["hooks"]
            if hook["id"].startswith("rust-")
        }
        self.assertEqual(
            stages,
            {
                "rust-fmt": ["pre-commit"],
                "rust-clippy": ["pre-push"],
                "rust-fast-tests": ["pre-push"],
            },
        )

    @unittest.skipIf(os.name == "nt", "the hook wrapper is a POSIX shell script")
    def test_cargo_hook_ignores_cdpath(self) -> None:
        # Catches the wrapper's `cd` following an exported CDPATH into a
        # same-named folder in another checkout. A stand-in `cargo` on PATH
        # prints the folder it runs in.
        with tempfile.TemporaryDirectory() as folder:
            other = Path(folder) / "other"
            (other / "scripts").mkdir(parents=True)
            (other / "native" / "cfr").mkdir(parents=True)
            bin_dir = Path(folder) / "bin"
            bin_dir.mkdir()
            fake = bin_dir / "cargo"
            fake.write_text("#!/bin/sh\npwd -P\n")
            fake.chmod(0o755)
            # CARGO_HOME points at the stand-in, so a real Cargo cannot be
            # picked ahead of it.
            env = dict(
                os.environ,
                CARGO_HOME=folder,
                CDPATH=str(other),
                HOME=folder,
                PATH=os.environ["PATH"],
            )
            result = subprocess.run(
                ["scripts/cargo_hook.sh", "--version"],
                cwd=REPO_ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=True,
            )
        expected = (REPO_ROOT / "native" / "cfr").resolve()
        self.assertEqual(result.stdout.strip().splitlines()[-1], str(expected))


class TestPlayReleaseWorkflow(unittest.TestCase):
    """Production enforces the gate and the release notes state its outcome."""

    def setUp(self) -> None:
        with open(PLAY_WORKFLOW_PATH, encoding="utf-8") as f:
            jobs = yaml.safe_load(f)["jobs"]
        self.generate = {step["name"]: step for step in jobs["generate-table"]["steps"]}
        self.release = {
            step["name"]: step for step in jobs["release-artifact"]["steps"]
        }

    def command(self, name: str) -> list[str]:
        return shlex.split(self.generate[name]["run"].replace("\\\n", ""))

    def test_production_adds_only_the_enforced_gate(self) -> None:
        self.assertEqual(
            self.command("Generate production artifact"),
            [
                "python",
                "-u",
                "artifact_pipeline/generate_play_table.py",
                "--analytical-max-iterations=40",
                "--full-hand-policy-max-iterations=2",
                "--outer-iterations=2",
                "--ibr-iterations=2",
                "--ibr-samples=30000",
                "--rollouts-per-action=2",
                "--policy-table-samples=200",
                "--samples=13000",
                "--promotion-gate=enforce",
                "--no-resume",
                "--seed=42",
            ],
        )
        self.assertEqual(
            self.generate["Generate production artifact"]["if"], PRODUCTION_EVENTS
        )
        self.assertFalse(
            any(
                "promotion-gate" in part
                for part in self.command("Generate bounded PR artifact")
            )
        )

    def test_every_run_summarizes_the_gate_for_the_release_notes(self) -> None:
        summarize = self.generate["Summarize promotion gate"]
        self.assertFalse("if" in summarize)
        self.assertTrue("release_summary" in summarize["run"])
        self.assertEqual(
            self.generate["Upload promotion gate summary"]["with"]["path"],
            "expected_play_points.gate.md",
        )
        self.assertEqual(
            self.release["Download promotion gate summary"]["with"]["name"],
            self.generate["Upload promotion gate summary"]["with"]["name"],
        )
        body = self.release["Publish rolling release"]["with"]["body"]
        self.assertTrue("${{ steps.gate_summary.outputs.text }}" in body)
        self.assertEqual(
            self.release["Capture promotion gate summary"]["id"], "gate_summary"
        )


class TestDiagnosticWorkflow(unittest.TestCase):
    """Guard manual execution and evidence preservation without dispatching."""

    def test_manual_read_only_serial_job_keeps_upload_on_failure(self):
        path = Path(__file__).parent / ".github/workflows/diagnose-crib-v4.yml"
        workflow = yaml.load(path.read_text(), Loader=yaml.BaseLoader)
        self.assertEqual(set(workflow["on"]), {"workflow_dispatch"})
        self.assertEqual(
            workflow["permissions"], {"contents": "read", "actions": "read"}
        )
        self.assertEqual(len(workflow["jobs"]), 1)
        job = workflow["jobs"]["first-shard"]
        self.assertEqual(job["timeout-minutes"], "240")
        runtime = next(s for s in job["steps"] if "setup-python@" in s.get("uses", ""))
        self.assertEqual(runtime["with"], {"python-version-file": ".python-version"})
        self.assertNotIn("strategy", job)
        upload = job["steps"][-1]
        self.assertEqual(upload["if"], "always()")
        self.assertTrue(upload["uses"].startswith("actions/upload-artifact@"))
        self.assertNotIn(
            "release", " ".join(step.get("uses", "") for step in job["steps"])
        )

    def test_input_retrieval_falls_back_after_asset_replacement(self):
        workflow = yaml.load(
            (
                Path(__file__).parent / ".github/workflows/diagnose-crib-v4.yml"
            ).read_text(),
            Loader=yaml.BaseLoader,
        )
        steps = workflow["jobs"]["first-shard"]["steps"]
        retrieve = next(
            step for step in steps if step.get("name", "").startswith("Retrieve")
        )
        self.assertTrue("verified_inputs" in retrieve["run"])
        download = retrieve["run"].split("# Every route")[0]
        fake = r"""import os, sys
from pathlib import Path
client = any('697897857' in value or 'client.json' in value for value in sys.argv)
content = 'client' if client else 'full'
if sys.argv[1] == 'api':
    if os.environ['IDS_AVAILABLE'] != 'yes':
        sys.exit(1)
    print(content, end='')
else:
    Path(sys.argv[sys.argv.index('--output') + 1]).write_text(content)
    with Path('fallbacks').open('a') as log:
        log.write(content + '\n')
"""
        for available in ("yes", "no"):
            with self.subTest(
                available=available
            ), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                gh = root / "gh"
                gh.write_text(f"#!{sys.executable}\n" + fake)
                gh.chmod(0o700)
                result = subprocess.run(
                    ["bash", "-e", "-c", download],
                    cwd=root,
                    env={
                        **os.environ,
                        "PATH": f"{root}{os.pathsep}{os.environ['PATH']}",
                        "IDS_AVAILABLE": available,
                    },
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual((root / "inputs/full.json").read_text(), "full")
                self.assertEqual((root / "inputs/client.json").read_text(), "client")
                self.assertEqual((root / "fallbacks").exists(), available == "no")

    def test_resume_validation_precedes_restore_and_uses_environment_input(self):
        workflow = yaml.load(
            (
                Path(__file__).parent / ".github/workflows/diagnose-crib-v4.yml"
            ).read_text(),
            Loader=yaml.BaseLoader,
        )
        steps = workflow["jobs"]["first-shard"]["steps"]
        names = [step.get("name") for step in steps]
        validate = names.index("Verify resume run provenance")
        restore = names.index("Restore compatible per-group checkpoints")
        measure = names.index("Measure the declared first shard")
        self.assertLess(validate, restore)
        self.assertLess(restore, measure)
        self.assertTrue(
            'validate_resume_run(json.load(sys.stdin), os.environ["GITHUB_REPOSITORY"])'
            in steps[validate]["run"]
        )
        self.assertTrue('[[ "$RESUME_RUN_ID" =~ ^[0-9]+$ ]]' in steps[validate]["run"])
        self.assertEqual(
            steps[validate]["env"]["RESUME_RUN_ID"], "${{ inputs.resume_run_id }}"
        )
        self.assertFalse(
            any("${{ inputs.resume_run_id }}" in step.get("run", "") for step in steps)
        )


class TestSurveyWorkflow(unittest.TestCase):
    """Check budget and isolation in the actual committed workflow."""

    def test_budget_parallelism_resume_and_always_upload(self):
        path = Path(__file__).parent / ".github/workflows/survey-crib-v4.yml"
        workflow = yaml.load(path.read_text(), Loader=yaml.BaseLoader)
        self.assertEqual(set(workflow["on"]), {"workflow_dispatch"})
        self.assertEqual(
            workflow["permissions"], {"contents": "read", "actions": "read"}
        )
        self.assertNotIn("concurrency", workflow)
        self.assertEqual(len(workflow["jobs"]), 1)
        job = workflow["jobs"]["survey-shard"]
        self.assertEqual(job["strategy"]["matrix"]["shard"], ["1", "2", "3", "4"])
        self.assertEqual(job["strategy"]["max-parallel"], "4")
        self.assertEqual(job["strategy"]["fail-fast"], "false")
        self.assertEqual(job["timeout-minutes"], "330")
        self.assertTrue("${{ matrix.shard }}" in job["concurrency"]["group"])
        self.assertEqual(job["concurrency"]["cancel-in-progress"], "false")
        steps = job["steps"]
        self.assertTrue("300 * 60" in steps[0]["run"])
        runtime = next(s for s in steps if "setup-python@" in s.get("uses", ""))
        self.assertEqual(runtime["with"], {"python-version-file": ".python-version"})
        names = [s.get("name") for s in steps]
        validate = names.index("Verify resume run provenance")
        restore = names.index("Restore compatible per-group checkpoints")
        measure = names.index("Measure the declared survey shard")
        self.assertLess(validate, restore)
        self.assertLess(restore, measure)
        self.assertTrue(
            "scripts.run_crib_v4_survey import validate_resume_run"
            in steps[validate]["run"]
        )
        self.assertTrue('[[ "$RESUME_RUN_ID" =~ ^[0-9]+$ ]]' in steps[validate]["run"])
        self.assertTrue('--shard "${{ matrix.shard }}"' in steps[measure]["run"])
        self.assertTrue(
            "exec python -u -m scripts.run_crib_v4_survey" in steps[measure]["run"]
        )
        upload = steps[-1]
        self.assertEqual(upload["if"], "always()")
        self.assertEqual(upload["with"]["retention-days"], "30")
        self.assertEqual(
            upload["with"]["name"], "crib-v4-survey-shard-${{ matrix.shard }}"
        )
        self.assertEqual(steps[restore]["with"]["name"], upload["with"]["name"])
        self.assertTrue(upload["uses"].startswith("actions/upload-artifact@"))
        self.assertFalse(any("release" in s.get("uses", "") for s in steps))
        self.assertFalse(
            any("${{ inputs.resume_run_id }}" in s.get("run", "") for s in steps)
        )


if __name__ == "__main__":
    unittest.main()
