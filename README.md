# Deadline Radar

Deadline Radar is a polished student productivity dashboard for managing assignments, exams, deadlines, and reminder alerts in a clean glassmorphism interface.

Created by Dineshraj K C.

## Highlights

- Glassmorphism dashboard UI with dark/light theme support
- Deadline tracking with add, edit, complete, and delete actions
- Smart filters, search, and sorting
- Reminder panel with browser notifications
- CSV and PDF export support
- SQLite persistence and secure server-side defaults
- Guest-first workflow with no forced login screen

## Project structure

- index.html — dashboard entry point
- css/style.css — glassmorphism styling and responsive layout
- js/script.js — frontend logic for filtering, updates, reminders, exports, and modal actions
- backend/app.py — Flask API and persistence layer
- tests/test_backend.py — regression and validation checks
- database/ — SQLite database storage

## Run locally

1. Open a terminal in the project folder.
2. Install dependencies:
   python -m pip install -r requirements.txt
3. Start the app:
   python -m flask --app backend.app run --host 0.0.0.0 --port 5000
4. Open the browser at:
   http://127.0.0.1:5000

## Security notes

- Default app secret is generated securely from the environment or a runtime token.
- Security headers are added for X-Frame-Options, content type sniffing protection, and CSP.
- Guest data flow is kept isolated by user-specific SQLite queries.
- Input validation is enforced for titles, due dates, and reminder data.

## Testing

Run:

python -m pytest tests/test_backend.py

## License

This project is licensed under the MIT License. See the LICENSE file for details.
