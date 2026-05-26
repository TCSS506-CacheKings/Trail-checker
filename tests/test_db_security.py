"""
Week 6 DB-and-security contract tests for Trail Checker.

Owner: Nick Stjern - DB-and-security

These tests describe the agreed schema and authorization behavior. They
exercise the Flask-Login refactor, login-required enforcement, and the
ownership-based 404 contract from CONTRACTS.md.
"""

from datetime import timedelta

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import SQLModel, Session, select
from werkzeug.security import generate_password_hash

from app import app, engine, OAuthIdentity, SavedTrail, User


@pytest.fixture
def client():
    app.config["TESTING"] = True

    SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)

    with app.test_client() as client:
        yield client


def test_saved_trails_table_exists_with_expected_columns(client):
    """The saved_trails table exists with the agreed contract columns."""
    tables = SQLModel.metadata.tables

    assert "saved_trails" in tables

    columns = tables["saved_trails"].columns.keys()
    expected_columns = {
        "id",
        "user_id",
        "display_name",
        "query_text",
        "latitude",
        "longitude",
        "country",
        "state",
        "notes",
        "created_at",
        "updated_at",
    }

    assert expected_columns.issubset(set(columns))


def test_trail_checks_table_exists_with_expected_columns(client):
    """The trail_checks table exists with the agreed contract columns."""
    tables = SQLModel.metadata.tables

    assert "trail_checks" in tables

    columns = tables["trail_checks"].columns.keys()
    expected_columns = {
        "id",
        "user_id",
        "query_text",
        "resolved_name",
        "latitude",
        "longitude",
        "weather_main",
        "weather_description",
        "temp_f",
        "feels_like_f",
        "humidity",
        "wind_mph",
        "visibility_meters",
        "aqi",
        "pm2_5",
        "pm10",
        "recommendation",
        "checked_at",
    }

    assert expected_columns.issubset(set(columns))


def test_anonymous_user_cannot_view_saved_trails(client):
    """Anonymous users must be blocked from the saved trails page."""
    response = client.get("/saved-trails")

    assert response.status_code in (302, 401)


def test_anonymous_user_cannot_save_trail(client):
    """Anonymous users must not be able to create saved trails."""
    response = client.post(
        "/saved-trails",
        data={
            "display_name": "Mount Rainier",
            "query_text": "Mount Rainier",
            "latitude": "46.8523",
            "longitude": "-121.7603",
        },
    )

    assert response.status_code in (302, 401)


def test_non_owner_delete_returns_404_for_missing_trail(client):
    """Deleting a non-existent trail must return 404 (does not leak existence)."""
    client.post("/register", data={"username": "alice", "password": "password123"})
    client.post("/logout")
    client.post("/register", data={"username": "bob", "password": "password123"})

    response = client.post("/saved-trails/999/delete")

    assert response.status_code == 404


def test_non_owner_delete_real_trail_returns_404(client):
    """A user deleting another user's *real* saved trail must receive 404."""
    client.post("/register", data={"username": "alice", "password": "password123"})

    client.post(
        "/saved-trails",
        data={
            "display_name": "Mount Rainier",
            "query_text": "Mount Rainier",
            "latitude": "46.8523",
            "longitude": "-121.7603",
        },
    )

    with Session(engine) as db:
        alice_trail = db.exec(select(SavedTrail)).first()
        assert alice_trail is not None
        alice_trail_id = alice_trail.id

    client.post("/logout")
    client.post("/register", data={"username": "bob", "password": "password123"})

    delete_response = client.post(f"/saved-trails/{alice_trail_id}/delete")
    assert delete_response.status_code == 404

    check_response = client.get(f"/saved-trails/{alice_trail_id}/check")
    assert check_response.status_code == 404

    with Session(engine) as db:
        still_there = db.get(SavedTrail, alice_trail_id)
        assert still_there is not None
        alice = db.exec(select(User).where(User.username == "alice")).first()
        assert still_there.user_id == alice.id


def test_saved_trail_unique_constraint_blocks_duplicate(client):
    """The composite unique constraint must reject duplicate saves at the DB layer."""
    client.post("/register", data={"username": "carol", "password": "password123"})

    payload = {
        "display_name": "Mount Rainier",
        "query_text": "Mount Rainier",
        "latitude": "46.8523",
        "longitude": "-121.7603",
    }

    client.post("/saved-trails", data=payload)
    client.post("/saved-trails", data=payload)

    with Session(engine) as db:
        rows = db.exec(select(SavedTrail)).all()
        assert len(rows) == 1


def test_cascade_delete_removes_users_saved_trails(client):
    """Deleting a user must cascade-delete that user's saved trails."""
    client.post("/register", data={"username": "dora", "password": "password123"})

    client.post(
        "/saved-trails",
        data={
            "display_name": "Mount Rainier",
            "query_text": "Mount Rainier",
            "latitude": "46.8523",
            "longitude": "-121.7603",
        },
    )

    with Session(engine) as db:
        dora = db.exec(select(User).where(User.username == "dora")).first()
        assert dora is not None
        trail_count_before = len(
            db.exec(select(SavedTrail).where(SavedTrail.user_id == dora.id)).all()
        )
        assert trail_count_before == 1

        db.delete(dora)
        db.commit()

        trail_count_after = len(
            db.exec(select(SavedTrail).where(SavedTrail.user_id == dora.id)).all()
        )
        assert trail_count_after == 0


# ---------------------------------------------------------------------------
# Week 7 — OAuth identity + nullable password contract
# ---------------------------------------------------------------------------


