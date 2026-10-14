PKG=~/Downloads/dremio-enterprise-27.0.0-main-202610090921320495-b7946edd.tar.gz
SP=/mnt/ubuntu-var/dremio/dremio-j21-d27
C=dremio-j21-d27-4G

for cfg in "2048 1024" "1536 1024" "1024 1024" "1024 512" "768 512"; do
  set -- $cfg
  echo "### heap=$1 direct=$2"
  if ./deploy_dremio.sh --package $PKG --storage-path $SP --java-version 21 \
       --container-memory-mb 4096 --heap-memory-mb $1 --direct-memory-mb $2 \
       --accept-eula --recreate --dry-run; then
    for rows in 10000000 50000000 100000000 200000000 500000000; do
      make test-container CONTAINER=$C ROW_COUNT=$rows || { echo "FAIL heap=$1 direct=$2 rows=$rows"; break; }
    done
  else
    echo "deploy failed: heap=$1 direct=$2"
  fi
  lxc delete -f $C
done
