"""The HDFS directory of the runs with STORAGE=hdfs: both tables (input/ and output/) live in it, as they live in the
bucket with STORAGE=s3. The tests reach it by WebHDFS, Dremio by RPC."""
import requests

import settings


def check(r):
    r.raise_for_status()
    return r


class Store:
    """The HDFS directory as a remote store of the test run (the interface of conftest.remote_store, shared with s3store.Store)."""

    def __init__(self, host, port, web_port, root, user):
        self.host, self.port, self.root, self.user = host, port, root.rstrip("/"), user
        self.web = f"http://{host}:{web_port}/webhdfs/v1"
        self.url = f"hdfs://{host}:{port}{self.root}"

    def _request(self, method, path, op, **params):
        return requests.request(method, f"{self.web}{self.root}/{path}", params={"op": op, "user.name": self.user, **params},
                                allow_redirects=False, timeout=settings.TIMEOUT)

    def ensure_sources(self, dremio, sources):
        """Creates the Dremio sources, {name: subdirectory of the store}; the directory first."""
        for name, subdir in sources.items():
            check(self._request("PUT", subdir, "MKDIRS"))
            dremio.ensure_hdfs_source(name, self.host, self.port, f"{self.root}/{subdir}")

    def sizes(self, prefix):
        """{name: size} of the files in the folder (not recursive: the tables of generate_data are flat); {} when there is none."""
        r = self._request("GET", prefix, "LISTSTATUS")
        if r.status_code == 404:
            return {}
        return {f["pathSuffix"]: f["length"] for f in check(r).json()["FileStatuses"]["FileStatus"]}

    def delete_folder(self, prefix):
        check(self._request("DELETE", prefix, "DELETE", recursive="true"))

    def upload_folder(self, folder, prefix, log=print):
        """Makes the prefix hold exactly the files of the folder; a file already there with the same size is kept."""
        local = {f.name: f for f in sorted(folder.iterdir())}
        remote = self.sizes(prefix)
        for name in remote.keys() - local.keys():
            check(self._request("DELETE", f"{prefix}/{name}", "DELETE"))
        for name, f in local.items():
            if remote.get(name) != f.stat().st_size:
                # WebHDFS: the namenode answers with the datanode to send the data to
                location = check(self._request("PUT", f"{prefix}/{name}", "CREATE", overwrite="true")).headers["Location"]
                with f.open("rb") as data:
                    check(requests.put(location, data=data, timeout=settings.TIMEOUT))
                log(f"uploaded {self.url}/{prefix}/{name}")
