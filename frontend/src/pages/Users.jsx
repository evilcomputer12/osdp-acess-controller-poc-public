import { useEffect, useState } from 'react';
import { api } from '../api';

export default function Users() {
  const [users, setUsers] = useState([]);
  const [creds, setCreds] = useState({});
  const [schedules, setSchedules] = useState([]);
  const [editing, setEditing] = useState(null); // null or user obj
  const [form, setForm] = useState({ username: '', full_name: '', role: 'user', schedule: '24/7', allowed_readers: '' });
  const [showModal, setShowModal] = useState(false);

  const load = async () => {
    const u = await api('/api/users');
    setUsers(u);
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

  return (
    <div>
      <h4 className="mb-3">Users &amp; Access Rights</h4>
      <button className="btn btn-sm btn-primary mb-3" onClick={openCreate}>
        <i className="bi bi-person-plus"></i> New User
      </button>

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
    </div>
  );
}
