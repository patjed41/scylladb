wget -nc https://s3.amazonaws.com/downloads.scylladb.com/downloads/scylla/relocatable/scylladb-2025.2/scylla-2025.2.0~rc1-0.20250513.6f1efcff315f.x86_64.tar.gz -O scylla.tar.gz
mkdir binary
tar -xf scylla.tar.gz -C binary --strip-components=1
docker build -t scylla:local .