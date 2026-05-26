"""
Course 506 Week 6 — Trail Checker (DB-and-security slice implemented)

Flask + Postgres + SQLModel + Flask-Login + Flask-WTF + Flask-Limiter.

The home page serves the static site you sync from your S3 bucket into
S3_content/. Login, register, logout, and about are Flask-rendered routes.
Saved trail routes are protected by Flask-Login and enforce ownership at
the database query level.
"""

import logging
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

# Load .env BEFORE any os.environ reads below. load_dotenv() is a no-op
# for variables already present in the environment (e.g. when Docker
# Compose injects them via env_file), so it is safe for both bare-metal
# `flask run` / `pytest` and containerized runs.
load_dotenv()

from flask import (
    Flask, render_template, request, redirect, url_for, session, flash, g,
    send_from_directory, abort, jsonify,
)
from flask_login import (
    LoginManager,
    UserMixin,
    login_user,
    logout_user,
    current_user,
    login_required,
)
from flask_wtf.csrf import CSRFProtect, CSRFError
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    event,
)
from sqlalchemy.exc import IntegrityError
from sqlmodel import SQLModel, Field, Session, create_engine, select
from werkzeug.security import generate_password_hash, check_password_hash
from weather_service import (
    GeocodeNotFoundError,
    ExternalAPIError,
    ExternalAPIUnavailableError,
    get_conditions_for_coordinates,
    get_conditions_for_query,
)


TESTING = os.environ.get("TESTING") == "1"


app = Flask(__name__)


app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-not-for-production")


if (
    not TESTING
    and not app.debug
    and app.config["SECRET_KEY"] == "dev-secret-not-for-production"
):
    raise RuntimeError(
        "SECRET_KEY is unset or still the default placeholder.\n"
        "  1. Copy .env.example to .env:   cp .env.example .env\n"
        "  2. Set SECRET_KEY in .env to a long random string.\n"
        "     (e.g. python -c \"import secrets; print(secrets.token_urlsafe(48))\")\n"
        "  3. Make sure the SECRET_KEY line is NOT commented out.\n"
        "See README.md -> 'Required environment variables' for the full list."
    )

app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=not (app.debug or TESTING),
    PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
    REMEMBER_COOKIE_HTTPONLY=True,
    REMEMBER_COOKIE_SAMESITE="Lax",
    REMEMBER_COOKIE_SECURE=not (app.debug or TESTING),
    REMEMBER_COOKIE_DURATION=timedelta(days=30),
    WTF_CSRF_ENABLED=not TESTING,
    WTF_CSRF_TIME_LIMIT=3600,
)

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://app:app@db:5432/app")

engine = create_engine(DATABASE_URL, echo=False)


@event.listens_for(engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record):
    """Force SQLite connections to enforce foreign keys.

    Postgres enforces FK + ondelete clauses by default, but SQLite does not
    unless the pragma is set per connection. Without this, FK + CASCADE
    behavior silently passes in tests while real production would catch it
    or vice versa. Aligning the two dialects keeps the contract test bed
    honest.
    """
    if engine.dialect.name == "sqlite":
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


S3_CONTENT_DIR = Path(__file__).parent / "S3_content"


login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"
# "strong" tears down the session entirely on IP/user-agent change. Default
# is "basic" which only marks it non-fresh. Strong is the right call for an
# app with no money flow but real per-user data: false positives (user
# changing networks) just require re-login, which is cheap.
login_manager.session_protection = "strong"

csrf = CSRFProtect(app)

limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=[],
    enabled=not TESTING,
)


audit_logger = logging.getLogger("trail_checker.audit")
audit_logger.setLevel(logging.INFO)
if not audit_logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(
        logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")
    )
    audit_logger.addHandler(_handler)


def audit(event: str, **fields):
    """Structured audit log for state-changing events. Never log secrets."""
    payload = " ".join(f"{key}={value}" for key, value in fields.items())
    audit_logger.info("event=%s %s", event, payload)


MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 128
PASSWORD_RE = re.compile(r"^(?=.*[A-Za-z])(?=.*\d).{8,128}$")

_DUMMY_PASSWORD_HASH = generate_password_hash("not-a-real-password")


