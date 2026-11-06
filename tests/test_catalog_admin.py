import threading
from datetime import datetime, timedelta, timezone

import pytest
from apscheduler.schedulers.background import BackgroundScheduler

import main
from routers import catalog_admin


_RUN_NOW_PATH = "/api/catalog/collection/run-now"
_STATUS_PATH = "/api/catalog/collection/status"
_API_KEY = "catalog-automation-test-key"


class _SignalingLock:
    """Wraps a real threading.Lock so a test can observe the exact moment a
    caller attempts to acquire it (acquire_attempted), proving blockage
    without any arbitrary timing margin: once acquire() has been entered and
    the wrapped lock is still held elsewhere, the caller is unambiguously
    blocked inside the real lock's own acquire() call, not merely "not yet
    scheduled"."""

    def __init__(self):
        self._lock = threading.Lock()
        self.acquire_attempted = threading.Event()

    def acquire(self, *args, **kwargs):
        self.acquire_attempted.set()
        return self._lock.acquire(*args, **kwargs)

    def release(self):
        self._lock.release()

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *exc_info):
        self.release()


def _automation_headers(user, monkeypatch):
    monkeypatch.setattr("deps.JOBAGENT_API_KEY", _API_KEY)
    monkeypatch.setattr("deps.JOBAGENT_API_KEY_USER_ID", str(user["id"]))
    return {"X-JobAgent-Api-Key": _API_KEY}


class TestCatalogCollectionRoutes:
    def test_trusted_client_can_trigger_and_read_status(self, client, user, monkeypatch):
        headers = _automation_headers(user, monkeypatch)
        modified = []
        scheduler = BackgroundScheduler(timezone="UTC")
        scheduler.add_job(
            lambda: None,
            "interval",
            days=1,
            id="catalog_collection",
            next_run_time=datetime.now(timezone.utc) + timedelta(days=1),
        )
        original_modify_job = scheduler.modify_job

        def record_modify_job(*args, **kwargs):
            modified.append((args, kwargs))
            return original_modify_job(*args, **kwargs)

        monkeypatch.setattr(scheduler, "modify_job", record_modify_job)
        monkeypatch.setattr(main.app.state, "scheduler", scheduler, raising=False)
        main.app.state.catalog_collection_running.clear()

        response = client.post(_RUN_NOW_PATH, headers=headers)
        status = client.get(_STATUS_PATH, headers=headers)

        assert response.status_code == 200
        assert response.json() == {"status": "trigger_requested"}
        assert status.status_code == 200
        assert status.json() == {"running": False}
        assert modified[0][0] == ("catalog_collection",)
        assert modified[0][1]["next_run_time"].tzinfo is not None

    @pytest.mark.parametrize("path,method", [(_RUN_NOW_PATH, "post"), (_STATUS_PATH, "get")])
    def test_session_user_cannot_access_automation_routes(
        self,
        logged_in_client,
        path,
        method,
    ):
        response = getattr(logged_in_client, method)(path)
        assert response.status_code == 403

    def test_running_job_is_not_rescheduled(self, client, user, monkeypatch):
        headers = _automation_headers(user, monkeypatch)
        started = threading.Event()
        release = threading.Event()
        scheduler = BackgroundScheduler(timezone="UTC")

        def slow_catalog_job():
            main.app.state.catalog_collection_running.set()
            started.set()
            try:
                release.wait(timeout=5)
            finally:
                main.app.state.catalog_collection_running.clear()

        scheduler.add_job(
            slow_catalog_job,
            "interval",
            days=1,
            id="catalog_collection",
            max_instances=1,
            coalesce=True,
            next_run_time=datetime.now(timezone.utc),
        )
        scheduler.start()
        try:
            assert started.wait(timeout=2)
            modify_calls = []
            original_modify_job = scheduler.modify_job

            def record_modify_job(*args, **kwargs):
                modify_calls.append((args, kwargs))
                return original_modify_job(*args, **kwargs)

            monkeypatch.setattr(scheduler, "modify_job", record_modify_job)
            monkeypatch.setattr(main.app.state, "scheduler", scheduler, raising=False)

            response = client.post(_RUN_NOW_PATH, headers=headers)
            status = client.get(_STATUS_PATH, headers=headers)

            assert response.status_code == 200
            assert response.json() == {"status": "already_running"}
            assert status.status_code == 200
            assert status.json() == {"running": True}
            assert modify_calls == []
        finally:
            release.set()
            scheduler.shutdown(wait=True)


