const state = {
  currentFilter: 'all',
  currentSearch: '',
  currentSort: 'due_date_asc',
  user: {
    name: 'Guest User',
    email: 'guest@deadline-radar.local',
  },
};

const themeToggle = document.getElementById('theme-toggle');
const deadlineListEl = document.getElementById('deadline-list');
const reminderListEl = document.getElementById('reminder-list');
const formEl = document.getElementById('deadline-form');
const refreshBtn = document.getElementById('refresh-btn');
const exportCsvBtn = document.getElementById('export-csv');
const exportPdfBtn = document.getElementById('export-pdf');
const filterButtons = document.querySelectorAll('.filter-button');
const searchInput = document.getElementById('search-input');
const sortSelect = document.getElementById('sort-select');
const profileNameEl = document.getElementById('profile-name');
const profileEmailEl = document.getElementById('profile-email');
const profileTotalEl = document.getElementById('profile-total');
const profilePendingEl = document.getElementById('profile-pending');
const profileModal = document.getElementById('profile-modal');
const profileForm = document.getElementById('profile-form');
const editModal = document.getElementById('edit-modal');
const editDeadlineForm = document.getElementById('edit-deadline-form');

const summaryEls = {
  pending: document.getElementById('pending-count'),
  urgent: document.getElementById('urgent-count'),
  completed: document.getElementById('completed-count'),
  total: document.getElementById('total-count'),
};

function applyTheme(theme) {
  document.body.setAttribute('data-theme', theme);
  localStorage.setItem('deadline-radar-theme', theme);
  const themeLabel = theme === 'dark' ? 'Light' : 'Dark';
  themeToggle.querySelector('.button-label').textContent = themeLabel;
  themeToggle.querySelector('.button-icon').textContent = theme === 'dark' ? '☼' : '◐';
}

function formatDate(dateString) {
  if (!dateString) return 'No date';
  const date = new Date(`${dateString}T00:00:00`);
  return date.toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  });
}

function getDaysLabel(daysLeft) {
  if (daysLeft === null || daysLeft === undefined) return 'No due date';
  if (daysLeft < 0) return `${Math.abs(daysLeft)} day(s) overdue`;
  if (daysLeft === 0) return 'Due today';
  if (daysLeft === 1) return 'Due tomorrow';
  return `${daysLeft} day(s) left`;
}

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>'"]/g, (character) => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    "'": '&#39;',
    '"': '&quot;',
  })[character]);
}

function createBadge(text, type) {
  const normalized = (text || '').toLowerCase();
  return `<span class="${type}-badge ${escapeHtml(normalized)}">${escapeHtml(text)}</span>`;
}

function renderDeadline(deadline) {
  const isCompleted = deadline.status === 'completed';
  const noteText = deadline.notes ? deadline.notes : 'No additional notes for this task.';

  return `
    <article class="deadline-card ${isCompleted ? 'completed' : ''}">
      <div class="deadline-top">
        <div>
          <h3 class="deadline-title">${escapeHtml(deadline.title)}</h3>
          <p class="deadline-meta">${escapeHtml(deadline.course || 'General')} • ${escapeHtml(formatDate(deadline.due_date))}</p>
        </div>
        <div>
          ${createBadge(deadline.priority, 'priority')}
        </div>
      </div>

      <p class="deadline-notes">${escapeHtml(noteText)}</p>

      <div class="deadline-actions">
        <div>
          ${createBadge(deadline.status, 'status')}
          <span class="days-left">${getDaysLabel(deadline.days_left)}</span>
        </div>

        <div class="action-group">
          <button class="action-button toggle-deadline" data-id="${deadline.id}" type="button">
            ${isCompleted ? 'Mark pending' : 'Mark complete'}
          </button>
          <button class="action-button edit-deadline" data-id="${deadline.id}" type="button">Edit</button>
          <button class="delete-button delete-deadline" data-id="${deadline.id}" type="button">Delete</button>
        </div>
      </div>
    </article>
  `;
}

function renderReminder(reminder) {
  return `
    <div class="reminder-item">
      <span>${escapeHtml(reminder.title)} • ${escapeHtml(getDaysLabel(reminder.days_left))}</span>
      <button class="send-reminder" data-id="${Number(reminder.id)}" type="button">${reminder.reminder_sent ? 'Sent' : 'Send'}</button>
    </div>
  `;
}

function requestNotificationPermission() {
  if (!('Notification' in window)) {
    return Promise.resolve('unsupported');
  }

  if (Notification.permission === 'granted') {
    return Promise.resolve('granted');
  }

  if (Notification.permission === 'denied') {
    return Promise.resolve('denied');
  }

  return Notification.requestPermission();
}

function showBrowserNotification(title, body) {
  if (!('Notification' in window)) {
    return;
  }

  if (Notification.permission === 'granted') {
    new Notification(title, { body });
  }
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });

  const data = await response.json().catch(() => ({}));

  if (!response.ok) {
    throw new Error(data.error || 'Something went wrong.');
  }

  return data;
}

