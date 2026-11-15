"""Ensure the demo launcher never stops listeners it cannot prove it owns."""
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from scripts import run_local


class LauncherOwnershipTests(unittest.TestCase):
    def setUp(self):
        runtime = TemporaryDirectory(dir=run_local.ROOT)
        self.addCleanup(runtime.cleanup)
        runtime_patch = patch.object(run_local, "RUNTIME", Path(runtime.name))
        runtime_patch.start()
        self.addCleanup(runtime_patch.stop)

    def test_interrupted_start_stops_and_records_the_started_child(self):
        with TemporaryDirectory(dir=run_local.ROOT) as directory:
            process = MagicMock(pid=101)
            process.poll.return_value = None
            entry = {"pid": 101, "fd": 8, "marker": str(Path(directory) / "5039.sample.fixture"), "port": 5039}
            recorded = []
            def interrupt_after_record(*args):
                recorded.append(run_local.json.loads((Path(directory) / "5038.state.json").read_text())["sample"])
                raise KeyboardInterrupt
            with patch.object(run_local, "RUNTIME", Path(directory)), \
                 patch.object(run_local.sys, "argv", ["run_local.py", "5038"]), \
                 patch.object(run_local, "stop_existing"), \
                 patch.object(run_local, "start_service", return_value=(process, entry)), \
                 patch.object(run_local, "wait_ready", side_effect=interrupt_after_record):
                with self.assertRaises(KeyboardInterrupt):
                    run_local.main()
            process.terminate.assert_called_once()
            state = run_local.json.loads((Path(directory) / "5038.state.json").read_text())
            self.assertEqual(recorded, [entry])
            self.assertNotIn("sample", state)

    def test_unresponsive_child_stays_recorded_after_failed_readiness(self):
        with TemporaryDirectory(dir=run_local.ROOT) as directory:
            process = MagicMock(pid=101)
            process.poll.return_value = None
            process.wait.side_effect = subprocess.TimeoutExpired("synthetic-child", 5)
            entry = {"pid": 101, "fd": 8, "marker": str(Path(directory) / "5039.sample.fixture"), "port": 5039}
            with patch.object(run_local, "RUNTIME", Path(directory)), \
                 patch.object(run_local.sys, "argv", ["run_local.py", "5038"]), \
                 patch.object(run_local, "stop_existing"), \
                 patch.object(run_local, "start_service", return_value=(process, entry)), \
                 patch.object(run_local, "wait_ready", side_effect=RuntimeError("not ready")):
                with self.assertRaisesRegex(RuntimeError, "did not stop"):
                    run_local.main()
            process.terminate.assert_called_once()
            state = run_local.json.loads((Path(directory) / "5038.state.json").read_text())
            self.assertEqual(state["sample"], entry)

    def test_failed_state_write_does_not_claim_stuck_child_was_recorded(self):
        with TemporaryDirectory(dir=run_local.ROOT) as directory:
            process = MagicMock(pid=101)
            process.poll.return_value = None
            process.wait.side_effect = subprocess.TimeoutExpired("synthetic-child", 5)
            entry = {"pid": 101, "fd": 8, "marker": str(Path(directory) / "5039.sample.fixture"), "port": 5039}
            original_save = run_local.save_state
            def fail_child_record(path, state):
                if "sample" in state:
                    raise OSError("synthetic disk failure")
                original_save(path, state)
            with patch.object(run_local, "RUNTIME", Path(directory)), \
                 patch.object(run_local.sys, "argv", ["run_local.py", "5038"]), \
                 patch.object(run_local, "stop_existing"), \
                 patch.object(run_local, "start_service", return_value=(process, entry)), \
                 patch.object(run_local, "save_state", side_effect=fail_child_record):
                with self.assertRaisesRegex(RuntimeError, "ownership state could not be saved"):
                    run_local.main()
            process.terminate.assert_called_once()
            state = run_local.json.loads((Path(directory) / "5038.state.json").read_text())
            self.assertNotIn("sample", state)

    def test_unknown_listener_is_not_stopped(self):
        with patch.object(run_local, "listeners", return_value={9001}), patch.object(run_local.os, "kill") as kill:
            with self.assertRaisesRegex(RuntimeError, "unowned"):
                run_local.stop_existing(None, 4038)
            kill.assert_not_called()

    def test_both_ports_are_checked_before_any_process_is_stopped(self):
        state = {"gateway": {"pid": 101}, "sample": {"pid": 102}}
        with patch.object(run_local, "listeners", side_effect=[{101}, {999}]), \
             patch.object(run_local, "active", return_value=True), \
             patch.object(run_local, "owns", return_value=True), \
             patch.object(run_local.os, "kill") as kill:
            with self.assertRaisesRegex(RuntimeError, "unexpected listener"):
                run_local.stop_existing(state, 4038)
            kill.assert_not_called()

    def test_two_verified_processes_receive_graceful_stop(self):
        state = {"gateway": {"pid": 101}, "sample": {"pid": 102}}
        stopped = set()
        with TemporaryDirectory(dir=run_local.ROOT) as directory:
            with patch.object(run_local, "RUNTIME", Path(directory)), \
                 patch.object(run_local, "listeners", side_effect=[{101}, {102}]), \
                 patch.object(run_local, "active", side_effect=lambda pid: pid not in stopped), \
                 patch.object(run_local, "owns", return_value=True), \
                 patch.object(run_local.os, "kill", side_effect=lambda pid, sig: stopped.add(pid)) as kill:
                run_local.stop_existing(state, 4038)
                self.assertEqual(stopped, {101, 102})
                self.assertTrue(all(call.args[1] == run_local.signal.SIGTERM for call in kill.call_args_list))

    def test_clean_stop_clears_stale_pids_without_removing_runtime_files(self):
        with TemporaryDirectory(dir=run_local.ROOT) as directory:
            root = Path(directory)
            state_path = root / "4038.state.json"
            marker, database = root / "4038.gateway.fixture", root / "4038.sqlite3"
            marker.write_text("marker")
            database.write_text("synthetic data")
            state = {"project": str(run_local.ROOT), "gateway": {"pid": 101}, "sample": {"pid": 102}}
            state_path.write_text(run_local.json.dumps(state))
            stopped = set()
            with patch.object(run_local, "RUNTIME", root), \
                 patch.object(run_local, "listeners", side_effect=[{101}, {102}]), \
                 patch.object(run_local, "active", side_effect=lambda pid: pid not in stopped), \
                 patch.object(run_local, "owns", return_value=True), \
                 patch.object(run_local.os, "kill", side_effect=lambda pid, sig: stopped.add(pid)):
                run_local.stop_existing(state, 4038)
            self.assertEqual(run_local.json.loads(state_path.read_text()), {"project": str(run_local.ROOT)})
            self.assertEqual(marker.read_text(), "marker")
            self.assertEqual(database.read_text(), "synthetic data")

    def test_partial_stop_keeps_only_the_unconfirmed_process(self):
        with TemporaryDirectory(dir=run_local.ROOT) as directory:
            root = Path(directory)
            state_path = root / "4038.state.json"
            state = {"project": str(run_local.ROOT), "gateway": {"pid": 101}, "sample": {"pid": 102}}
            state_path.write_text(run_local.json.dumps(state))
            stopped = set()
            with patch.object(run_local, "RUNTIME", root), \
                 patch.object(run_local, "listeners", side_effect=[{101}, {102}]), \
                 patch.object(run_local, "active", side_effect=lambda pid: pid not in stopped or pid == 102), \
                 patch.object(run_local, "owns", return_value=True), \
                 patch.object(run_local.os, "kill", side_effect=lambda pid, sig: stopped.add(pid)), \
                 patch.object(run_local.time, "monotonic", side_effect=[0, 0, 11]), \
                 patch.object(run_local.time, "sleep"):
                with self.assertRaisesRegex(RuntimeError, "did not stop"):
                    run_local.stop_existing(state, 4038)
            self.assertEqual(run_local.json.loads(state_path.read_text()),
                             {"project": str(run_local.ROOT), "sample": {"pid": 102}})

    def test_marker_and_working_directory_must_both_match(self):
        with TemporaryDirectory(dir=run_local.ROOT) as directory:
            marker = Path(directory).resolve() / "4038.gateway.fixture"
            marker.touch()
            entry = {"pid": 101, "fd": 8, "marker": str(marker), "port": 4038}
            def inspect(cmd, **kwargs):
                path = marker if cmd[cmd.index("-d") + 1] == "8" else run_local.ROOT / "gateway"
                return SimpleNamespace(returncode=0, stdout=f"n{path}\n")
            with patch.object(run_local, "RUNTIME", Path(directory)), patch.object(run_local.subprocess, "run", side_effect=inspect):
                self.assertTrue(run_local.owns(entry, "gateway", 4038))
                self.assertFalse(run_local.owns(entry, "sample", 4039))


if __name__ == "__main__":
    unittest.main()
