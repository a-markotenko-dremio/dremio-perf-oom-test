"""Thin client of the Dremio REST API: login, SQL jobs and the catalog calls the tests need."""
import os
import time
import urllib.parse

import requests


class JobFailed(AssertionError):
    """A SQL job ended FAILED or CANCELED (its errorMessage is in the text)."""


class JobTimeout(AssertionError):
    """A SQL job did not finish in time and was cancelled."""


class DremioClient:
    def __init__(self, url, timeout):
        self.url = url
        self.timeout = timeout  # seconds allowed for one job
        self.headers = {}

    # ---- connection
    def is_up(self):
        requests.get(f"{self.url}/apiv2/server_status", timeout=10).raise_for_status()

    def login(self):
        """Authenticates with DREMIO_TOKEN, or with DREMIO_USER / DREMIO_PASSWORD."""
        token = os.environ.get("DREMIO_TOKEN")
        if token:
            self.headers = {"Authorization": f"Bearer {token}"}
            return
        r = requests.post(f"{self.url}/apiv2/login", timeout=30, json={
            "userName": os.environ.get("DREMIO_USER", "dremio"),
            "password": os.environ.get("DREMIO_PASSWORD", "dremio123")})
        r.raise_for_status()
        self.headers = {"Authorization": f"_dremio{r.json()['token']}"}

    def _get(self, path, timeout=30, **kwargs):
        return requests.get(f"{self.url}{path}", headers=self.headers, timeout=timeout, **kwargs)

    # ---- SQL
    def run_sql(self, sql):
        """Runs one statement and returns the finished job (with its id)."""
        r = requests.post(f"{self.url}/api/v3/sql", headers=self.headers, json={"sql": sql}, timeout=60)
        r.raise_for_status()
        job_id = r.json()["id"]

        deadline = time.time() + self.timeout
        while True:
            job = self._get(f"/api/v3/job/{job_id}").json()
            state = job["jobState"]
            if state in ("COMPLETED", "FAILED", "CANCELED"):
                break
            if time.time() > deadline:
                requests.post(f"{self.url}/api/v3/job/{job_id}/cancel", headers=self.headers, timeout=30)
                raise JobTimeout(f"Job {job_id} did not finish within {self.timeout}s (state={state})")
            time.sleep(1)

        if state != "COMPLETED":
            raise JobFailed(f"Job {job_id} {state}: {job.get('errorMessage')}\nSQL: {sql[:200]}")
        job["id"] = job_id
        return job

    def query_rows(self, sql):
        job = self.run_sql(sql)
        res = self._get(f"/api/v3/job/{job['id']}/results", timeout=60)
        res.raise_for_status()
        return res.json()["rows"]

    def count_rows(self, table):
        return int(self.query_rows(f"SELECT COUNT(*) AS cnt FROM {table}")[0]["cnt"])

    # ---- catalog
    def ensure_nas_source(self, name, path):
        """
        Creates the NAS source, or repoints it to `path` if it already exists; True when the source is new or was
        pointing elsewhere (the metadata of its tables then describes other files), False when it already had `path`.
        """
        path.mkdir(parents=True, exist_ok=True)
        config = {"path": str(path)}
        # Look the source up by listing the catalog: by-path fails for an unavailable source.
        root = self._get("/api/v3/catalog")
        root.raise_for_status()
        found = next((d for d in root.json()["data"] if d.get("path") == [name]), None)
        if found:
            source = self._get(f"/api/v3/catalog/{found['id']}")
            source.raise_for_status()
            if source.json()["config"]["path"] == config["path"]:
                return False
            body = {"entityType": "source", "id": found["id"], "tag": found["tag"],
                    "name": name, "type": "NAS", "config": config}
            r = requests.put(f"{self.url}/api/v3/catalog/{found['id']}",
                             headers=self.headers, json=body, timeout=60)
        else:
            r = requests.post(f"{self.url}/api/v3/catalog", headers=self.headers, timeout=60,
                              json={"entityType": "source", "name": name, "type": "NAS", "config": config})
        assert r.ok, f"Cannot configure source {name} -> {path}: {r.status_code} {r.text}"
        return True

    def entity_type(self, path):
        """The catalog entityType at the path ("folder", "dataset", ...), or None when there is nothing."""
        r = self._get(f"/api/v3/catalog/by-path/{'/'.join(path)}")
        return r.json()["entityType"] if r.ok else None

    def unpromote_table(self, table_path):
        """Removes a table's Dremio metadata so its folder can be rebuilt."""
        existing = self._get(f"/api/v3/catalog/by-path/{'/'.join(table_path)}")
        # Drop any stale dataset (e.g. an old Iceberg table) so Dremio re-reads the folder.
        if existing.ok and existing.json().get("entityType") == "dataset":
            d = existing.json()
            # params= URL-encodes the tag: it may contain '+', which a raw query string turns into a space.
            requests.delete(f"{self.url}/api/v3/catalog/{d['id']}", params={"tag": d["tag"]},
                            headers=self.headers, timeout=60).raise_for_status()

    def promote_folder(self, table_path):
        """Registers a folder of Parquet files as a table."""
        folder = self._get(f"/api/v3/catalog/by-path/{'/'.join(table_path)}")
        folder.raise_for_status()
        folder_id = folder.json()["id"]
        r = requests.post(f"{self.url}/api/v3/catalog/{urllib.parse.quote(folder_id, safe='')}",
                          headers=self.headers, timeout=120,
                          json={"entityType": "dataset", "id": folder_id, "path": table_path,
                                "type": "PHYSICAL_DATASET", "format": {"type": "Parquet"}})
        assert r.ok, f"Cannot promote input table: {r.status_code} {r.text}"
