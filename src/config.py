"""Service configuration, read once from environment variables.

Every setting has a harmless default so that modules can be imported (and unit
tests can run) without any GCP environment. Code that talks to a real backend
calls :meth:`Settings.require` first, which fails loudly when a value is
missing.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_SERVICE_URL = "https://elbow-rehab-service-1086744305186.europe-central2.run.app"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", case_sensitive=False)

    # GCP project
    project_id: str = ""
    location: str = "europe-central2"

    # BigQuery
    output_dataset: str = ""
    imu_readings_table: str = ""  # v1 paired rows (read-only legacy)
    calculated_angles_table: str = ""  # v1 angles
    raw_packets_table: str = "raw_imu_packets"
    angles_v2_table: str = "angles_v2"

    # Cloud SQL
    db_user: str = ""
    db_pass: SecretStr = SecretStr("")
    db_name: str = ""
    instance_name: str = ""
    private_ip: bool = False

    # Firebase Admin: path to a key file for local development only.
    # On Cloud Run leave empty and Application Default Credentials are used.
    firebase_cred: str = ""

    # Public URL of this service (invite links, Cloud Tasks target).
    service_url: str = DEFAULT_SERVICE_URL

    # Cloud Tasks processing trigger
    tasks_queue: str = "session-processing"
    tasks_location: str = ""  # defaults to `location`
    tasks_service_account: str = ""  # SA that signs the OIDC token
    tasks_audience: str = ""  # defaults to `service_url`
    tasks_dispatch_deadline_s: int = 1800

    # Version tag stored with every processed result.
    algorithm_version: str = "v2.0.0"
    git_sha: str = ""

    def require(self, *names: str) -> None:
        missing = []
        for name in names:
            value = getattr(self, name)
            if isinstance(value, SecretStr):
                value = value.get_secret_value()
            if not value:
                missing.append(name.upper())
        if missing:
            raise RuntimeError(f"Missing required env var(s): {', '.join(missing)}")

    def bq_table(self, table: str) -> str:
        self.require("project_id", "output_dataset")
        return f"{self.project_id}.{self.output_dataset}.{table}"

    @property
    def effective_tasks_location(self) -> str:
        return self.tasks_location or self.location

    @property
    def effective_tasks_audience(self) -> str:
        return self.tasks_audience or self.service_url

    @property
    def full_algorithm_version(self) -> str:
        if self.git_sha:
            return f"{self.algorithm_version}+{self.git_sha}"
        return self.algorithm_version


@lru_cache
def get_settings() -> Settings:
    return Settings()