def test_oauth_identity_table_exists_with_expected_columns(client):
    """The oauth_identity table exists with the agreed contract columns."""
    tables = SQLModel.metadata.tables
    assert "oauth_identity" in tables

    columns = tables["oauth_identity"].columns.keys()
    expected = {"id", "user_id", "provider", "provider_user_id", "created_at"}
    assert expected.issubset(set(columns))


def test_users_password_hash_is_nullable(client):
    """Week 7 makes password_hash nullable for OAuth-only users."""
    password_hash_col = SQLModel.metadata.tables["users"].columns["password_hash"]
    assert password_hash_col.nullable is True


def test_user_can_be_created_without_password_hash(client):
    """A User row with password_hash=None must be insertable (OAuth-only)."""
    with Session(engine) as db:
        oauth_only_user = User(username="oauth-only", password_hash=None)
        db.add(oauth_only_user)
        db.commit()
        db.refresh(oauth_only_user)

        assert oauth_only_user.id is not None
        assert oauth_only_user.password_hash is None


def test_login_with_null_password_user_does_not_authenticate(client):
    """Posting any password for an OAuth-only user must fail safely."""
    with Session(engine) as db:
        db.add(User(username="oauth-only", password_hash=None))
        db.commit()

    response = client.post(
        "/login",
        data={"username": "oauth-only", "password": "anything-at-all-1"},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"Invalid" in response.data
    with client.session_transaction() as sess:
        assert "_user_id" not in sess


def test_oauth_identity_unique_constraint(client):
    """(provider, provider_user_id) is unique across all users."""
    with Session(engine) as db:
        u1 = User(username="alice", password_hash=None)
        u2 = User(username="alice-2", password_hash=None)
        db.add_all([u1, u2])
        db.commit()
        db.refresh(u1)
        db.refresh(u2)

        db.add(OAuthIdentity(user_id=u1.id, provider="github", provider_user_id="42"))
        db.commit()

        db.add(OAuthIdentity(user_id=u2.id, provider="github", provider_user_id="42"))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()


def test_oauth_identity_provider_check_constraint_rejects_unknown_provider(client):
    """The CHECK constraint blocks provider strings outside the whitelist."""
    with Session(engine) as db:
        u = User(username="alice", password_hash=None)
        db.add(u)
        db.commit()
        db.refresh(u)

        # "GitHub" with a capital G must be rejected — defense against
        # case-variant duplicates that the unique constraint would miss.
        db.add(
            OAuthIdentity(user_id=u.id, provider="GitHub", provider_user_id="42")
        )
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()


def test_oauth_identity_provider_user_id_must_be_nonempty(client):
    """Empty provider_user_id must be rejected at the DB layer."""
    with Session(engine) as db:
        u = User(username="alice", password_hash=None)
        db.add(u)
        db.commit()
        db.refresh(u)

        db.add(
            OAuthIdentity(user_id=u.id, provider="github", provider_user_id="")
        )
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()


def test_oauth_identity_cascade_delete_with_user(client):
    """Deleting a User must CASCADE-delete that user's oauth identities."""
    with Session(engine) as db:
        u = User(username="alice", password_hash=None)
        db.add(u)
        db.commit()
        db.refresh(u)

        db.add(OAuthIdentity(user_id=u.id, provider="github", provider_user_id="42"))
        db.commit()

        identities_before = db.exec(
            select(OAuthIdentity).where(OAuthIdentity.user_id == u.id)
        ).all()
        assert len(identities_before) == 1

        db.delete(u)
        db.commit()

        identities_after = db.exec(
            select(OAuthIdentity).where(OAuthIdentity.user_id == u.id)
        ).all()
        assert len(identities_after) == 0


def test_password_user_and_oauth_user_are_distinct(client):
    """N3 linking policy: each (provider, provider_user_id) = new User.

    Even if a password-registered user happens to share a username root
    with a GitHub user, they are two distinct identities. The schema
    enforces this by *not* having any cross-link beyond user_id.
    """
    client.post(
        "/register", data={"username": "alice", "password": "password123"}
    )

    with Session(engine) as db:
        oauth_alice = User(username="alice-gh-42", password_hash=None)
        db.add(oauth_alice)
        db.commit()
        db.refresh(oauth_alice)

        db.add(
            OAuthIdentity(
                user_id=oauth_alice.id,
                provider="github",
                provider_user_id="42",
            )
        )
        db.commit()

        users = db.exec(select(User).order_by(User.username)).all()
        usernames = [u.username for u in users]
        assert usernames == ["alice", "alice-gh-42"]


# ---------------------------------------------------------------------------
# Week 7 — Session / cookie / login-manager configuration contract
# ---------------------------------------------------------------------------


def test_session_lifetime_is_twelve_hours():
    """PERMANENT_SESSION_LIFETIME governs the 12h session contract (N4)."""
    assert app.config["PERMANENT_SESSION_LIFETIME"] == timedelta(hours=12)


def test_remember_cookie_lifetime_is_thirty_days():
    """REMEMBER_COOKIE_DURATION governs the 30d remember-me contract (N4)."""
    assert app.config["REMEMBER_COOKIE_DURATION"] == timedelta(days=30)


def test_session_protection_is_strong():
    """Flask-Login session protection is set to 'strong' (S3 hardening)."""
    from app import login_manager

    assert login_manager.session_protection == "strong"


def test_cookie_security_flags_are_set():
    """HttpOnly and SameSite=Lax must be set on both session and remember."""
    assert app.config["SESSION_COOKIE_HTTPONLY"] is True
    assert app.config["SESSION_COOKIE_SAMESITE"] == "Lax"
    assert app.config["REMEMBER_COOKIE_HTTPONLY"] is True
    assert app.config["REMEMBER_COOKIE_SAMESITE"] == "Lax"
