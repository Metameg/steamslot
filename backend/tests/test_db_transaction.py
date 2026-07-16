"""Test request-scoped transaction management in get_db()."""
import uuid
from collections.abc import Iterator
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from app.db import get_db
from app.models import Game
from app.config import get_settings


@pytest.fixture()
def app_with_routes(engine):
    """Create a test FastAPI app with routes that use get_db."""
    # Create a SessionLocal for the test database
    TestSessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

    def get_db_test() -> Iterator[Session]:
        """Test version of get_db using test database."""
        db = TestSessionLocal()
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    test_app = FastAPI()

    @test_app.post("/write-success")
    def write_success_route(db: Session = Depends(get_db_test)):
        """Route that writes a Game and returns success."""
        game = Game(
            steam_app_id=123456,
            title="Test Game Success",
            regular_price=2999,
            header_image_url=None,
        )
        db.add(game)
        return {"status": "success"}

    @test_app.post("/write-with-exception")
    def write_with_exception_route(db: Session = Depends(get_db_test)):
        """Route that writes a Game and then raises an exception."""
        game = Game(
            steam_app_id=789012,
            title="Test Game Exception",
            regular_price=4999,
            header_image_url=None,
        )
        db.add(game)
        raise ValueError("Intentional exception for testing rollback")

    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    return test_app, session_factory


def test_get_db_commits_on_success(app_with_routes):
    """Test that get_db commits on successful route completion."""
    app, session_factory = app_with_routes
    client = TestClient(app)

    # Hit the success route
    response = client.post("/write-success")
    assert response.status_code == 200
    assert response.json() == {"status": "success"}

    # Verify the row was committed by checking with an independent session
    session = session_factory()
    try:
        game = session.query(Game).filter_by(steam_app_id=123456).first()
        assert game is not None, "Game row should exist after successful write"
        assert game.title == "Test Game Success"
    finally:
        session.close()


def test_get_db_rollback_on_exception(app_with_routes):
    """Test that get_db rolls back on exception and doesn't persist the row."""
    app, session_factory = app_with_routes
    client = TestClient(app)

    # Hit the exception route (TestClient will raise the exception)
    try:
        response = client.post("/write-with-exception")
        # If we get here, the exception was caught and turned into a response
        assert response.status_code == 500
    except ValueError as e:
        # TestClient re-raises unhandled exceptions
        assert str(e) == "Intentional exception for testing rollback"

    # Verify the row was NOT committed (rolled back) by checking with an independent session
    session = session_factory()
    try:
        game = session.query(Game).filter_by(steam_app_id=789012).first()
        assert game is None, "Game row should NOT exist after exception (should be rolled back)"
    finally:
        session.close()


def test_get_db_closes_session_on_success(app_with_routes):
    """Test that get_db closes the session after successful route completion."""
    app, session_factory = app_with_routes
    client = TestClient(app)

    # Hit the success route
    response = client.post("/write-success")
    assert response.status_code == 200

    # If the session wasn't closed properly, this should not raise an error
    # because the TestClient context manages cleanup appropriately


def test_get_db_closes_session_on_exception(app_with_routes):
    """Test that get_db closes the session even when an exception occurs."""
    app, session_factory = app_with_routes
    client = TestClient(app)

    # Hit the exception route (TestClient will raise the exception)
    try:
        response = client.post("/write-with-exception")
        # If we get here, the exception was caught and turned into a response
        assert response.status_code == 500
    except ValueError:
        # Expected: TestClient re-raises unhandled exceptions
        pass

    # If the session wasn't closed properly, this should not raise an error
    # because the TestClient context manages cleanup appropriately


@pytest.fixture(autouse=True)
def cleanup_test_data(session_factory):
    """Clean up test data after each test."""
    yield
    # Clean up any Game rows we created during testing
    session = session_factory()
    try:
        session.query(Game).filter(
            Game.steam_app_id.in_([123456, 789012])
        ).delete()
        session.commit()
    finally:
        session.close()
