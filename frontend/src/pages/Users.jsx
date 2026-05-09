import { useEffect, useState } from 'react';
import { api } from '../api';

export default function Users() {
  const [users, setUsers] = useState([]);
  const [panelUsers, setPanelUsers] = useState([]);
  const [creds, setCreds] = useState({});
  const [schedules, setSchedules] = useState([]);
  const [editing, setEditing] = useState(null); // null or user obj
  const [form, setForm] = useState({ username: '', full_name: '', role: 'user', schedule: '24/7', allowed_readers: '' });
  const [showModal, setShowModal] = useState(false);
  const [passwordState, setPasswordState] = useState({ username: '', password: '', confirm: '' });
  const [showPasswordModal, setShowPasswordModal] = useState(false);

  const load = async () => {
    const u = await api('/api/users');
    setUsers(u);
    const panel = await api('/api/panel_users');
    setPanelUsers(Array.isArray(panel) ? panel : []);
    const allCreds = await api('/api/credentials');
    const map = {};
    allCreds.forEach(c => {
      if (!map[c.user_id]) map[c.user_id] = { cards: 0, pins: 0 };
      if (c.type === 'card') map[c.user_id].cards++;
      else map[c.user_id].pins++;
    });
    setCreds(map);
    setSchedules(await api('/api/schedules'));
  };

  useEffect(() => { load(); }, []);

  const openCreate = () => {
    setEditing(null);
    setForm({ username: '', full_name: '', role: 'user', schedule: '24/7', allowed_readers: '' });
    setShowModal(true);
  };

  const openEdit = (u) => {
    setEditing(u);
    setForm({
      username: u.username,
      full_name: u.full_name || '',
      role: u.role,
      schedule: u.schedule || '24/7',
      allowed_readers: (u.allowed_readers || []).join(', '),
    });
    setShowModal(true);
  };

  const save = async () => {
    if (editing) {
      await api(`/api/users/${editing.id}`, 'PUT', form);
    } else {
      const r = await api('/api/users', 'POST', form);
      if (!r.ok) { alert(r.error || 'Error'); return; }
    }
    setShowModal(false);
    load();
  };

  const del = async (id) => {
    if (!confirm('Deactivate this user?')) return;
    await api(`/api/users/${id}`, 'DELETE');
    load();
  };

  const openPasswordModal = (panelUser) => {
    setPasswordState({ username: panelUser.username, password: '', confirm: '' });
    setShowPasswordModal(true);
  };

  const savePassword = async () => {
    if (!passwordState.password || passwordState.password.length < 3) {
      alert('Password must be at least 3 characters.');
      return;
    }
    if (passwordState.password !== passwordState.confirm) {
      alert('Passwords do not match.');
      return;
    }
    const result = await api(`/api/panel_users/${encodeURIComponent(passwordState.username)}/password`, 'PUT', {
      password: passwordState.password,
    });
    if (!result.ok) {
      alert(result.error || 'Could not update panel password.');
      return;
    }
    const changedUser = passwordState.username;
    setShowPasswordModal(false);
    setPasswordState({ username: '', password: '', confirm: '' });
    alert(`Password updated for ${changedUser}.`);
    load();
  };

  const resetPassword = async (panelUser) => {
    if (!panelUser.can_reset_password) {
      alert('No seeded default password is configured for this panel account.');
      return;
    }
    if (!confirm(`Reset the password for ${panelUser.username} back to its default value?`)) {
      return;
    }
    const result = await api(`/api/panel_users/${encodeURIComponent(panelUser.username)}/password/reset`, 'POST');
    if (!result.ok) {
      alert(result.error || 'Could not reset the panel password.');
      return;
    }
    alert(`Password reset for ${panelUser.username}.`);
    load();
  };

  return (
    <div>
      <h4 className="mb-3">Users &amp; Access Rights</h4>
      <button className="btn btn-sm btn-primary mb-3" onClick={openCreate}>
        <i className="bi bi-person-plus"></i> New User
      </button>

      <div className="card mb-4">
        <div className="card-body">
          <h5 className="card-title mb-1">Panel Login Accounts</h5>
          <p className="text-muted small mb-3">These are the web-panel accounts used to sign in to the admin UI.</p>

          <div className="table-responsive">
            <table className="table table-sm table-hover mb-0">
              <thead>
                <tr><th>Username</th><th>Display Name</th><th>Role</th><th>Status</th><th>Actions</th></tr>
              </thead>
              <tbody>
                {panelUsers.map(panelUser => (
                  <tr key={panelUser.username}>
                    <td>{panelUser.username}</td>
                    <td>{panelUser.display_name || panelUser.username}</td>
                    <td>
                      <span className={`badge ${panelUser.role === 'admin' ? 'bg-warning text-dark' : 'bg-info text-dark'}`}>
                        {panelUser.role}
                      </span>
                    </td>
                    <td>{panelUser.active ? 'Active' : 'Disabled'}</td>
                    <td>
                      <div className="btn-group btn-group-sm" role="group">
                        <button className="btn btn-outline-warning" onClick={() => openPasswordModal(panelUser)}>
                          <i className="bi bi-key"></i> Change Password
                        </button>
                        <button
                          className="btn btn-outline-secondary"
                          onClick={() => resetPassword(panelUser)}
                          disabled={!panelUser.can_reset_password}
                        >
                          <i className="bi bi-arrow-counterclockwise"></i> Reset to Default
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <div className="table-responsive">
        <table className="table table-sm table-hover">
          <thead>
            <tr><th>Username</th><th>Full Name</th><th>Role</th><th>Schedule</th><th>Readers</th><th>Cards</th><th>PINs</th><th>Actions</th></tr>
          </thead>
          <tbody>
            {users.map(u => (
              <tr key={u.id}>
                <td>{u.username}</td>
                <td>{u.full_name || ''}</td>
                <td>
                  <span className={`badge ${u.role === 'admin' ? 'bg-warning' : u.role === 'guard' ? 'bg-info' : 'bg-secondary'}`}>
                    {u.role}
                  </span>
                </td>
                <td>{u.schedule || '24/7'}</td>
                <td>{u.allowed_readers?.length ? u.allowed_readers.join(', ') : 'All'}</td>
                <td>{creds[u.id]?.cards || 0}</td>
                <td>{creds[u.id]?.pins || 0}</td>
                <td>
                  <button className="btn btn-sm btn-outline-info me-1" onClick={() => openEdit(u)}>
                    <i className="bi bi-pencil"></i>
                  </button>
                  <button className="btn btn-sm btn-outline-danger" onClick={() => del(u.id)}>
                    <i className="bi bi-trash"></i>
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Modal */}
      {showModal && (
        <div className="modal show d-block" tabIndex="-1" style={{ background: 'rgba(0,0,0,.5)' }}>
          <div className="modal-dialog">
            <div className="modal-content">
              <div className="modal-header">
                <h5 className="modal-title">{editing ? 'Edit User' : 'New User'}</h5>
                <button type="button" className="btn-close" onClick={() => setShowModal(false)}></button>
              </div>
              <div className="modal-body">
                <div className="mb-2">
                  <label className="form-label small">Username</label>
                  <input className="form-control form-control-sm" value={form.username}
                    onChange={e => setForm({ ...form, username: e.target.value })} />
                </div>
                <div className="mb-2">
                  <label className="form-label small">Full Name</label>
                  <input className="form-control form-control-sm" value={form.full_name}
                    onChange={e => setForm({ ...form, full_name: e.target.value })} />
                </div>
                <div className="mb-2">
                  <label className="form-label small">Role</label>
                  <select className="form-select form-select-sm" value={form.role}
                    onChange={e => setForm({ ...form, role: e.target.value })}>
                    <option value="user">User</option>
                    <option value="admin">Admin</option>
                    <option value="guard">Guard</option>
                  </select>
                </div>
                <div className="mb-2">
                  <label className="form-label small">Schedule</label>
                  <select className="form-select form-select-sm" value={form.schedule}
                    onChange={e => setForm({ ...form, schedule: e.target.value })}>
                    {schedules.map(s => <option key={s.name} value={s.name}>{s.name}</option>)}
                  </select>
                </div>
                <div className="mb-2">
                  <label className="form-label small">Allowed Readers (comma-separated, blank = all)</label>
                  <input className="form-control form-control-sm" value={form.allowed_readers}
                    onChange={e => setForm({ ...form, allowed_readers: e.target.value })} placeholder="e.g. 0,1,2" />
                </div>
              </div>
              <div className="modal-footer">
                <button className="btn btn-primary btn-sm" onClick={save}>
                  {editing ? 'Save' : 'Create'}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {showPasswordModal && (
        <div className="modal show d-block" tabIndex="-1" style={{ background: 'rgba(0,0,0,.5)' }}>
          <div className="modal-dialog">
            <div className="modal-content">
              <div className="modal-header">
                <h5 className="modal-title">Change Panel Password</h5>
                <button type="button" className="btn-close" onClick={() => setShowPasswordModal(false)}></button>
              </div>
              <div className="modal-body">
                <div className="mb-2">
                  <label className="form-label small">Panel Username</label>
                  <input className="form-control form-control-sm" value={passwordState.username} disabled />
                </div>
                <div className="mb-2">
                  <label className="form-label small">New Password</label>
                  <input
                    type="password"
                    className="form-control form-control-sm"
                    value={passwordState.password}
                    onChange={e => setPasswordState({ ...passwordState, password: e.target.value })}
                  />
                </div>
                <div className="mb-2">
                  <label className="form-label small">Confirm Password</label>
                  <input
                    type="password"
                    className="form-control form-control-sm"
                    value={passwordState.confirm}
                    onChange={e => setPasswordState({ ...passwordState, confirm: e.target.value })}
                  />
                </div>
              </div>
              <div className="modal-footer">
                <button className="btn btn-secondary btn-sm" onClick={() => setShowPasswordModal(false)}>
                  Cancel
                </button>
                <button className="btn btn-warning btn-sm" onClick={savePassword}>
                  Save Password
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
