# Helpers of a Dremio cluster whose nodes are containers on several hosts. Sourced after common.sh (cx, container_ip).

# host_address NAME: IPv4 address of the host NAME from /etc/hosts.
host_address() {
    local ip
    ip=$(getent ahostsv4 "$1" | awk '{print $1; exit}')
    [[ -n $ip ]] || die "host $1 is not in /etc/hosts"
    echo "$ip"
}

# own_address PEER_NAME: the address of this host on the network that leads to the host PEER_NAME.
own_address() {
    ip -4 route get "$(host_address "$1")" | grep -oP 'src \K\S+'
}

# forward_ports HOST_IP CONTAINER_IP PORT...: DNAT from the host address to the container. Rules of the same host
# address and port that lead elsewhere (a recreated container has a new address) are removed first.
forward_ports() {
    local host_ip=$1 container_ip=$2 p stale
    shift 2
    sudo sysctl -w net.ipv4.ip_forward=1
    for p in "$@"; do
        while read -r stale; do
            [[ -z $stale ]] || sudo iptables -t nat ${stale/#-A/-D}
        done < <(sudo iptables -t nat -S PREROUTING | grep -E -- "-d $host_ip/32 .*--dport $p .*-j DNAT" | grep -v -- "--to-destination $container_ip:$p\$")
        local rule=(PREROUTING -d "$host_ip" -p tcp --dport "$p" -j DNAT --to-destination "$container_ip:$p")
        sudo iptables -t nat -C "${rule[@]}" 2>/dev/null || sudo iptables -t nat -A "${rule[@]}"
    done
}

# The container reaches the published address of its host through loopback (a DNAT back into the same container
# does not work). The address is lost when the container restarts.
# usage: add_loopback_alias HOST_IP   (uses cx)
add_loopback_alias() {
    cx bash -euc "ip addr show dev lo | grep -q 'inet $1/32' || ip addr add $1/32 dev lo"
}

# Makes the container a node of the cluster: its ports are forwarded from the host address, the container knows that
# address, and the given `key: value` lines replace the lines of the same keys in dremio.conf; then Dremio restarts.
# usage: configure_cluster_node HOST_IP "PORT PORT..." CONF_LINE...   (uses cx)
configure_cluster_node() {
    local host_ip=$1 ports=$2
    shift 2
    forward_ports "$host_ip" "$(container_ip)" $ports
    add_loopback_alias "$host_ip"
    printf '%s\n' "$@" | cx bash -euc '
        conf=/opt/dremio/conf/dremio.conf
        [[ -f $conf.bak ]] || cp "$conf" "$conf.bak"
        while IFS= read -r line; do
            key=${line%%:*}
            sed -i "/^${key//./\\.}:/d" "$conf"
            echo "$line" >> "$conf"
        done
        systemctl restart dremio'
}

# The data sets of the fabric OOM stand are mounted into every node at their host path (a NAS source needs one path on
# all nodes) as this device; the device also marks the containers of the stand.
STAND_DATA_DEVICE=fabric-oom-repro

# mount_stand_data DIR: mounts DIR into the container NAME at the same path, once.
mount_stand_data() {
    mkdir -p "$1"
    $CT config device get "$NAME" "$STAND_DATA_DEVICE" source >/dev/null 2>&1 \
        || $CT config device add "$NAME" "$STAND_DATA_DEVICE" disk source="$1" path="$1" shift=true
}

# stand_node [HOST]: the running container of the stand on HOST (this host when omitted): the one with the data device.
stand_node() {
    local script found
    # the script ends with true: the status of the last `device get` must not fail the caller's set -e
    printf -v script 'for n in $(%s list status=running -c n --format csv); do %s config device get "$n" %s source >/dev/null 2>&1 && echo "$n"; done; true' \
        "$CT" "$CT" "$STAND_DATA_DEVICE"
    if [[ -n ${1:-} ]]; then found=$(ssh -n "$1" "$script"); else found=$(bash -c "$script"); fi
    [[ -n $found && $found != *$'\n'* ]] \
        || die "expected one running container with the $STAND_DATA_DEVICE device on ${1:-this host}, found: ${found:-none} (setup_fabric_oom_stand.sh brings the stand up)"
    echo "$found"
}
