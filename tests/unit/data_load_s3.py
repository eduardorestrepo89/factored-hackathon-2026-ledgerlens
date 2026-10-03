"""An in-memory stand-in for the few boto3 S3 calls data_load makes."""

import io
from pathlib import Path


class FakeS3:
    def __init__(self, objects: dict[tuple[str, str], bytes] | None = None):
        self.objects = dict(objects or {})  # (bucket, key) -> bytes
        self.truncate: set[str] = set()  # keys whose upload loses its last byte

    def get_paginator(self, name):
        assert name == "list_objects_v2"
        return self

    def paginate(self, Bucket, Prefix):
        found = sorted(
            k for b, k in self.objects if b == Bucket and k.startswith(Prefix)
        )
        contents = [
            {"Key": k, "ETag": f'"etag-{k}"', "Size": len(self.objects[(Bucket, k)])}
            for k in found
        ]
        return [{"Contents": contents}, {}]

    def get_object(self, Bucket, Key):
        return {"Body": io.BytesIO(self.objects[(Bucket, Key)])}

    def put_object(self, Bucket, Key, Body, **kwargs):
        self.objects[(Bucket, Key)] = Body if isinstance(Body, bytes) else Body.encode()

    def upload_fileobj(self, Fileobj, Bucket, Key):
        data = Fileobj.read()
        self.objects[(Bucket, Key)] = data[:-1] if Key in self.truncate else data

    def upload_file(self, Filename, Bucket, Key):
        self.objects[(Bucket, Key)] = Path(Filename).read_bytes()

    def download_file(self, Bucket, Key, Filename):
        Path(Filename).write_bytes(self.objects[(Bucket, Key)])

    def delete_object(self, Bucket, Key):
        self.objects.pop((Bucket, Key), None)  # S3 deletes of a missing key succeed

    def head_object(self, Bucket, Key):
        return {"ContentLength": len(self.objects[(Bucket, Key)])}

    def keys(self, bucket: str) -> list[str]:
        return sorted(k for b, k in self.objects if b == bucket)
