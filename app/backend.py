"""Backends som pratar med utskriftssystemet.

CupsBackend använder pycups mot den lokala CUPS-servern.
MockBackend simulerar en skrivare i minnet, för utveckling utan CUPS.
"""

from __future__ import annotations

import itertools
import os
import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Optional

# CUPS-konstanter (IPP)
PRINTER_STATES = {3: "idle", 4: "processing", 5: "stopped"}
JOB_STATES = {
    3: "pending",
    4: "held",
    5: "processing",
    6: "stopped",
    7: "canceled",
    8: "aborted",
    9: "completed",
}
ACTIVE_JOB_STATES = {"pending", "held", "processing", "stopped"}


class BackendError(Exception):
    """Fel som ska visas för användaren."""


@dataclass
class Printer:
    name: str
    info: str
    location: str
    make_and_model: str
    state: str  # idle | processing | stopped
    state_message: str
    state_reasons: list[str]
    accepting_jobs: bool
    is_default: bool
    device_uri: str
    active_jobs: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Job:
    id: int
    printer: str
    title: str
    user: str
    state: str
    created: Optional[int]
    completed: Optional[int]
    size_kb: Optional[int]
    pages_done: Optional[int]

    def to_dict(self) -> dict:
        return asdict(self)


def _printer_from_uri(uri: str) -> str:
    return uri.rstrip("/").rsplit("/", 1)[-1] if uri else ""


class CupsBackend:
    """Riktig backend mot CUPS via pycups."""

    JOB_ATTRS = [
        "job-id",
        "job-name",
        "job-state",
        "job-printer-uri",
        "job-originating-user-name",
        "time-at-creation",
        "time-at-completed",
        "job-k-octets",
        "job-media-sheets-completed",
    ]

    def __init__(self) -> None:
        import cups  # importeras här så att mock-läget fungerar utan pycups

        self._cups = cups
        # pycups-anslutningar är inte trådsäkra
        self._lock = threading.Lock()

    def _conn(self):
        return self._cups.Connection()

    def _call(self, fn):
        with self._lock:
            try:
                return fn(self._conn())
            except self._cups.IPPError as e:
                status, msg = e.args if len(e.args) == 2 else (None, str(e))
                raise BackendError(msg or f"CUPS-fel {status}") from e
            except RuntimeError as e:
                raise BackendError(f"Kunde inte nå CUPS: {e}") from e

    def list_printers(self) -> list[Printer]:
        def fn(c):
            printers = c.getPrinters()
            default = c.getDefault()
            jobs = c.getJobs(which_jobs="not-completed", requested_attributes=["job-printer-uri"])
            return printers, default, jobs

        printers, default, jobs = self._call(fn)
        counts: dict[str, int] = {}
        for attrs in jobs.values():
            p = _printer_from_uri(attrs.get("job-printer-uri", ""))
            counts[p] = counts.get(p, 0) + 1

        result = []
        for name, a in printers.items():
            reasons = [r for r in a.get("printer-state-reasons", []) if r != "none"]
            result.append(
                Printer(
                    name=name,
                    info=a.get("printer-info") or name,
                    location=a.get("printer-location", ""),
                    make_and_model=a.get("printer-make-and-model", ""),
                    state=PRINTER_STATES.get(a.get("printer-state"), "unknown"),
                    state_message=a.get("printer-state-message", ""),
                    state_reasons=reasons,
                    accepting_jobs=bool(a.get("printer-is-accepting-jobs", True)),
                    is_default=(name == default),
                    device_uri=a.get("device-uri", ""),
                    active_jobs=counts.get(name, 0),
                )
            )
        result.sort(key=lambda p: (not p.is_default, p.name.lower()))
        return result

    def list_jobs(self, which: str = "not-completed", limit: int = 50) -> list[Job]:
        if which not in ("not-completed", "completed", "all"):
            raise BackendError("Ogiltigt urval")
        jobs = self._call(
            lambda c: c.getJobs(which_jobs=which, limit=limit, requested_attributes=self.JOB_ATTRS)
        )
        result = []
        for jid, a in jobs.items():
            result.append(
                Job(
                    id=int(jid),
                    printer=_printer_from_uri(a.get("job-printer-uri", "")),
                    title=a.get("job-name") or "(utan namn)",
                    user=a.get("job-originating-user-name", ""),
                    state=JOB_STATES.get(a.get("job-state"), "unknown"),
                    created=a.get("time-at-creation"),
                    completed=a.get("time-at-completed") or None,
                    size_kb=a.get("job-k-octets"),
                    pages_done=a.get("job-media-sheets-completed"),
                )
            )
        result.sort(key=lambda j: j.id, reverse=True)
        return result

    # Jobbåtgärder
    def cancel_job(self, job_id: int) -> None:
        self._call(lambda c: c.cancelJob(job_id))

    def hold_job(self, job_id: int) -> None:
        self._call(lambda c: c.setJobHoldUntil(job_id, "indefinite"))

    def release_job(self, job_id: int) -> None:
        self._call(lambda c: c.setJobHoldUntil(job_id, "no-hold"))

    def restart_job(self, job_id: int) -> None:
        self._call(lambda c: c.restartJob(job_id))

    def cancel_all(self, printer: str) -> None:
        self._call(lambda c: c.cancelAllJobs(name=printer))

    # Skrivaråtgärder
    def pause_printer(self, name: str) -> None:
        self._call(lambda c: c.disablePrinter(name))

    def resume_printer(self, name: str) -> None:
        def fn(c):
            c.enablePrinter(name)
            c.acceptJobs(name)

        self._call(fn)

    def set_default(self, name: str) -> None:
        self._call(lambda c: c.setDefault(name))

    def test_page(self, name: str) -> int:
        return self._call(lambda c: c.printTestPage(name))

    def print_file(self, printer: str, path: str, title: str, options: dict[str, str]) -> int:
        return self._call(lambda c: c.printFile(printer, path, title, options))


