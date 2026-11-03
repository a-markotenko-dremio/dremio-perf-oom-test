"""Offline tests of s3store on a fake S3 client: the bucket of the STORAGE=s3 runs and the table folders in it."""
import pytest

import s3store

TABLE = "input/STACKIT_S3/tpcds-1tb-flat/catalog_sales"


class FakeS3:
    """The calls of boto3 that s3store makes, over a dict of key -> bytes."""

    def __init__(self, objects=None, buckets=()):
        self.objects, self.buckets, self.deleted = dict(objects or {}), list(buckets), []

    def list_buckets(self):
        return {"Buckets": [{"Name": b} for b in self.buckets]}

    def create_bucket(self, Bucket):
        self.buckets.append(Bucket)

    def get_paginator(self, name):
        assert name == "list_objects_v2"
        fake = self

        class Paginator:
            def paginate(self, Bucket, Prefix):
                found = [{"Key": k, "Size": len(v)} for k, v in sorted(fake.objects.items()) if k.startswith(Prefix)]
                return [{"Contents": found[:2]}, {"Contents": found[2:]}] if found else [{}]  # an empty listing has no Contents
        return Paginator()

    def delete_objects(self, Bucket, Delete):
        assert len(Delete["Objects"]) <= 1000
        for o in Delete["Objects"]:
            self.deleted.append(o["Key"])
            del self.objects[o["Key"]]

    def upload_file(self, path, Bucket, Key):
        self.objects[Key] = open(path, "rb").read()


@pytest.fixture
def blocks(tmp_path):
    folder = tmp_path / "catalog_sales"
    folder.mkdir()
    for name, data in (("block_0000000000_10.parquet", b"a" * 10), ("block_0000000010_5.parquet", b"b" * 5)):
        (folder / name).write_bytes(data)
    return folder


def test_a_missing_bucket_is_created_and_an_existing_one_is_left(tmp_path):
    s3 = FakeS3(buckets=["d26-1-8-wolfi-jdk-21-8G-4cpu"])
    s3store.ensure_bucket(s3, "d26-1-8-wolfi-jdk-21-8G-4cpu")
    assert s3.buckets == ["d26-1-8-wolfi-jdk-21-8G-4cpu"]
    s3store.ensure_bucket(s3, "d26-1-10-wolfi-jdk-21-8G-4cpu")
    assert s3.buckets == ["d26-1-8-wolfi-jdk-21-8G-4cpu", "d26-1-10-wolfi-jdk-21-8G-4cpu"]


def test_the_blocks_of_a_table_are_uploaded_into_its_folder(blocks):
    s3, log = FakeS3(), []
    s3store.upload_folder(s3, "b", blocks, TABLE, log=log.append)
    assert {k: len(v) for k, v in s3.objects.items()} == {f"{TABLE}/block_0000000000_10.parquet": 10, f"{TABLE}/block_0000000010_5.parquet": 5}
    assert len(log) == 2


def test_a_block_that_is_already_there_is_not_uploaded_again_and_a_block_that_is_not_wanted_is_removed(blocks):
    s3 = FakeS3({f"{TABLE}/block_0000000000_10.parquet": b"x" * 10, f"{TABLE}/block_0000000020_10.parquet": b"c" * 10,
                 f"{TABLE}_other/block.parquet": b"z"})
    log = []
    s3store.upload_folder(s3, "b", blocks, TABLE, log=log.append)
    assert s3.deleted == [f"{TABLE}/block_0000000020_10.parquet"]
    assert log == [f"uploaded s3://b/{TABLE}/block_0000000010_5.parquet"]
    assert s3.objects[f"{TABLE}/block_0000000000_10.parquet"] == b"x" * 10  # kept: the size is the same
    assert f"{TABLE}_other/block.parquet" in s3.objects  # a folder of a similar name is not this one


def test_a_folder_is_deleted_page_by_page_in_requests_of_at_most_1000_keys():
    s3 = FakeS3({f"output/tpcds-1tb/catalog_sales/data/{i}.parquet": b"x" for i in range(2500)} | {"input/keep": b"k"})
    s3store.delete_folder(s3, "b", "output/tpcds-1tb/catalog_sales")
    assert list(s3.objects) == ["input/keep"]


def test_deleting_a_folder_that_is_not_there_is_not_an_error():
    s3store.delete_folder(FakeS3(), "b", "output/tpcds-1tb/catalog_sales")
