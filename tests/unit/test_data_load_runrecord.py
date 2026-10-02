"""Run records: one JSON per stage under runs/<run-id>/ in the team bucket."""

import pytest
from data_load_s3 import FakeS3

from data_load import runrecord


@pytest.mark.unit
def test_write_then_read_round_trips():
    s3 = FakeS3()
    record = {"tables": {"branches": {"files": 1}}}
    uri = runrecord.write(s3, "team", "run-1", "ingest", record)
    assert uri == "s3://team/runs/run-1/ingest.json"
    assert runrecord.read(s3, "team", "run-1", "ingest") == record


@pytest.mark.unit
@pytest.mark.parametrize("run_id", ["", "../x", "a/b", "x" * 81])
def test_run_ids_cannot_escape_the_runs_prefix(run_id):
    with pytest.raises(ValueError, match="bad run id"):
        runrecord.record_key(run_id, "ingest")


@pytest.mark.unit
def test_unknown_stage_is_rejected():
    with pytest.raises(ValueError, match="unknown stage"):
        runrecord.record_key("run-1", "stage")
