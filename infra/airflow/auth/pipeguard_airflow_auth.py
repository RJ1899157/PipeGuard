"""Local Airflow 3.3.2 authorization: recovery never receives a global writer role."""
from importlib.metadata import version
import json
import os
import stat

from airflow.api_fastapi.auth.managers.models.resource_details import DagAccessEntity
from airflow.api_fastapi.auth.managers.simple.simple_auth_manager import SimpleAuthManager
from airflow.configuration import conf


RECOVERY_USER = "pipeguard_recovery"
RECOVERY_DAG = "pipeguard_orders"


class PipeGuardAuthManager(SimpleAuthManager):
    """Keep existing local users; deny recovery access except the fixed DAG/run scope.

    The separate process-level switch is NOT a human approval. Until a dispatcher
    validates executable proposals, provisioning keeps this switch disabled.
    """

    def init(self):
        # Authorization hooks/routes are version-specific; review any upgrade first.
        if version("apache-airflow-core") != "3.3.2":
            raise RuntimeError("PipeGuard Airflow authorization requires version review")
        if conf.getboolean("core", "simple_auth_manager_all_admins"):
            raise RuntimeError("PipeGuard forbids the all-admin authentication bypass")
        if conf.get("api", "host") != "127.0.0.1":
            raise RuntimeError("PipeGuard requires a loopback-only Airflow API")
        configured = self.get_users()
        users = [user for user in configured if user.username == RECOVERY_USER]
        if len(users) != 1 or users[0].role != "viewer" or users[0].teams:
            raise RuntimeError("PipeGuard recovery requires its dedicated viewer identity")
        self._verify_password_file(configured)
        super().init()

    def _verify_password_file(self, configured):
        # The parent would otherwise generate and log a missing user's password.
        try:
            descriptor = os.open(self.get_generated_password_file(), os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(descriptor, "rb") as stream:
                info = os.fstat(stream.fileno())
                if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                        or info.st_mode & 0o077 or info.st_size > 65536):
                    raise ValueError
                raw = stream.read(65537)
            if len(raw) > 65536:
                raise ValueError
            passwords = json.loads(raw)
            if not isinstance(passwords, dict) or any(
                not isinstance(passwords.get(user.username), str)
                or not passwords[user.username] or len(passwords[user.username]) > 2048
                for user in configured
            ):
                raise ValueError
        except (OSError, ValueError):
            raise RuntimeError("Private Airflow accounts must be safely preseeded before startup") from None

    @staticmethod
    def _is_authorized(*, user, **kwargs):
        # The parent uses this hook for configuration, secrets, assets and views.
        if user.username == RECOVERY_USER:
            return False
        return SimpleAuthManager._is_authorized(user=user, **kwargs)

    def is_authorized_dag(self, *, method, user, access_entity=None, details=None):
        if user.username != RECOVERY_USER:
            return super().is_authorized_dag(
                method=method, user=user, access_entity=access_entity, details=details)
        if (user.role != "viewer" or user.teams or details is None
                or details.id != RECOVERY_DAG):
            return False
        if method == "GET":
            return access_entity in (None, DagAccessEntity.RUN)
        return (method == "POST" and access_entity == DagAccessEntity.RUN
                and os.environ.get("PIPEGUARD_AIRFLOW_RECOVERY_ENABLED") == "1")

    def is_authorized_team(self, *, method, user, details=None):
        if user.username == RECOVERY_USER:
            return False
        return super().is_authorized_team(method=method, user=user, details=details)

    def is_authorized_hitl_task(self, *, assigned_users, user):
        if user.username == RECOVERY_USER:
            return False
        return super().is_authorized_hitl_task(assigned_users=assigned_users, user=user)

    def filter_authorized_menu_items(self, menu_items, *, user):
        if user.username == RECOVERY_USER:
            return []
        return super().filter_authorized_menu_items(menu_items, user=user)