def test_catalog_running_flag_clears_when_collection_raises(monkeypatch):
    def fail(_conn):
        assert main.app.state.catalog_collection_running.is_set()
        raise RuntimeError("collection failed")

    monkeypatch.setattr("collectors.catalog_runner.run_catalog_collection", fail)
    main.app.state.catalog_collection_running.clear()

    with pytest.raises(RuntimeError, match="collection failed"):
        main._run_catalog_collection_tracked(object())

    assert not main.app.state.catalog_collection_running.is_set()


def test_run_now_blocks_on_the_lock_while_a_transition_holds_it(monkeypatch):
    """The endpoint's is_set()-check-then-modify_job() must be unable to
    proceed while catalog_collection_lock is held elsewhere, or it could
    observe a stale is_set()==False and call modify_job() mid-transition.
    _SignalingLock marks the exact moment the endpoint's acquire() is
    entered, so blockage is observed directly rather than inferred from a
    timeout."""
    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(
        lambda: None, "date", run_date=datetime.now(timezone.utc) + timedelta(days=1),
        id="catalog_collection",
    )
    modify_job_calls = []
    original_modify_job = scheduler.modify_job

    def record_modify_job(*args, **kwargs):
        modify_job_calls.append((args, kwargs))
        return original_modify_job(*args, **kwargs)

    monkeypatch.setattr(scheduler, "modify_job", record_modify_job)
    monkeypatch.setattr(main.app.state, "scheduler", scheduler, raising=False)
    main.app.state.catalog_collection_running.clear()
    fake_lock = _SignalingLock()
    monkeypatch.setattr(catalog_admin, "catalog_collection_lock", fake_lock)

    request = type("FakeRequest", (), {})()
    request.app = main.app
    responses = []

    def call_endpoint():
        responses.append(
            catalog_admin.run_catalog_collection_now(request, user={"id": 1}),
        )

    fake_lock.acquire()
    try:
        caller = threading.Thread(target=call_endpoint)
        caller.start()
        assert fake_lock.acquire_attempted.wait(timeout=5), "endpoint never attempted to acquire the lock"
        # fake_lock is still held by this test at this point, so the caller's
        # acquire() call is now unambiguously blocked inside the real
        # underlying threading.Lock, not merely "not yet scheduled."
        assert caller.is_alive(), (
            "the endpoint returned despite the lock being held -- "
            "its check-then-act is not actually guarded by the lock"
        )
        # Simulate what the real transition's lock-held section does: flip the
        # flag true while still holding the same lock the endpoint is queued on.
        main.app.state.catalog_collection_running.set()
    finally:
        fake_lock.release()

    caller.join(timeout=2)
    assert not caller.is_alive()
    assert responses[0].status == "already_running"
    assert modify_job_calls == []


def test_run_now_sees_already_running_after_a_real_tracked_transition(monkeypatch):
    """Exercises main._run_catalog_collection_tracked() for real: it only
    reaches run_catalog_collection() after its own lock-held `.set()` has
    completed, so collection_started firing proves the flag is already set
    and the lock already free -- the endpoint must then see already_running."""
    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(
        lambda: None, "date", run_date=datetime.now(timezone.utc) + timedelta(days=1),
        id="catalog_collection",
    )
    collection_started = threading.Event()
    collection_finished = threading.Event()
    modify_job_calls = []

    def slow_run_catalog_collection(_conn):
        collection_started.set()
        # Generous fail-safe against a genuinely hung test, not a race margin:
        # the test's own flow is fully event-driven (collection_started gates
        # everything downstream), so this only ever times out if something is
        # actually broken, not from ordinary scheduling variance.
        collection_finished.wait(timeout=30)

    monkeypatch.setattr("collectors.catalog_runner.run_catalog_collection", slow_run_catalog_collection)
    main.app.state.catalog_collection_running.clear()

    original_modify_job = scheduler.modify_job

    def record_modify_job(*args, **kwargs):
        modify_job_calls.append((args, kwargs))
        return original_modify_job(*args, **kwargs)

    monkeypatch.setattr(scheduler, "modify_job", record_modify_job)
    monkeypatch.setattr(main.app.state, "scheduler", scheduler, raising=False)

    request = type("FakeRequest", (), {})()
    request.app = main.app

    tracked = threading.Thread(target=main._run_catalog_collection_tracked, args=(object(),))
    tracked.start()
    try:
        assert collection_started.wait(timeout=2), "tracked transition never started"
        assert main.app.state.catalog_collection_running.is_set()

        response = catalog_admin.run_catalog_collection_now(request, user={"id": 1})
    finally:
        collection_finished.set()
        tracked.join(timeout=2)

    assert not tracked.is_alive()
    assert response.status == "already_running"
    assert modify_job_calls == []
