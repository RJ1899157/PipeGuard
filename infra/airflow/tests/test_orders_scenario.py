"""Load the actual DAG with its pinned interpreter; no scheduler or database writes."""
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from airflow.exceptions import ParamValidationError

PATH=Path(__file__).resolve().parents[1]/"dags/orders.py"


def load(mode):
    with patch.dict(os.environ,{} if mode is None else {"PIPEGUARD_AIRFLOW_MANUAL_ONLY":mode}):
        if mode is None:
            os.environ.pop("PIPEGUARD_AIRFLOW_MANUAL_ONLY",None)
        spec=importlib.util.spec_from_file_location("orders_scenario_check",PATH)
        module=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.dag


class OrdersScenario(unittest.TestCase):
    def test_default_and_explicit_daily_schedule(self):
        for mode in (None,"0"):
            dag=load(mode)
            self.assertEqual(dag.schedule,"@daily")
            self.assertFalse(dag.catchup)
            self.assertEqual(dag.max_active_runs,1)
            self.assertTrue(dag.is_paused_upon_creation)

    def test_manual_mode_and_false_fault_defaults(self):
        dag=load("1")
        self.assertIsNone(dag.schedule)
        self.assertFalse(dag.params["simulate_terminal_failure"])
        self.assertFalse(dag.params["simulate_first_attempt_failure"])
        task=dag.get_task("build_orders")
        self.assertEqual(task.retries,1)
        self.assertEqual(task.owner,"RJ1899157")
        for name in ("simulate_terminal_failure","simulate_first_attempt_failure"):
            with self.assertRaises(ParamValidationError):
                dag.params.get_param(name).resolve("true")

    def test_fault_flags_are_forwarded_without_running_a_workload(self):
        task=load("0").get_task("build_orders")
        function=task.python_callable
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            config=root/"sample-pipelines/orders/.env"
            config.parent.mkdir(parents=True)
            config.write_text("PIPEGUARD_INTEGRATION_ID=test\nPIPEGUARD_JOB_ID=test\nPIPEGUARD_PRODUCER_TOKEN=test\n")
            for first,terminal in ((False,False),(True,False),(False,True),(True,True)):
                context={"dag":Mock(dag_id="pipeguard_orders"),"run_id":"synthetic",
                         "task":Mock(task_id="build_orders"),"ti":Mock(try_number=2),
                         "params":{"simulate_first_attempt_failure":first,"simulate_terminal_failure":terminal}}
                process=Mock(pid=99999999,returncode=0)
                process.communicate.return_value=('{"external_run_id":"synthetic","attempt_number":2,"dbt_succeeded":true,"monitoring":"acknowledged"}',"")
                with patch.dict(function.__globals__,{"ROOT":root,"get_current_context":lambda:context}), \
                     patch("subprocess.Popen",return_value=process) as start,patch("os.killpg"):
                    function()
                command=start.call_args.args[0]
                self.assertEqual("--simulate-first-attempt-failure" in command,first)
                self.assertEqual("--simulate-terminal-failure" in command,terminal)
                self.assertEqual(command[command.index("--attempt")+1],"2")

    def test_invalid_schedule_mode_refuses_import(self):
        for mode in ("true","","2","1\n"):
            with self.assertRaisesRegex(ValueError,"must be 0 or 1"):
                load(mode)


if __name__=="__main__":
    unittest.main()