async function updateSummary() {
  const summary = await fetchJson('/api/summary');
  summaryEls.pending.textContent = summary.pending;
  summaryEls.urgent.textContent = summary.urgent;
  summaryEls.completed.textContent = summary.completed;
  summaryEls.total.textContent = summary.total;
}

async function updateReminders() {
  try {
    const reminders = await fetchJson('/api/reminders');
    if (!reminders.length) {
      reminderListEl.innerHTML = '<p class="empty-state">No reminders due in the next 7 days.</p>';
      return;
    }

    reminderListEl.innerHTML = reminders.map(renderReminder).join('');

    if ('Notification' in window && Notification.permission === 'granted') {
      showBrowserNotification('Deadline Radar', `${reminders.length} deadline(s) are due soon.`);
    }
  } catch (error) {
    reminderListEl.innerHTML = `<p class="empty-state">${escapeHtml(error.message)}</p>`;
  }
}

async function loadDeadlines() {
  try {
    const query = new URLSearchParams({
      status: state.currentFilter,
      q: state.currentSearch,
      sort: state.currentSort,
    });

    const deadlines = await fetchJson(`/api/deadlines?${query.toString()}`);

    if (!deadlines.length) {
      deadlineListEl.innerHTML = '<p class="empty-state">No deadlines available for this filter.</p>';
      return;
    }

    deadlineListEl.innerHTML = deadlines.map(renderDeadline).join('');
  } catch (error) {
    deadlineListEl.innerHTML = `<p class="empty-state">${escapeHtml(error.message)}</p>`;
  }
}

async function handleSubmit(event) {
  event.preventDefault();

  const formData = new FormData(formEl);
  const payload = {
    title: String(formData.get('title') || '').trim(),
    course: String(formData.get('course') || '').trim(),
    due_date: formData.get('due_date'),
    priority: formData.get('priority'),
    reminder_email: String(formData.get('reminder_email') || '').trim(),
    notes: String(formData.get('notes') || '').trim(),
  };

  try {
    await fetchJson('/api/deadlines', {
      method: 'POST',
      body: JSON.stringify(payload),
    });

    formEl.reset();
    document.getElementById('priority').value = 'Medium';
    await updateSummary();
    await updateReminders();
    await loadDeadlines();
  } catch (error) {
    alert(error.message);
  }
}

async function handleDeadlineAction(event) {
  const toggleBtn = event.target.closest('.toggle-deadline');
  const deleteBtn = event.target.closest('.delete-deadline');
  const reminderBtn = event.target.closest('.send-reminder');
  const editBtn = event.target.closest('.edit-deadline');

  if (!toggleBtn && !deleteBtn && !reminderBtn && !editBtn) return;

  const target = event.target.closest('[data-id]');
  const id = Number(target?.dataset?.id);

  try {
    if (toggleBtn) {
      await fetchJson(`/api/deadlines/${id}/toggle`, { method: 'PATCH' });
    }

    if (deleteBtn) {
      await fetchJson(`/api/deadlines/${id}`, { method: 'DELETE' });
    }

    if (reminderBtn) {
      const result = await fetchJson(`/api/reminders/send/${id}`, { method: 'POST' });
      showBrowserNotification('Reminder sent', `${result.recipient} received a reminder.`);
    }

    if (editBtn) {
      const task = (await fetchJson('/api/deadlines?status=all')).find((item) => item.id === id);
      if (!task) {
        throw new Error('Task not found.');
      }

      document.getElementById('edit-deadline-id').value = task.id;
      document.getElementById('edit-title').value = task.title;
      document.getElementById('edit-course').value = task.course || '';
      document.getElementById('edit-due_date').value = task.due_date;
      document.getElementById('edit-priority').value = task.priority;
      document.getElementById('edit-reminder_email').value = task.reminder_email || '';
      document.getElementById('edit-notes').value = task.notes || '';
      editModal.classList.remove('hidden');
      editModal.setAttribute('aria-hidden', 'false');
      return;
    }

    await updateSummary();
    await updateReminders();
    await loadDeadlines();
  } catch (error) {
    alert(error.message);
  }
}

function bindFilters() {
  filterButtons.forEach((button) => {
    button.addEventListener('click', () => {
      state.currentFilter = button.dataset.filter;
      filterButtons.forEach((item) => item.classList.toggle('active', item === button));
      loadDeadlines();
    });
  });

  searchInput.addEventListener('input', (event) => {
    state.currentSearch = event.target.value.trim();
    loadDeadlines();
  });

  sortSelect.addEventListener('change', (event) => {
    state.currentSort = event.target.value;
    loadDeadlines();
  });
}

