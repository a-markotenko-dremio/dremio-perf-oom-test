# Sourced by deploy_dremio.sh. The cached base image, built once and reused, so that every deployment skips
# the apt install: Ubuntu + OpenJDK + curl, or with --java-image Ubuntu + Docker (perf-docker).

# Builds the cached perf-java<N> (or perf-docker) image when it is missing (or --rebuild-image); does nothing with --image.
ensure_image() {
    if (( USE_CACHED_IMAGE )); then
        local packages launch_args=()
        if [[ -n $JAVA_IMAGE ]]; then
            packages="docker.io curl ca-certificates"
            read -r -a launch_args <<<"$(docker_launch_args)"
        else
            packages="openjdk-${JAVA_VERSION}-jdk-headless curl ca-certificates"
        fi
        if (( REBUILD_IMAGE )) && $CT image info "$IMAGE" >/dev/null 2>&1; then
            log "Deleting cached image $IMAGE"
            $CT image delete "$IMAGE"
        fi
        if ! $CT image info "$IMAGE" >/dev/null 2>&1; then
            BUILD="${IMAGE}-build"
            $CT info "$BUILD" >/dev/null 2>&1 && $CT delete --force "$BUILD"
            log "Building image $IMAGE from $DEFAULT_IMAGE (one-time)"
            build_image() {
                $CT launch "$DEFAULT_IMAGE" "$BUILD" "${launch_args[@]}" || return 1
                local bx=("$CT" exec "$BUILD" --)
                for _ in $(seq 60); do "${bx[@]}" getent hosts archive.ubuntu.com >/dev/null 2>&1 && break; sleep 2; done
                "${bx[@]}" getent hosts archive.ubuntu.com >/dev/null 2>&1 || return 1
                "${bx[@]}" apt-get update -qq || return 1
                "${bx[@]}" env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
                    $packages || return 1
                "${bx[@]}" apt-get clean || return 1
                $CT stop "$BUILD" || return 1
                $CT publish "$BUILD" --alias "$IMAGE" || return 1
            }
            if ! build_image; then
                $CT delete --force "$BUILD" >/dev/null 2>&1 || true
                die "cannot build image $IMAGE (are $packages available?)"
            fi
            $CT delete --force "$BUILD"
        fi
    fi
}
