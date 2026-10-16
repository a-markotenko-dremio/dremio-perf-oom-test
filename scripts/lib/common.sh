# Sourced by the scripts: shared helpers.

log() { echo "==> $*"; }
die() { echo "ERROR: $*" >&2; exit 1; }

# Picks the container CLI: sets CT (incus, or lxc) and DEFAULT_IMAGE, the stock image of that CLI.
detect_container_cli() {
    if command -v incus >/dev/null; then CT=incus; DEFAULT_IMAGE=images:ubuntu/22.04
    elif command -v lxc >/dev/null; then CT=lxc; DEFAULT_IMAGE=ubuntu:22.04
    else die "neither incus nor lxc found in PATH"; fi
}

# The Java of a deployment as a name part: the tag of --java-image (lower case, other characters
# to hyphens), e.g. cgr.dev/chainguard/jdk:openjdk-21-dev -> openjdk-21-dev; else the Java version.
java_label() {
    if [[ -n ${JAVA_IMAGE:-} ]]; then
        local tag=${JAVA_IMAGE##*/}
        tag=${tag#*:}
        tr 'A-Z' 'a-z' <<<"$tag" | sed -E 's/[^a-z0-9]+/-/g; s/^-+|-+$//g'
    else
        echo "${JAVA_VERSION:-}"
    fi
}

# Container settings that let Docker run inside it.
docker_launch_args() {
    echo "-c security.nesting=true -c security.syscalls.intercept.mknod=true -c security.syscalls.intercept.setxattr=true"
}

# Default container name: d<dremio version>-j<java>-<memory>-<cpus>cpu, e.g. d26-1-8-j21-16G-4cpu. The version comes
# from the package file name; dots become hyphens because instance names allow only alphanumerics
# and hyphens. <memory> is the container memory limit (14G, or 1500M when not a whole number of GB);
# <cpus> is the CPU limit, or the number of CPUs of this host when the container is not limited.
# usage: default_container_name PACKAGE JAVA_VERSION CONTAINER_MB [CPUS]
default_container_name() {
    local package=$1 java=$2 mb=$3 cpus=${4:-} name=""
    if [[ $(basename "$package") =~ -([0-9]+)\.([0-9]+)\.([0-9]+) ]]; then
        name=d${BASH_REMATCH[1]}-${BASH_REMATCH[2]}-${BASH_REMATCH[3]}-
    fi
    name+=j${java}
    if (( mb % 1024 == 0 )); then name+=-$((mb / 1024))G; else name+=-${mb}M; fi
    if [[ $cpus =~ ^[0-9]+$ ]]; then name+=-${cpus}cpu; else name+=-$(nproc)cpu; fi
    echo "$name"
}
