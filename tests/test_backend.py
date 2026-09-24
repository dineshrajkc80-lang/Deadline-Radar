import sqlite3
import uuid

import pytest

from backend.app import app


@pytest.fixture
def client(tmp_path):
    app.config['TESTING'] = True
    app.secret_key = 'test-secret'
    app.config['DATABASE'] = str(tmp_path / 'test.db')

    connection = sqlite3.connect(app.config['DATABASE'])
    connection.execute('CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, email TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP)')
    connection.execute('CREATE TABLE deadlines (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, title TEXT NOT NULL, course TEXT, due_date TEXT NOT NULL, priority TEXT NOT NULL DEFAULT "Medium", notes TEXT, status TEXT NOT NULL DEFAULT "pending", reminder_email TEXT, reminder_sent INTEGER DEFAULT 0, created_at TEXT DEFAULT CURRENT_TIMESTAMP, completed_at TEXT)')
    connection.commit()
    connection.close()

    with app.test_client() as client:
        yield client

    app.config.pop('DATABASE', None)


def test_homepage_loads(client):
    response = client.get('/')
    assert response.status_code == 200
    assert b'Deadline Radar' in response.data


def test_signup_and_login_flow(client):
    email = f'dinesh-{uuid.uuid4().hex[:8]}@example.com'

    signup = client.post('/api/signup', json={
        'name': 'Dinesh',
        'email': email,
        'password': 'secret123'
    })
    assert signup.status_code == 201

    login = client.post('/api/login', json={
        'email': email,
        'password': 'secret123'
    })
    assert login.status_code == 200
    data = login.get_json()
    assert data['email'] == email
    assert data['name'] == 'Dinesh'


def test_deadlines_api_supports_search_and_sort(client):
    email = f'user-{uuid.uuid4().hex[:8]}@example.com'
    client.post('/api/signup', json={
        'name': 'Test User',
        'email': email,
        'password': 'secret123'
    })

    client.post('/api/deadlines', json={
        'title': 'Final Project',
        'course': 'AI',
        'due_date': '2026-10-08',
        'priority': 'High',
        'notes': 'Research paper'
    })
    client.post('/api/deadlines', json={
        'title': 'Math Quiz',
        'course': 'Mathematics',
        'due_date': '2026-10-02',
        'priority': 'Low',
        'notes': 'Solve all problems'
    })

    response = client.get('/api/deadlines?q=math&sort=due_date_asc')
    assert response.status_code == 200
    data = response.get_json()
    assert len(data) == 1
    assert data[0]['title'] == 'Math Quiz'

    response = client.get('/api/deadlines?sort=priority_desc')
    assert response.status_code == 200
    data = response.get_json()
    assert data[0]['priority'] == 'High'


def test_deadline_update_route_updates_task(client):
    email = f'user-{uuid.uuid4().hex[:8]}@example.com'
    client.post('/api/signup', json={
        'name': 'Task User',
        'email': email,
        'password': 'secret123'
    })

    created = client.post('/api/deadlines', json={
        'title': 'Old title',
        'course': 'History',
        'due_date': '2026-10-10',
        'priority': 'Medium',
        'notes': 'Old note'
    })
    deadline_id = created.get_json()['id']

    response = client.put(f'/api/deadlines/{deadline_id}', json={
        'title': 'New title',
        'course': 'Biology',
        'due_date': '2026-10-15',
        'priority': 'High',
        'notes': 'Updated note',
        'reminder_email': 'alerts@example.com'
    })

    assert response.status_code == 200
    data = response.get_json()
    assert data['title'] == 'New title'
    assert data['course'] == 'Biology'
    assert data['priority'] == 'High'
    assert data['notes'] == 'Updated note'
    assert data['reminder_email'] == 'alerts@example.com'


def test_dashboard_works_without_login(client):
    response = client.get('/api/me')
    assert response.status_code == 200
    data = response.get_json()
    assert data['name']

    profile = client.get('/api/profile')
    assert profile.status_code == 200

    response = client.get('/api/deadlines')
    assert response.status_code == 200
    assert isinstance(response.get_json(), list)


def test_duplicate_signup_and_invalid_deadline_are_rejected(client):
    email = f'duplicate-{uuid.uuid4().hex[:8]}@example.com'
    payload = {'name': 'Duplicate User', 'email': email, 'password': 'secret123'}

    assert client.post('/api/signup', json=payload).status_code == 201
    duplicate = client.post('/api/signup', json=payload)
    assert duplicate.status_code == 409

    invalid = client.post('/api/deadlines', json={
        'title': 'Broken date',
        'due_date': 'not-a-date',
    })
    assert invalid.status_code == 400


def test_security_headers_are_added(client):
    response = client.get('/api/health')
    assert response.headers['X-Frame-Options'] == 'DENY'
    assert response.headers['X-Content-Type-Options'] == 'nosniff'
    assert 'frame-ancestors' in response.headers['Content-Security-Policy']
