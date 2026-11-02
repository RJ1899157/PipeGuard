"""Run with Airflow's own interpreter; no database, credentials or live actions."""
import ast
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import airflow
from airflow.api_fastapi.auth.managers.models.resource_details import (
    AccessView, DagAccessEntity, DagDetails, TeamDetails,
)
from airflow.api_fastapi.auth.managers.simple.simple_auth_manager import SimpleAuthManager
from airflow.api_fastapi.auth.managers.simple.user import SimpleAuthManagerUser

from pipeguard_airflow_auth import PipeGuardAuthManager, RECOVERY_DAG, RECOVERY_USER


class RecoveryAuthorization(unittest.TestCase):
    def setUp(self):
        self.manager = PipeGuardAuthManager()
        self.recovery = SimpleAuthManagerUser(username=RECOVERY_USER, role="viewer")
        self.observer = SimpleAuthManagerUser(username="pipeguard_observer", role="viewer")
        self.admin = SimpleAuthManagerUser(username="RJ1899157", role="admin")

    def test_dag_permissions_exhaustive_matrix(self):
        for enabled in (None, "0", "true", "1"):
            environment = {} if enabled is None else {"PIPEGUARD_AIRFLOW_RECOVERY_ENABLED": enabled}
            with patch.dict("os.environ", environment, clear=True):
                for dag in (None, "~", "", "another_dag", RECOVERY_DAG):
                    for method in ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"):
                        for entity in (None, *DagAccessEntity):
                            with self.subTest(enabled=enabled, dag=dag, method=method, entity=entity):
                                allowed = (dag == RECOVERY_DAG and (
                                    method == "GET" and entity in (None, DagAccessEntity.RUN)
                                    or enabled == "1" and method == "POST" and entity == DagAccessEntity.RUN))
                                self.assertEqual(self.manager.is_authorized_dag(
                                    method=method, user=self.recovery, details=DagDetails(id=dag),
                                    access_entity=entity), allowed)

    def test_missing_details_wrong_role_and_teams_fail_closed(self):
        with patch.dict("os.environ", {"PIPEGUARD_AIRFLOW_RECOVERY_ENABLED": "1"}):
            self.assertFalse(self.manager.is_authorized_dag(method="GET", user=self.recovery))
            for role, teams in (("admin", []), ("user", []), (None, []), ("viewer", ["a"])):
                user = SimpleAuthManagerUser(username=RECOVERY_USER, role=role, teams=teams)
                for method in ("GET", "POST"):
                    self.assertFalse(self.manager.is_authorized_dag(
                        method=method, user=user, details=DagDetails(id=RECOVERY_DAG),
                        access_entity=DagAccessEntity.RUN))

    def test_global_resources_never_authorized_even_with_admin_role(self):
        for role in ("viewer", "user", "admin"):
            user = SimpleAuthManagerUser(username=RECOVERY_USER, role=role, teams=["test"])
            for resource in ("configuration", "connection", "asset", "asset_alias", "pool", "variable", "team"):
                for method in ("GET", "POST", "PUT", "DELETE"):
                    with self.subTest(role=role, resource=resource, method=method):
                        self.assertFalse(getattr(self.manager, "is_authorized_" + resource)(
                            method=method, user=user))
            self.assertFalse(self.manager.is_authorized_team(
                method="GET", user=user, details=TeamDetails(name="test")))
            self.assertFalse(self.manager.is_authorized_hitl_task(assigned_users={RECOVERY_USER}, user=user))
            self.assertFalse(self.manager.is_authorized_custom_view(method="GET", resource_name="test", user=user))
            self.assertEqual(self.manager.filter_authorized_menu_items(["test"], user=user), [])
            for view in AccessView:
                self.assertFalse(self.manager.is_authorized_view(access_view=view, user=user))

    def test_existing_administrator_and_observer_permissions_preserved(self):
        parent = SimpleAuthManager()
        for user in (self.admin, self.observer):
            for method in ("GET", "POST", "PUT", "DELETE"):
                for entity in (None, *DagAccessEntity):
                    kwargs = dict(method=method, user=user, details=DagDetails(id="other"), access_entity=entity)
                    self.assertEqual(self.manager.is_authorized_dag(**kwargs), parent.is_authorized_dag(**kwargs))
                for resource in ("configuration", "connection", "asset", "asset_alias", "pool", "variable"):
                    kwargs = dict(method=method, user=user)
                    self.assertEqual(getattr(self.manager, "is_authorized_" + resource)(**kwargs),
                                     getattr(parent, "is_authorized_" + resource)(**kwargs))

    def test_list_and_batch_cannot_widen_dag_scope(self):
        self.assertEqual(self.manager.filter_authorized_dag_ids(
            dag_ids={RECOVERY_DAG, "other"}, user=self.recovery), {RECOVERY_DAG})
        self.assertEqual(self.manager.filter_authorized_dag_ids(
            dag_ids={RECOVERY_DAG}, user=self.recovery, method="PUT"), set())
        self.assertFalse(self.manager.batch_is_authorized_dag([
            {"method": "GET", "details": DagDetails(id=RECOVERY_DAG)},
            {"method": "GET", "details": DagDetails(id="other")},
        ], user=self.recovery))

    def test_startup_guards_and_valid_parent_initialization(self):
        with (patch("pipeguard_airflow_auth.version", return_value="3.3.2") as installed,
              patch("pipeguard_airflow_auth.conf.getboolean", return_value=False) as bypass,
              patch("pipeguard_airflow_auth.conf.get", return_value="127.0.0.1") as host,
              patch.object(PipeGuardAuthManager, "get_users", return_value=[self.recovery]) as users,
              patch.object(PipeGuardAuthManager, "_verify_password_file") as passwords,
              patch.object(SimpleAuthManager, "init") as parent):
            self.manager.init()
            passwords.assert_called_once_with([self.recovery])
            parent.assert_called_once()
            for fault in ("version", "bypass", "host", "missing", "duplicate", "role", "teams"):
                with self.subTest(fault=fault):
                    installed.return_value = "next" if fault == "version" else "3.3.2"
                    bypass.return_value = fault == "bypass"
                    host.return_value = "0.0.0.0" if fault == "host" else "127.0.0.1"
                    users.return_value = {
                        "missing": [], "duplicate": [self.recovery, self.recovery],
                        "role": [SimpleAuthManagerUser(username=RECOVERY_USER, role="user")],
                        "teams": [SimpleAuthManagerUser(username=RECOVERY_USER, role="viewer", teams=["a"])],
                    }.get(fault, [self.recovery])
                    with self.assertRaises(RuntimeError):
                        self.manager.init()
            parent.assert_called_once()

    def test_startup_password_guard_rejects_missing_unsafe_and_malformed_files(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "users.json"
            with patch.object(PipeGuardAuthManager, "get_generated_password_file", return_value=str(path)):
                with self.assertRaises(RuntimeError):
                    self.manager._verify_password_file([self.recovery])
                for payload in ([], {}, {RECOVERY_USER: ""}, {RECOVERY_USER: 123}, {RECOVERY_USER: "x" * 2049}):
                    path.write_text(json.dumps(payload))
                    path.chmod(0o600)
                    with self.assertRaises(RuntimeError):
                        self.manager._verify_password_file([self.recovery])
                path.write_text(json.dumps({RECOVERY_USER: "synthetic"}))
                self.manager._verify_password_file([self.recovery])
                path.chmod(0o644)
                with self.assertRaises(RuntimeError):
                    self.manager._verify_password_file([self.recovery])
                path.chmod(0o600)
                path.write_text("x" * 65537)
                with self.assertRaises(RuntimeError):
                    self.manager._verify_password_file([self.recovery])
                target = Path(directory) / "target.json"
                path.rename(target)
                path.symlink_to(target)
                with self.assertRaises(RuntimeError):
                    self.manager._verify_password_file([self.recovery])

    def test_pinned_public_post_run_route_dependency_is_only_trigger(self):
        # Inspect explicit route dependencies. The inline asset-materialization
        # permission check has a separate regression below.
        routes = Path(airflow.__file__).parent / "api_fastapi/core_api/routes/public"
        matches = []
        for path in sorted(routes.rglob("*.py")):
            for node in ast.walk(ast.parse(path.read_text())):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                for decorator in node.decorator_list:
                    for call in ast.walk(decorator):
                        if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Name):
                            continue
                        if call.func.id != "requires_access_dag":
                            continue
                        keywords = {k.arg: ast.unparse(k.value) for k in call.keywords}
                        if (keywords.get("method") == "'POST'"
                                and keywords.get("access_entity") == "DagAccessEntity.RUN"):
                            matches.append((path.name, node.name))
        self.assertEqual(matches, [("dag_run.py", "trigger_dag_run")])

    def test_asset_materialization_also_requires_the_denied_asset_permission(self):
        path = Path(airflow.__file__).parent / "api_fastapi/core_api/routes/public/assets.py"
        function = next(node for node in ast.parse(path.read_text()).body
                        if isinstance(node, ast.FunctionDef) and node.name == "materialize_asset")
        self.assertTrue(any(
            isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
            and call.func.id == "requires_access_asset"
            and any(k.arg == "method" and ast.literal_eval(k.value) == "POST" for k in call.keywords)
            for decorator in function.decorator_list for call in ast.walk(decorator)))
        self.assertFalse(self.manager.is_authorized_asset(method="POST", user=self.recovery))


if __name__ == "__main__":
    unittest.main()
