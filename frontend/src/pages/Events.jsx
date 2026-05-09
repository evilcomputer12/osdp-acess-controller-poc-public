import { useEffect, useState } from 'react';
import { api } from '../api';

export default function Events() {
  const [events, setEvents] = useState([]);
  const [typeFilter, setTypeFilter] = useState('');

  const load = async () => {
    const url = '/api/events' + (typeFilter ? `?type=${typeFilter}` : '');
    setEvents(await api(url));
  };

  useEffect(() => { load(); }, [typeFilter]);

  const fmtTime = (t) => { try { return new Date(t).toLocaleString(); } catch { return t || ''; } };

  return (
    <div>
      <h4 className="mb-3">Events Log</h4>
      <div className="mb-2">
        <select className="form-select form-select-sm d-inline-block w-auto" value={typeFilter}
          onChange={e => setTypeFilter(e.target.value)}>
          <option value="">All types</option>
          {['card', 'keypad', 'state', 'lstat', 'door', 'sensor', 'nak', 'error'].map(t =>
            <option key={t} value={t}>{t.charAt(0).toUpperCase() + t.slice(1)}</option>
          )}
        </select>
        <button className="btn btn-sm btn-outline-secondary ms-2" onClick={load}>
          <i className="bi bi-arrow-repeat"></i>
        </button>
      </div>
      <div className="table-responsive">
        <table className="table table-sm table-hover">
          <thead><tr><th>Time</th><th>Type</th><th>Reader</th><th>Details</th></tr></thead>
          <tbody>
            {events.map((ev, i) => (
              <tr key={i}>
                <td>{fmtTime(ev.ts)}</td>
                <td><span className="badge bg-secondary">{ev.type}</span></td>
                <td>{ev.reader ?? ev.index ?? ''}</td>
                <td><code>{ev.raw || ''}</code></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
