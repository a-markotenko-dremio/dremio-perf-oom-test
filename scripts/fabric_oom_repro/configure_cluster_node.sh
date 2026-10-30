#!/usr/bin/env bash
# Makes a Dremio container a node of the two-host stand: mounts the data sets of the stand, forwards its ports from the
# address of this host, sets the cluster keys of dremio.conf and restarts Dremio. Run on the host of the container.
#   scripts/fabric_oom_repro/configure_cluster_node.sh CONTAINER PEER_HOST coordinator|executor MINIO_ENDPOINT
# MINIO_ENDPOINT is host:port of the MinIO of setup_minio.sh: the distributed store (paths.dist) that all nodes share.
# Dremio needs one store for the cluster - the executors write the Iceberg metadata of a dataset and read each
# other's - and on S3 there are no POSIX users, so it does not matter which uid a node's container runs as.
# PEER_HOST is the other host of the cluster as named in /etc/hosts; the address of this host is the one that leads
# to it. For an executor it is the host of the coordinator (ZooKeeper runs there).
# Safe to run again. Heap, direct memory and the container limit are set by deploy_dremio.sh, not here.
set -euo pipefail
source "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/../lib/common.sh"
source "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/../lib/cluster.sh"

[[ $# -eq 4 ]] || { echo "usage: $0 CONTAINER PEER_HOST coordinator|executor MINIO_ENDPOINT" >&2; exit 2; }
NAME=$1
PEER=$2
detect_container_cli
mount_stand_dir "$STAND_DATA_DEVICE" "$(default OOM_REPRO_DIR)"
HOST_IP=$(own_address "$PEER")
DIST=dremioS3:///$(default OOM_REPRO_DIST_BUCKET)

# The S3 client of the distributed store, as the Dremio documentation writes it for MinIO: the endpoint carries no
# scheme, path style access and the compatibility mode are required.
cx tee /opt/dremio/conf/core-site.xml >/dev/null <<XML
<configuration>
  <property><name>fs.dremioS3.impl</name><value>com.dremio.plugins.s3.store.S3FileSystem</value></property>
  <property><name>fs.s3a.access.key</name><value>$(default OOM_REPRO_MINIO_KEY)</value></property>
  <property><name>fs.s3a.secret.key</name><value>$(default OOM_REPRO_MINIO_SECRET)</value></property>
  <property><name>fs.s3a.aws.credentials.provider</name><value>org.apache.hadoop.fs.s3a.SimpleAWSCredentialsProvider</value></property>
  <property><name>fs.s3a.endpoint</name><value>$4</value></property>
  <property><name>fs.s3a.path.style.access</name><value>true</value></property>
  <property><name>dremio.s3.compat</name><value>true</value></property>
  <property><name>fs.s3a.connection.ssl.enabled</name><value>false</value></property>
</configuration>
XML
# The conduit (gRPC between the nodes: catalog settings, metadata jobs) listens on a random port unless fixed; the
# peers reach it through the published host address, so it is fixed and forwarded like fabric.
CONDUIT_PORT=45679
case $3 in
    coordinator)
        configure_cluster_node "$HOST_IP" "2181 9047 31010 45678 $CONDUIT_PORT" "registration.publish-host: \"$HOST_IP\"" \
            "services.conduit.port: $CONDUIT_PORT" "paths.dist: \"$DIST\"" ;;
    executor)
        configure_cluster_node "$HOST_IP" "45678 $CONDUIT_PORT" \
            "services.coordinator.enabled: false" "services.coordinator.master.enabled: false" \
            "services.executor.enabled: true" "zookeeper: \"$(host_address "$PEER"):2181\"" \
            "registration.publish-host: \"$HOST_IP\"" "services.conduit.port: $CONDUIT_PORT" "paths.dist: \"$DIST\"" ;;
    *) echo "role must be coordinator or executor, not $3" >&2; exit 2 ;;
esac
echo "done: $NAME advertises $HOST_IP as $3"
