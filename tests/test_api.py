import os

os.environ["PRINTDASH_MOCK"] = "1"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import main  # noqa: E402
from app.backend import MockBackend  # noqa: E402


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(main, "backend", MockBackend())
    monkeypatch.delenv("PRINTDASH_PASSWORD", raising=False)
    return TestClient(main.app)


def test_health(client):
    assert client.get("/api/health").json() == {"ok": True, "mock": True}


def test_printers(client):
    printers = client.get("/api/printers").json()
    assert printers[0]["name"] == "LaserJet1020"
    assert printers[0]["is_default"] is True
    assert printers[0]["active_jobs"] == 2


def test_jobs_filter(client):
    active = client.get("/api/jobs").json()
    done = client.get("/api/jobs?which=completed").json()
    assert {j["state"] for j in active} <= {"pending", "processing", "held"}
    assert all(j["state"] == "completed" for j in done)
    assert len(client.get("/api/jobs?which=all").json()) == len(active) + len(done)
    assert client.get("/api/jobs?which=bogus").status_code == 422


def test_job_lifecycle(client):
    jid = client.get("/api/jobs").json()[0]["id"]  # newest, pending
    assert client.post(f"/api/jobs/{jid}/hold").status_code == 200
    assert client.post(f"/api/jobs/{jid}/hold").status_code == 400
    assert client.post(f"/api/jobs/{jid}/release").status_code == 200
    assert client.post(f"/api/jobs/{jid}/cancel").status_code == 200
    job = next(j for j in client.get("/api/jobs?which=completed").json() if j["id"] == jid)
    assert job["state"] == "canceled"
    assert client.post(f"/api/jobs/{jid}/restart").status_code == 200
    assert client.post("/api/jobs/9999/cancel").json()["detail"].startswith("Job ")


def test_printer_actions(client):
    assert client.post("/api/printers/LaserJet1020/pause").status_code == 200
    assert client.get("/api/printers").json()[0]["state"] == "stopped"
    assert client.post("/api/printers/LaserJet1020/resume").status_code == 200
    r = client.post("/api/printers/LaserJet1020/testpage").json()
    assert r["job_id"] > 0
    client.post("/api/printers/PDF/default")
    assert client.get("/api/printers").json()[0]["name"] == "PDF"
    client.post("/api/printers/LaserJet1020/cancel-all")
    assert client.get("/api/printers").json()[1]["active_jobs"] == 0
    assert client.post("/api/printers/Nope/pause").status_code == 400
    assert client.post("/api/printers/LaserJet1020/explode").status_code == 422


def test_print_upload(client):
    r = client.post(
        "/api/print",
        data={"printer": "LaserJet1020", "copies": "2", "page_ranges": "1-3, 5"},
        files={"file": ("test.pdf", b"%PDF-1.4 hej", "application/pdf")},
    )
    assert r.status_code == 200, r.text
    jid = r.json()["job_id"]
    assert any(j["id"] == jid and j["title"] == "test.pdf" for j in client.get("/api/jobs").json())


@pytest.mark.parametrize(
    "data,filename,msg",
    [
        ({"printer": "LaserJet1020"}, "virus.exe", "File type"),
        ({"printer": "LaserJet1020", "copies": "0"}, "a.pdf", "Copies"),
        ({"printer": "LaserJet1020", "page_ranges": "1;rm -rf"}, "a.pdf", "page range"),
    ],
)
def test_print_validation(client, data, filename, msg):
    r = client.post("/api/print", data=data, files={"file": (filename, b"x")})
    assert r.status_code == 400
    assert msg in r.json()["detail"]


def test_upload_size_limit(client, monkeypatch):
    monkeypatch.setattr(main, "MAX_UPLOAD_MB", 1)
    r = client.post(
        "/api/print",
        data={"printer": "LaserJet1020"},
        files={"file": ("big.pdf", b"0" * (2 * 1024 * 1024))},
    )
    assert r.status_code == 413


def test_password(client, monkeypatch):
    monkeypatch.setenv("PRINTDASH_PASSWORD", "hemligt")
    assert client.get("/api/printers").status_code == 401
    assert client.get("/").status_code == 401
    assert client.get("/api/printers", auth=("x", "fel")).status_code == 401
    assert client.get("/api/printers", auth=("x", "hemligt")).status_code == 200
    assert client.get("/api/health").status_code == 200


def test_mock_progress(monkeypatch):
    b = MockBackend()
    monkeypatch.setattr(b, "SECONDS_PER_PAGE", 0.001)
    import time

    time.sleep(0.05)
    b.list_jobs()
    time.sleep(0.05)
    assert all(j.state == "completed" for j in b.list_jobs("all"))
