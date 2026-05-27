"""
Week 6 client-side contract tests for Trail Checker.

Owner: Liam Sipp - Client-side

These tests intentionally describe the Trail Checker templates before the
implementation exists. They should fail at first, then pass when the
client-side templates and routes are implemented.
"""

import os

# These must be set BEFORE importing app.py.
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["SECRET_KEY"] = "test-secret"
os.environ["OPENWEATHER_API_KEY"] = "fake-test-key"

import pytest
import responses
from sqlmodel import SQLModel
from app import app, engine


@pytest.fixture
def client():
    app.config["TESTING"] = True

    SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)

    with app.test_client() as client:
        yield client


def test_trail_checker_page_has_search_form(client):
    """The Trail Checker page exposes the agreed search form."""
    response = client.get("/trail-checker")

    assert response.status_code == 200
    assert b'action="/trail-checker/results"' in response.data
    assert b'method="GET"' in response.data or b"method='GET'" in response.data
    assert b'name="q"' in response.data
    assert b'type="submit"' in response.data


def test_base_nav_links_to_trail_checker(client):
    """The shared navbar includes a link to the Trail Checker page."""
    response = client.get("/")

    assert response.status_code == 200
    assert b'href="/trail-checker"' in response.data


@responses.activate
def test_results_page_has_stable_result_sections(client):
    """The results page includes stable selectors for client-side layout tests."""
    responses.add(
        responses.GET,
        "http://api.openweathermap.org/geo/1.0/direct",
        json=[
            {
                "name": "Mount Rainier",
                "lat": 46.8523,
                "lon": -121.7603,
                "country": "US",
                "state": "Washington",
            }
        ],
        status=200,
    )

    responses.add(
        responses.GET,
        "https://api.openweathermap.org/data/2.5/weather",
        json={
            "name": "Mount Rainier",
            "weather": [{"main": "Clouds", "description": "overcast clouds"}],
            "main": {"temp": 48.2, "feels_like": 45.1, "humidity": 72},
            "wind": {"speed": 8.3},
            "visibility": 10000,
        },
        status=200,
    )

    responses.add(
        responses.GET,
        "http://api.openweathermap.org/data/2.5/air_pollution",
        json={
            "list": [
                {
                    "main": {"aqi": 2},
                    "components": {"pm2_5": 4.2, "pm10": 7.5},
                }
            ]
        },
        status=200,
    )

    response = client.get("/trail-checker/results?q=Mount%20Rainier")

    assert response.status_code == 200
    assert b'data-testid="weather-card"' in response.data
    assert b'data-testid="air-quality-card"' in response.data
    assert b'data-testid="recommendation-badge"' in response.data


def test_saved_trails_page_has_empty_state(client):
    """Saved trails page includes an empty-state container."""
    response = client.get("/saved-trails")

    assert response.status_code in (200, 302)

    if response.status_code == 200:
        assert b'data-testid="saved-trails-empty"' in response.data

def test_login_page_has_github_button_and_remember_checkbox(client):
    """Week 7 login page keeps password login and adds GitHub + remember UI."""
    response = client.get("/login")

    assert response.status_code == 200
    assert b"Sign in with GitHub" in response.data
    assert b'href="/login/github"' in response.data
    assert b'name="username"' in response.data
    assert b'name="password"' in response.data
    assert b'name="remember"' in response.data
    assert b'id="remember"' in response.data
    assert b"Remember me" in response.data


def test_logged_in_navbar_uses_week7_contract_text_and_logout_button(client):
    """Authenticated navbar exposes stable text for Week 7 Playwright assertions."""
    client.post(
        "/register",
        data={"username": "LiamCase", "password": "password123"},
    )

    response = client.get("/")

    assert response.status_code == 200
    assert b"Logged in as LiamCase" in response.data
    assert b'action="/logout"' in response.data
    assert b'method="POST"' in response.data
    assert b"Logout" in response.data