class User(UserMixin, SQLModel, table=True):
    __tablename__ = "users"

    id: int | None = Field(default=None, primary_key=True)
    username: str = Field(
        sa_column=Column(String(80), nullable=False, unique=True, index=True),
    )
    # NULLABLE in Week 7 to support OAuth-only users who have no password.
    # The login route refuses authentication when password_hash IS NULL so
    # a NULL hash can never accidentally authenticate. The Week 7 contract
    # is that every User has at least one auth method, enforced at the
    # transactional layer in the OAuth callback (see CONTRACTS.md §4).
    password_hash: str | None = Field(
        default=None,
        sa_column=Column(String(255), nullable=True),
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class OAuthIdentity(SQLModel, table=True):
    """Federated identity from an external provider (GitHub for Week 7).

    Schema enforces the Week 7 linking policy: UNIQUE(provider,
    provider_user_id) means each external account maps to exactly one
    local User; the CHECK constraint on `provider` blocks accidental
    case-variant duplicates ("github" vs "GitHub") that the unique
    constraint would otherwise miss. CASCADE on user deletion keeps
    orphan identities impossible.
    """

    __tablename__ = "oauth_identity"
    __table_args__ = (
        UniqueConstraint(
            "provider",
            "provider_user_id",
            name="uq_oauth_provider_user",
        ),
        CheckConstraint(
            "provider IN ('github')",
            name="ck_oauth_provider_allowed",
        ),
        CheckConstraint(
            "length(provider_user_id) > 0",
            name="ck_oauth_provider_user_id_nonempty",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    provider: str = Field(sa_column=Column(String(50), nullable=False))
    provider_user_id: str = Field(
        sa_column=Column(String(255), nullable=False)
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class SavedTrail(SQLModel, table=True):
    __tablename__ = "saved_trails"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "latitude",
            "longitude",
            name="uq_saved_trails_user_lat_lon",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        )
    )
    display_name: str = Field(sa_column=Column(String(100), nullable=False))
    query_text: str = Field(sa_column=Column(String(100), nullable=False))
    latitude: float = Field(sa_column=Column(Float, nullable=False))
    longitude: float = Field(sa_column=Column(Float, nullable=False))
    country: str | None = Field(
        default=None, sa_column=Column(String(10), nullable=True)
    )
    state: str | None = Field(
        default=None, sa_column=Column(String(100), nullable=True)
    )
    notes: str | None = Field(
        default=None, sa_column=Column(String(500), nullable=True)
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class TrailCheck(SQLModel, table=True):
    __tablename__ = "trail_checks"

    id: int | None = Field(default=None, primary_key=True)
    user_id: int | None = Field(
        default=None,
        sa_column=Column(
            Integer,
            ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    query_text: str = Field(sa_column=Column(String(100), nullable=False))
    resolved_name: str = Field(sa_column=Column(String(100), nullable=False))
    latitude: float = Field(sa_column=Column(Float, nullable=False))
    longitude: float = Field(sa_column=Column(Float, nullable=False))
    weather_main: str = Field(sa_column=Column(String(50), nullable=False))
    weather_description: str = Field(sa_column=Column(String(100), nullable=False))
    temp_f: float = Field(sa_column=Column(Float, nullable=False))
    feels_like_f: float | None = None
    humidity: int | None = None
    wind_mph: float | None = None
    visibility_meters: int | None = None
    aqi: int | None = None
    pm2_5: float | None = None
    pm10: float | None = None
    recommendation: str = Field(sa_column=Column(String(20), nullable=False))
    checked_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


def get_db_session():
    if "db_session" not in g:
        g.db_session = Session(engine)
    return g.db_session


@app.teardown_appcontext
def close_db_session(exception=None):
    db_session = g.pop("db_session", None)
    if db_session is not None:
        db_session.close()


@login_manager.user_loader
def load_user(user_id: str):
    try:
        user_id_int = int(user_id)
    except (TypeError, ValueError):
        return None
    db = get_db_session()
    return db.get(User, user_id_int)


@app.context_processor
def inject_user():
    return {
        "user": current_user if current_user.is_authenticated else None,
    }


@app.errorhandler(CSRFError)
def handle_csrf_error(error):
    """Anonymous CSRF failures should look the same as @login_required denials.

    This keeps the e2e walk's step 8 assertion clean: every anonymous
    state-changing request lands at /login regardless of which gate fired.
    """
    if not current_user.is_authenticated:
        return redirect(url_for("login"))
    flash("Your session expired. Please try again.")
    return redirect(request.referrer or url_for("home"))


def validate_text(value: str | None, min_len: int, max_len: int, field_name: str) -> str:
    cleaned = (value or "").strip()
    if len(cleaned) < min_len or len(cleaned) > max_len:
        raise ValueError(f"Invalid {field_name}")
    return cleaned


def validate_optional_text(value: str | None, max_len: int, field_name: str) -> str | None:
    cleaned = (value or "").strip()
    if not cleaned:
        return None
    if len(cleaned) > max_len:
        raise ValueError(f"Invalid {field_name}")
    return cleaned


def validate_float(value: str | None, min_value: float, max_value: float, field_name: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"Invalid {field_name}")
    if parsed < min_value or parsed > max_value:
        raise ValueError(f"Invalid {field_name}")
    return parsed


def validate_password_policy(password: str) -> None:
    if PASSWORD_RE.fullmatch(password or "") is None:
        raise ValueError(
            f"Password must be {MIN_PASSWORD_LENGTH}-{MAX_PASSWORD_LENGTH} "
            "characters and include both letters and a digit."
        )


@app.route("/")
def home():
    return render_template("home.html")


@app.route("/site/")
def site_home():
    index_path = S3_CONTENT_DIR / "index.html"
    if not index_path.exists():
        return render_template("placeholder.html"), 200
    return send_from_directory(S3_CONTENT_DIR, "index.html")


@app.route("/site/<path:filename>")
def serve_s3_content(filename):
    file_path = S3_CONTENT_DIR / filename
    if not file_path.exists() or not file_path.is_file():
        abort(404)
    return send_from_directory(S3_CONTENT_DIR, filename)


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "GET":
        return render_template("register.html")

    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")

    if not username or not password:
        flash("Username and password are required.")
        return redirect(url_for("register"))

    try:
        validate_password_policy(password)
    except ValueError as error:
        flash(str(error))
        return redirect(url_for("register"))

    db = get_db_session()
    existing = db.exec(select(User).where(User.username == username)).first()
    if existing is not None:
        flash("That username is already taken.")
        return redirect(url_for("register"))

    user = User(
        username=username,
        password_hash=generate_password_hash(password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    login_user(user)
    # session.permanent makes PERMANENT_SESSION_LIFETIME (12h) effective.
    # Without this, the cookie would be a browser-session cookie that dies
    # on browser close, ignoring the configured lifetime.
    session.permanent = True
    audit(
        "user.register",
        user_id=user.id,
        username=username,
        ip=request.remote_addr,
    )
    return redirect(url_for("home"))


@app.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
def login():
    if request.method == "GET":
        return render_template("login.html")

    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    remember = bool(request.form.get("remember"))

    db = get_db_session()
    user = db.exec(select(User).where(User.username == username)).first()

    # NULL password_hash = OAuth-only user (no password set). We do NOT
    # accept any password as valid for them, and we still run the dummy
    # hash so the response time matches the wrong-password branch.
    if user is None or user.password_hash is None:
        check_password_hash(_DUMMY_PASSWORD_HASH, password)
        audit("user.login.failure", username=username, ip=request.remote_addr)
        flash("Invalid username or password.")
        return redirect(url_for("login"))

    if not check_password_hash(user.password_hash, password):
        audit("user.login.failure", username=username, ip=request.remote_addr)
        flash("Invalid username or password.")
        return redirect(url_for("login"))

    login_user(user, remember=remember)
    session.permanent = True
    audit(
        "user.login.success",
        user_id=user.id,
        remember=remember,
        ip=request.remote_addr,
    )
    return redirect(url_for("home"))


@app.route("/logout", methods=["POST"])
@login_required
def logout():
    user_id = current_user.id
    logout_user()
    audit("user.logout", user_id=user_id, ip=request.remote_addr)
    return redirect(url_for("home"))


@app.route("/about")
def about():
    return render_template("about.html")


# ---------------------------------------------------------------------------
# Routes — Trail Checker
# ---------------------------------------------------------------------------

def _json_error(code: str, message: str, status: int):
    return jsonify({"ok": False, "error": {"code": code, "message": message}}), status


def _parse_query_text(raw_query: str) -> str | None:
    query_text = raw_query.strip()
    if len(query_text) < 2 or len(query_text) > 100:
        return None
    return query_text


def _results_context_from_data(data: dict, is_saved: bool = False) -> dict:
    weather = data.get("weather") or {}
    air_quality = data.get("air_quality") or {}
    return {
        "query_text": data["query_text"],
        "resolved_name": data["resolved_name"],
        "latitude": data["latitude"],
        "longitude": data["longitude"],
        "weather_main": weather.get("main"),
        "weather_description": weather.get("description"),
        "temp_f": weather.get("temp_f"),
        "feels_like_f": weather.get("feels_like_f"),
        "humidity": weather.get("humidity"),
        "wind_mph": weather.get("wind_mph"),
        "visibility_meters": weather.get("visibility_meters"),
        "aqi": air_quality.get("aqi"),
        "pm2_5": air_quality.get("pm2_5"),
        "pm10": air_quality.get("pm10"),
        "recommendation": data.get("recommendation", "unknown"),
        "country": data.get("country"),
        "state": data.get("state"),
        "is_saved": is_saved,
    }


def _current_user_id_or_none() -> int | None:
    if current_user.is_authenticated:
        return current_user.id
    return None


def _is_saved_trail(
    db: Session,
    user_id: int | None,
    latitude: float,
    longitude: float,
) -> bool:
    if user_id is None:
        return False
    return db.exec(
        select(SavedTrail).where(
            SavedTrail.user_id == user_id,
            SavedTrail.latitude == latitude,
            SavedTrail.longitude == longitude,
        )
    ).first() is not None


def _create_trail_check(db: Session, data: dict, user_id: int | None) -> TrailCheck:
    weather = data.get("weather") or {}
    air_quality = data.get("air_quality") or {}
    trail_check = TrailCheck(
        user_id=user_id,
        query_text=data["query_text"],
        resolved_name=data["resolved_name"],
        latitude=data["latitude"],
        longitude=data["longitude"],
        weather_main=weather["main"],
        weather_description=weather["description"],
        temp_f=weather["temp_f"],
        feels_like_f=weather.get("feels_like_f"),
        humidity=weather.get("humidity"),
        wind_mph=weather.get("wind_mph"),
        visibility_meters=weather.get("visibility_meters"),
        aqi=air_quality.get("aqi"),
        pm2_5=air_quality.get("pm2_5"),
        pm10=air_quality.get("pm10"),
        recommendation=data.get("recommendation", "unknown"),
    )
    db.add(trail_check)
    db.commit()
    db.refresh(trail_check)
    return trail_check


def _render_trail_checker_error(message: str, query_text: str = ""):
    flash(message)
    return render_template("trail_checker.html", query_text=query_text)


@app.route("/trail-checker")
def trail_checker():
    return render_template("trail_checker.html")


@app.route("/trail-checker/results")
def trail_checker_results():
    query_text = _parse_query_text(request.args.get("q", ""))
    if query_text is None:
        return _render_trail_checker_error(
            "Enter a location between 2 and 100 characters.",
            request.args.get("q", "").strip(),
        )

    try:
        data = get_conditions_for_query(query_text)
    except GeocodeNotFoundError:
        return _render_trail_checker_error(
            "Location not found. Try a different search.",
            query_text,
        )
    except ExternalAPIError:
        return _render_trail_checker_error(
            "Weather data was malformed. Try again later.",
            query_text,
        )
    except ExternalAPIUnavailableError:
        return _render_trail_checker_error(
            "External weather service is unavailable. Try again later.",
            query_text,
        )

    db = get_db_session()
    user_id = _current_user_id_or_none()
    is_saved = _is_saved_trail(db, user_id, data["latitude"], data["longitude"])
    _create_trail_check(db, data, user_id)

    return render_template(
        "trail_results.html",
        title=f"Trail Checker — {data['resolved_name']}",
        **_results_context_from_data(data, is_saved=is_saved),
    )


@app.route("/api/conditions")
def api_conditions():
    query_text = _parse_query_text(request.args.get("q", ""))
    if query_text is None:
        return _json_error("invalid_input", "Query must be 2-100 characters.", 400)

    try:
        data = get_conditions_for_query(query_text)
    except GeocodeNotFoundError as exc:
        return _json_error("not_found", str(exc), 404)
    except ExternalAPIError as exc:
        return _json_error("external_api_error", str(exc), 502)
    except ExternalAPIUnavailableError as exc:
        return _json_error("external_api_unavailable", str(exc), 503)

    return jsonify({"ok": True, "data": data})


# ---------------------------------------------------------------------------
# Routes — Saved trails
# ---------------------------------------------------------------------------

@app.route("/saved-trails", methods=["GET"])
@login_required
def saved_trails():
    db = get_db_session()
    trails = db.exec(
        select(SavedTrail)
        .where(SavedTrail.user_id == current_user.id)
        .order_by(SavedTrail.created_at.desc())
    ).all()

    prior_input = session.pop("saved_trail_form", None)
    return render_template(
        "saved_trails.html",
        saved_trails=trails,
        prior_input=prior_input,
    )


@app.route("/saved-trails", methods=["POST"])
@login_required
def create_saved_trail():
    form = request.form

    # Every form field is treated as untrusted input even when it appears to
    # come from our own results page. Validate, do not infer.
    try:
        display_name = validate_text(form.get("display_name"), 2, 100, "display_name")
        query_text = validate_text(form.get("query_text"), 2, 100, "query_text")
        latitude = validate_float(form.get("latitude"), -90, 90, "latitude")
        longitude = validate_float(form.get("longitude"), -180, 180, "longitude")
        country = validate_optional_text(form.get("country"), 10, "country")
        state = validate_optional_text(form.get("state"), 100, "state")
        notes = validate_optional_text(form.get("notes"), 500, "notes")
    except ValueError as error:
        flash(str(error))
        session["saved_trail_form"] = {
            "display_name": form.get("display_name", ""),
            "query_text": form.get("query_text", ""),
            "latitude": form.get("latitude", ""),
            "longitude": form.get("longitude", ""),
            "country": form.get("country", ""),
            "state": form.get("state", ""),
            "notes": form.get("notes", ""),
        }
        return redirect(url_for("saved_trails"))

    db = get_db_session()
    existing = db.exec(
        select(SavedTrail).where(
            SavedTrail.user_id == current_user.id,
            SavedTrail.latitude == latitude,
            SavedTrail.longitude == longitude,
        )
    ).first()

    if existing is not None:
        flash("That trail is already saved.")
        return redirect(url_for("saved_trails"))

    trail = SavedTrail(
        user_id=current_user.id,
        display_name=display_name,
        query_text=query_text,
        latitude=latitude,
        longitude=longitude,
        country=country,
        state=state,
        notes=notes,
    )
    db.add(trail)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        audit(
            "saved_trail.create.duplicate",
            user_id=current_user.id,
            latitude=latitude,
            longitude=longitude,
        )
        flash("That trail is already saved.")
        return redirect(url_for("saved_trails"))

    db.refresh(trail)
    audit(
        "saved_trail.create",
        user_id=current_user.id,
        trail_id=trail.id,
    )
    flash("Trail saved.")
    return redirect(url_for("saved_trails"))


@app.route("/saved-trails/<int:trail_id>/delete", methods=["POST"])
@login_required
def delete_saved_trail(trail_id: int):
    db = get_db_session()
    trail = db.exec(
        select(SavedTrail).where(
            SavedTrail.id == trail_id,
            SavedTrail.user_id == current_user.id,
        )
    ).first()

    # Touch users table the same way every time to keep timing uniform
    # between owner, non-owner, and missing-id cases.
    db.get(User, current_user.id)

    if trail is None:
        audit(
            "saved_trail.delete.denied",
            actor_id=current_user.id,
            target_trail_id=trail_id,
        )
        abort(404)

    db.delete(trail)
    db.commit()
    audit(
        "saved_trail.delete",
        user_id=current_user.id,
        trail_id=trail_id,
    )
    flash("Saved trail deleted.")
    return redirect(url_for("saved_trails"))


@app.route("/saved-trails/<int:trail_id>/check", methods=["GET"])
@login_required
def check_saved_trail(trail_id: int):
    db = get_db_session()
    trail = db.exec(
        select(SavedTrail).where(
            SavedTrail.id == trail_id,
            SavedTrail.user_id == current_user.id,
        )
    ).first()

    db.get(User, current_user.id)

    if trail is None:
        audit(
            "saved_trail.check.denied",
            actor_id=current_user.id,
            target_trail_id=trail_id,
        )
        abort(404)

    try:
        data = get_conditions_for_coordinates(
            trail.query_text,
            trail.display_name,
            trail.latitude,
            trail.longitude,
            country=trail.country,
            state=trail.state,
        )
    except ExternalAPIError:
        flash("Weather data was malformed. Try again later.")
        return redirect(url_for("saved_trails"))
    except ExternalAPIUnavailableError:
        flash("External weather service is unavailable. Try again later.")
        return redirect(url_for("saved_trails"))

    return render_template(
        "trail_results.html",
        title=f"Trail Checker — {trail.display_name}",
        saved_trail=trail,
        **_results_context_from_data(data, is_saved=True),
    )


SQLModel.metadata.create_all(engine)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
