"""Ensure the demo launcher never stops listeners it cannot prove it owns."""
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from scripts import run_local


class LauncherOwnershipTests(unittest.TestCase):
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
        with patch.object(run_local, "listeners", side_effect=[{101}, {102}]), \
             patch.object(run_local, "active", side_effect=lambda pid: pid not in stopped), \
             patch.object(run_local, "owns", return_value=True), \
             patch.object(run_local.os, "kill", side_effect=lambda pid, sig: stopped.add(pid)) as kill:
            run_local.stop_existing(state, 4038)
            self.assertEqual(stopped, {101, 102})
            self.assertTrue(all(call.args[1] == run_local.signal.SIGTERM for call in kill.call_args_list))

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
