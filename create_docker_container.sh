heap_mb=4096
direct_mb=8192
total_mb=14336

make create-container PACKAGE=/mnt/ubuntu-var/dremio/Downloads/dremio-enterprise-26.1.8-202605070149260956-31448f13.tar.gz JAVA_IMAGE=eclipse-temurin:21-jdk HEAP_MB=$heap_mb DIRECT_MB=$direct_mb CONTAINER_MB=$total_mb CPUS=4 RECREATE=1 STORAGE_PATH=/mnt/ubuntu-var/dremio/temurin-jdk

#make create-container   PACKAGE=/mnt/ubuntu-var/dremio/Downloads/dremio-enterprise-26.1.8-202605070149260956-31448f13.tar.gz   JAVA_IMAGE=cgr.dev/chainguard/jdk:latest   HEAP_MB=8192 DIRECT_MB=16384 CONTAINER_MB=28672 CPUS=4 RECREATE=1
#

make create-container PACKAGE=/mnt/ubuntu-var/dremio/Downloads/dremio-enterprise-26.1.8-202605070149260956-31448f13.tar.gz JAVA_IMAGE=wolfi-jdk:21  HEAP_MB=$heap_mb DIRECT_MB=$direct_mb CONTAINER_MB=$total_mb CPUS=4 RECREATE=1 STORAGE_PATH=/mnt/ubuntu-var/dremio/wolfi-jdk
