"""Tests proving app.db.get_db's real commit/rollback/close behavior against a real database."""
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

import app.db as db_module
from app.db import get_db
from app.models import Game

TEST_APP_ID = 999888777


@pytest.fixture()
def patched_session_local(monkeypatch, engine):
    """Point the REAL get_db's SessionLocal at the test database engine, without touching
    get_db's own logic -- this lets us exercise app.db.get_db unmodified."""
    test_session_local = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(db_module, "SessionLocal", test_session_local)
    return test_session_local


@pytest.fixture()
def throwaway_app(patched_session_local):
    app = FastAPI()

    @app.post("/success")
    def success_route(db: Session = Depends(get_db)):
        db.add(Game(steam_app_id=TEST_APP_ID, title="Commit Test Game", regular_price=100))
        return {"ok": True}

    @app.post("/failure")
    def failure_route(db: Session = Depends(get_db)):
        db.add(Game(steam_app_id=TEST_APP_ID, title="Rollback Test Game", regular_price=100))
        raise RuntimeError("simulated failure")

    return app


@pytest.fixture()
def client(throwaway_app):
    return TestClient(throwaway_app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def cleanup(session_factory):
    yield
    session = session_factory()
    try:
        session.query(Game).filter(Game.steam_app_id == TEST_APP_ID).delete()
        session.commit()
    finally:
        session.close()


def test_get_db_commits_on_success(client, session_factory):
    response = client.post("/success")
    assert response.status_code == 200

    verify = session_factory()
    try:
        game = verify.scalar(select(Game).where(Game.steam_app_id == TEST_APP_ID))
        assert game is not None
        assert game.title == "Commit Test Game"
    finally:
        verify.close()


def test_get_db_rolls_back_on_exception(client, session_factory):
    response = client.post("/failure")
    assert response.status_code == 500

    verify = session_factory()
    try:
        game = verify.scalar(select(Game).where(Game.steam_app_id == TEST_APP_ID))
        assert game is None
    finally:
        verify.close()


def test_get_db_closes_session_on_success(client, mocker):
    close_spy = mocker.spy(Session, "close")
    response = client.post("/success")
    assert response.status_code == 200
    assert close_spy.call_count >= 1


def test_get_db_closes_session_on_exception(client, mocker):
    close_spy = mocker.spy(Session, "close")
    response = client.post("/failure")
    assert response.status_code == 500
    assert close_spy.call_count >= 1