function openProfileModal() {
  profileForm.querySelector('[name="name"]').value = state.user?.name || 'Guest User';
  profileForm.querySelector('[name="email"]').value = state.user?.email || 'guest@deadline-radar.local';
  profileForm.querySelector('[name="password"]').value = '';
  profileModal.classList.remove('hidden');
  profileModal.setAttribute('aria-hidden', 'false');
}

function closeModal(modal) {
  modal.classList.add('hidden');
  modal.setAttribute('aria-hidden', 'true');
}

async function exportCsv() {
  const deadlines = await fetchJson(`/api/deadlines?status=${state.currentFilter}&q=${encodeURIComponent(state.currentSearch)}&sort=${encodeURIComponent(state.currentSort)}`);
  const header = ['id', 'title', 'course', 'due_date', 'priority', 'notes', 'status'];
  const rows = deadlines.map((d) => [d.id, d.title, d.course, d.due_date, d.priority, d.notes, d.status]);
  const csv = [header, ...rows].map((row) => row.map((cell) => `"${String(cell ?? '').replace(/"/g, '""')}"`).join(',')).join('\n');

  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = 'deadline-radar.csv';
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

async function exportPdf() {
  const { jsPDF } = window.jspdf || {};
  if (!jsPDF) {
    alert('PDF export is unavailable right now.');
    return;
  }

  const deadlines = await fetchJson(`/api/deadlines?status=${state.currentFilter}&q=${encodeURIComponent(state.currentSearch)}&sort=${encodeURIComponent(state.currentSort)}`);
  const doc = new jsPDF();
  doc.setFontSize(18);
  doc.text('Deadline Radar', 14, 18);
  let y = 32;

  deadlines.forEach((deadline, index) => {
    if (y > 250) {
      doc.addPage();
      y = 20;
    }

    doc.setFontSize(12);
    doc.text(`${index + 1}. ${deadline.title}`, 14, y);
    y += 8;
    doc.text(`Course: ${deadline.course || 'General'} | Priority: ${deadline.priority} | Due: ${deadline.due_date}`, 14, y);
    y += 8;
    doc.text(`Status: ${deadline.status} | Notes: ${deadline.notes || 'N/A'}`, 14, y);
    y += 12;
  });

  if (deadlines.length === 0) {
    doc.text('No deadlines to export.', 14, 32);
  }

  doc.save('deadline-radar.pdf');
}

async function loadUser() {
  try {
    const user = await fetchJson('/api/me');
    const profile = await fetchJson('/api/profile');
    state.user = user;
    profileNameEl.textContent = profile.name;
    profileEmailEl.textContent = profile.email;
    profileTotalEl.textContent = profile.total_deadlines;
    profilePendingEl.textContent = profile.pending_deadlines;
    await requestNotificationPermission();
    await updateSummary();
    await updateReminders();
    await loadDeadlines();
  } catch (error) {
    state.user = {
      name: 'Guest User',
      email: 'guest@deadline-radar.local',
    };
    profileNameEl.textContent = state.user.name;
    profileEmailEl.textContent = state.user.email;
    profileTotalEl.textContent = '0';
    profilePendingEl.textContent = '0';
    await updateSummary();
    await updateReminders();
    await loadDeadlines();
  }
}

async function init() {
  const savedTheme = localStorage.getItem('deadline-radar-theme') || 'dark';
  applyTheme(savedTheme);

  themeToggle.addEventListener('click', () => {
    const nextTheme = document.body.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
    applyTheme(nextTheme);
  });

  formEl.addEventListener('submit', handleSubmit);
  deadlineListEl.addEventListener('click', handleDeadlineAction);
  reminderListEl.addEventListener('click', handleDeadlineAction);
  refreshBtn.addEventListener('click', async () => {
    await updateSummary();
    await updateReminders();
    await loadDeadlines();
  });
  exportCsvBtn.addEventListener('click', exportCsv);
  exportPdfBtn.addEventListener('click', exportPdf);
  document.getElementById('open-profile-modal').addEventListener('click', openProfileModal);

  document.querySelectorAll('.close-modal').forEach((button) => {
    button.addEventListener('click', () => closeModal(document.getElementById(button.dataset.close)));
  });

  profileForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    const payload = Object.fromEntries(new FormData(profileForm));
    try {
      await fetchJson('/api/profile', {
        method: 'PUT',
        body: JSON.stringify(payload),
      });
      closeModal(profileModal);
      await loadUser();
    } catch (error) {
      alert(error.message);
    }
  });

  editDeadlineForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    const id = document.getElementById('edit-deadline-id').value;
    const payload = Object.fromEntries(new FormData(editDeadlineForm));
    try {
      await fetchJson(`/api/deadlines/${id}`, {
        method: 'PUT',
        body: JSON.stringify(payload),
      });
      closeModal(editModal);
      await updateSummary();
      await updateReminders();
      await loadDeadlines();
    } catch (error) {
      alert(error.message);
    }
  });

  bindFilters();
  await loadUser();
}

document.addEventListener('DOMContentLoaded', init);