# ---------------------------------------------------------------------------


@dataclass
class _MockJob:
    id: int
    printer: str
    title: str
    user: str
    created: int
    size_kb: int
    pages: int
    state: str = "pending"
    progress: float = 0.0
    completed: Optional[int] = None


@dataclass
class _MockPrinter:
    name: str
    info: str
    location: str
    make_and_model: str
    device_uri: str
    enabled: bool = True
    accepting: bool = True
    reasons: list[str] = field(default_factory=list)


class MockBackend:
    """Simulerar CUPS i minnet. Jobb skrivs ut med ca 4 sekunder per sida."""

    SECONDS_PER_PAGE = 4.0

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._ids = itertools.count(101)
        self._printers = {
            "LaserJet1020": _MockPrinter(
                name="LaserJet1020",
                info="HP LaserJet 1020",
                location="Kontoret",
                make_and_model="HP LaserJet 1020, hpcups 3.23",
                device_uri="hp:/usb/HP_LaserJet_1020?serial=FN0ABC123",
            ),
            "PDF": _MockPrinter(
                name="PDF",
                info="Skriv till PDF",
                location="",
                make_and_model="Generic CUPS-PDF Printer",
                device_uri="cups-pdf:/",
            ),
        }
        self._default = "LaserJet1020"
        self._jobs: dict[int, _MockJob] = {}
        self._last_tick = time.monotonic()
        now = int(time.time())
        for title, pages, age in [
            ("Kvitto_oktober.pdf", 1, 7200),
            ("Resplan Göteborg.pdf", 3, 3600),
            ("Recept – kanelbullar", 2, 600),
        ]:
            j = self._new_job("LaserJet1020", title, pages, now - age)
            j.state, j.progress, j.completed = "completed", 1.0, now - age + pages * 4
        self._new_job("LaserJet1020", "Faktura 2026-118.pdf", 2, now - 5)
        self._new_job("LaserJet1020", "Biljett.pdf", 1, now - 2)

    def _new_job(self, printer: str, title: str, pages: int, created: Optional[int] = None) -> _MockJob:
        jid = next(self._ids)
        job = _MockJob(
            id=jid,
            printer=printer,
            title=title,
            user=os.environ.get("USER", "pi"),
            created=created or int(time.time()),
            size_kb=pages * 85,
            pages=max(1, pages),
        )
        self._jobs[jid] = job
        return job

    def _tick(self) -> None:
        """Låt tiden gå: driv första aktiva jobbet per skrivare framåt."""
        now = time.monotonic()
        dt = now - self._last_tick
        self._last_tick = now
        for p in self._printers.values():
            if not p.enabled:
                continue
            for job in sorted(self._jobs.values(), key=lambda j: j.id):
                if job.printer != p.name or job.state not in ("pending", "processing"):
                    continue
                job.state = "processing"
                job.progress += dt / (self.SECONDS_PER_PAGE * job.pages)
                if job.progress >= 1.0:
                    job.progress, job.state, job.completed = 1.0, "completed", int(time.time())
                break  # en skrivare skriver ett jobb i taget

    def _printer(self, name: str) -> _MockPrinter:
        if name not in self._printers:
            raise BackendError(f"Okänd skrivare: {name}")
        return self._printers[name]

    def _job(self, job_id: int) -> _MockJob:
        if job_id not in self._jobs:
            raise BackendError(f"Jobbet {job_id} finns inte")
        return self._jobs[job_id]

    def list_printers(self) -> list[Printer]:
        with self._lock:
            self._tick()
            out = []
            for p in self._printers.values():
                active = [j for j in self._jobs.values() if j.printer == p.name and j.state in ACTIVE_JOB_STATES]
                if not p.enabled:
                    state, msg = "stopped", "Pausad av administratör"
                elif any(j.state == "processing" for j in active):
                    j = next(j for j in active if j.state == "processing")
                    state, msg = "processing", f"Skriver ut ”{j.title}”"
                else:
                    state, msg = "idle", ""
                out.append(
                    Printer(
                        name=p.name,
                        info=p.info,
                        location=p.location,
                        make_and_model=p.make_and_model,
                        state=state,
                        state_message=msg,
                        state_reasons=list(p.reasons),
                        accepting_jobs=p.accepting,
                        is_default=p.name == self._default,
                        device_uri=p.device_uri,
                        active_jobs=len(active),
                    )
                )
            out.sort(key=lambda p: (not p.is_default, p.name.lower()))
            return out

    def list_jobs(self, which: str = "not-completed", limit: int = 50) -> list[Job]:
        if which not in ("not-completed", "completed", "all"):
            raise BackendError("Ogiltigt urval")
        with self._lock:
            self._tick()
            out = []
            for j in sorted(self._jobs.values(), key=lambda j: j.id, reverse=True):
                active = j.state in ACTIVE_JOB_STATES
                if which == "not-completed" and not active:
                    continue
                if which == "completed" and active:
                    continue
                out.append(
                    Job(
                        id=j.id,
                        printer=j.printer,
                        title=j.title,
                        user=j.user,
                        state=j.state,
                        created=j.created,
                        completed=j.completed,
                        size_kb=j.size_kb,
                        pages_done=int(j.progress * j.pages),
                    )
                )
            return out[:limit]

    def cancel_job(self, job_id: int) -> None:
        with self._lock:
            j = self._job(job_id)
            if j.state not in ACTIVE_JOB_STATES:
                raise BackendError("Jobbet är redan avslutat")
            j.state, j.completed = "canceled", int(time.time())

    def hold_job(self, job_id: int) -> None:
        with self._lock:
            j = self._job(job_id)
            if j.state != "pending":
                raise BackendError("Bara väntande jobb kan pausas")
            j.state = "held"

    def release_job(self, job_id: int) -> None:
        with self._lock:
            j = self._job(job_id)
            if j.state != "held":
                raise BackendError("Jobbet är inte pausat")
            j.state = "pending"

    def restart_job(self, job_id: int) -> None:
        with self._lock:
            j = self._job(job_id)
            if j.state in ACTIVE_JOB_STATES:
                raise BackendError("Jobbet är fortfarande aktivt")
            j.state, j.progress, j.completed = "pending", 0.0, None

    def cancel_all(self, printer: str) -> None:
        with self._lock:
            self._printer(printer)
            for j in self._jobs.values():
                if j.printer == printer and j.state in ACTIVE_JOB_STATES:
                    j.state, j.completed = "canceled", int(time.time())

    def pause_printer(self, name: str) -> None:
        with self._lock:
            self._tick()
            self._printer(name).enabled = False

    def resume_printer(self, name: str) -> None:
        with self._lock:
            self._tick()
            p = self._printer(name)
            p.enabled = p.accepting = True

    def set_default(self, name: str) -> None:
        with self._lock:
            self._printer(name)
            self._default = name

    def test_page(self, name: str) -> int:
        with self._lock:
            self._printer(name)
            return self._new_job(name, "Testsida", 1).id

    def print_file(self, printer: str, path: str, title: str, options: dict[str, str]) -> int:
        with self._lock:
            p = self._printer(printer)
            if not p.accepting:
                raise BackendError("Skrivaren tar inte emot jobb")
            copies = int(options.get("copies", "1"))
            size = os.path.getsize(path)
            pages = max(1, size // 60_000) * copies
            return self._new_job(printer, title, pages).id


def make_backend():
    if os.environ.get("PRINTDASH_MOCK", "").lower() in ("1", "true", "yes"):
        return MockBackend()
    return CupsBackend()
