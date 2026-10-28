"""Offline tests of scripts/lib/cluster.sh: addresses of the hosts and the DNAT rules of the container ports."""
import os
import stat
import subprocess

import pytest

import defaults

LIB = defaults.ROOT_DIR / "scripts" / "lib"

# the DNAT rules `iptables -t nat -S PREROUTING` printed on the host of a recreated container: the rules of port 2181
# lead to the address of the removed container, the rule of port 45678 is current
STALE = "-A PREROUTING -d 192.168.1.75/32 -p tcp -m tcp --dport 2181 -j DNAT --to-destination 10.97.177.150:2181"
CURRENT = "-A PREROUTING -d 192.168.1.75/32 -p tcp -m tcp --dport 45678 -j DNAT --to-destination 10.97.177.91:45678"
OTHER_HOST = "-A PREROUTING -d 192.168.1.66/32 -p tcp -m tcp --dport 2181 -j DNAT --to-destination 10.0.0.9:2181"


def fake_command(directory, name, body):
    path = directory / name
    path.write_text(f"#!/bin/bash\n{body}\n")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def cluster_sh(script, env=None):
    """Runs the script after sourcing common.sh and cluster.sh."""
    return subprocess.run(["bash", "-euc", f'source {LIB}/common.sh; source {LIB}/cluster.sh; {script}'],
                          capture_output=True, text=True, env={**os.environ, **(env or {})})


def test_an_address_comes_from_etc_hosts():
    out = cluster_sh("host_address localhost")
    assert out.stdout.strip() == "127.0.0.1"


def test_an_unknown_host_is_an_error():
    out = cluster_sh("host_address no-such-host.invalid")
    assert out.returncode != 0
    assert "host no-such-host.invalid is not in /etc/hosts" in out.stderr


def test_the_own_address_is_the_source_of_the_route_to_the_peer():
    assert cluster_sh("own_address localhost").stdout.strip() == "127.0.0.1"


@pytest.fixture
def iptables(tmp_path):
    """Fake sudo, sysctl and iptables: iptables lists the given rules and logs every call."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    rules, log = tmp_path / "rules", tmp_path / "log"
    rules.write_text("\n".join([STALE, CURRENT, OTHER_HOST]) + "\n")
    fake_command(bin_dir, "sudo", 'exec "$@"')
    fake_command(bin_dir, "sysctl", "true")
    fake_command(bin_dir, "iptables", f'echo "$@" >> {log}\n'
                 f'case "$*" in "-t nat -S PREROUTING") cat {rules};; "-t nat -C "*) exit 1;; esac')
    env = {"PATH": f"{bin_dir}:{os.environ['PATH']}"}
    return env, lambda: log.read_text().splitlines()


def test_a_rule_to_the_address_of_a_removed_container_is_replaced(iptables):
    env, calls = iptables
    out = cluster_sh("forward_ports 192.168.1.75 10.97.177.91 2181 45678", env)
    assert out.returncode == 0, out.stderr
    assert f"-t nat -D {STALE[3:]}" in calls()
    assert "-t nat -A PREROUTING -d 192.168.1.75 -p tcp --dport 2181 -j DNAT --to-destination 10.97.177.91:2181" in calls()


def test_current_rules_and_the_rules_of_other_hosts_are_not_touched(iptables):
    env, calls = iptables
    cluster_sh("forward_ports 192.168.1.75 10.97.177.91 2181 45678", env)
    deleted = [c for c in calls() if c.startswith("-t nat -D")]
    assert deleted == [f"-t nat -D {STALE[3:]}"]


@pytest.fixture
def stand_hosts(tmp_path):
    """Fake incus and ssh: incus lists the running containers of CONTAINERS (name:device,...), says the devices mount MOUNTED and logs device changes;
    ssh runs the command locally."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "log"
    fake_command(bin_dir, "incus", f'''
        case "$1 $2" in
            "list status=running") tr , "\\n" <<<"$CONTAINERS" | cut -d: -f1 | sort -u ;;
            "config device")
                case "$3" in
                    get) grep -qx "$4:$5" < <(tr , "\\n" <<<"$CONTAINERS") && echo "$MOUNTED" ;;
                    remove) echo "remove $4 $5" >> {log} ;;
                    add) echo "add $4 $5 $6 $7 $8 $9" >> {log} ;;
                esac ;;
        esac''')
    fake_command(bin_dir, "ssh", 'shift 2; exec bash -c "$1"')
    return {"PATH": f"{bin_dir}:{os.environ['PATH']}"}, lambda: log.read_text().splitlines() if log.exists() else []


def test_the_node_of_the_stand_is_the_running_container_with_the_data_device(stand_hosts):
    env, _ = stand_hosts
    env["CONTAINERS"] = "v0910:storage,d27-0-0-j21-14G-4cpu:fabric-oom-repro,d27-0-0-j21-14G-4cpu:storage"
    assert cluster_sh("CT=incus; stand_node", env).stdout.strip() == "d27-0-0-j21-14G-4cpu"
    assert cluster_sh("CT=incus; stand_node den", env).stdout.strip() == "d27-0-0-j21-14G-4cpu"


@pytest.mark.parametrize("containers, found", [("v0910:storage", "none"), ("a:fabric-oom-repro,b:fabric-oom-repro", "a\nb")])
def test_no_node_or_two_nodes_is_an_error(stand_hosts, containers, found):
    env, _ = stand_hosts
    env["CONTAINERS"] = containers
    out = cluster_sh("CT=incus; stand_node", env)
    assert out.returncode != 0
    assert f"expected one running container with the fabric-oom-repro device on this host, found: {found}" in out.stderr


def test_a_stand_directory_is_mounted_once(stand_hosts, tmp_path):
    env, calls = stand_hosts
    env["CONTAINERS"] = "d27-0-0-j21-14G-4cpu:storage"
    data = tmp_path / "fabric-oom-repro"
    out = cluster_sh(f"CT=incus; NAME=d27-0-0-j21-14G-4cpu; mount_stand_dir fabric-oom-repro {data}", env)
    assert out.returncode == 0, out.stderr
    assert data.is_dir()
    assert [c for c in calls() if c.startswith("add")] == [
        f"add d27-0-0-j21-14G-4cpu fabric-oom-repro disk source={data} path={data} shift=true"]
    before = len(calls())
    env["CONTAINERS"] = "d27-0-0-j21-14G-4cpu:storage,d27-0-0-j21-14G-4cpu:fabric-oom-repro"
    env["MOUNTED"] = str(data)
    cluster_sh(f"CT=incus; NAME=d27-0-0-j21-14G-4cpu; mount_stand_dir fabric-oom-repro {data}", env)
    assert len(calls()) == before


def test_a_device_mounting_another_directory_is_replaced(stand_hosts, tmp_path):
    """A second stand uses a new dist directory: the device of the first stand would leave it unmounted."""
    env, calls = stand_hosts
    env["CONTAINERS"] = "d27-0-0-j21-14G-4cpu:fabric-oom-dist"
    env["MOUNTED"] = "/mnt/ubuntu-var/nfs/shared/fabric-oom-dist/first"
    new = tmp_path / "second"
    out = cluster_sh(f"CT=incus; NAME=d27-0-0-j21-14G-4cpu; mount_stand_dir fabric-oom-dist {new}", env)
    assert out.returncode == 0, out.stderr
    assert calls() == ["remove d27-0-0-j21-14G-4cpu fabric-oom-dist",
                       f"add d27-0-0-j21-14G-4cpu fabric-oom-dist disk source={new} path={new} shift=true"]
