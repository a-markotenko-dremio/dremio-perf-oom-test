"""The bucket of the runs with STORAGE=s3: both tables (input/ and output/) live in it, as they live under STORAGE_PATH with STORAGE=fs."""
import boto3

REGION = "us-east-1"  # required by the client; the servers of the stand ignore it


def client(endpoint, key, secret):
    return boto3.client("s3", endpoint_url=f"http://{endpoint}", aws_access_key_id=key, aws_secret_access_key=secret,
                        region_name=REGION)


def ensure_bucket(s3, bucket):
    if bucket not in [b["Name"] for b in s3.list_buckets()["Buckets"]]:
        s3.create_bucket(Bucket=bucket)


def sizes(s3, bucket, prefix):
    """{key: size} of the objects under the prefix (a folder, without the trailing slash)."""
    pages = s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=f"{prefix}/")
    return {o["Key"]: o["Size"] for page in pages for o in page.get("Contents", [])}  # no "Contents" in an empty page


def delete_keys(s3, bucket, keys):
    keys = list(keys)
    for i in range(0, len(keys), 1000):  # the limit of one request
        s3.delete_objects(Bucket=bucket, Delete={"Objects": [{"Key": k} for k in keys[i:i + 1000]]})


def delete_folder(s3, bucket, prefix):
    delete_keys(s3, bucket, sizes(s3, bucket, prefix))


def upload_folder(s3, bucket, folder, prefix, log=print):
    """Makes the prefix of the bucket hold exactly the files of the folder; a file already there with the same size is kept."""
    local = {f"{prefix}/{f.name}": f for f in sorted(folder.iterdir())}
    remote = sizes(s3, bucket, prefix)
    delete_keys(s3, bucket, remote.keys() - local.keys())
    for key, f in local.items():
        if remote.get(key) != f.stat().st_size:
            s3.upload_file(str(f), bucket, key)
            log(f"uploaded s3://{bucket}/{key}")
