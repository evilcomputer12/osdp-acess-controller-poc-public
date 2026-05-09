import { useEffect, useState } from 'react';
import { api } from '../api';

export default function AccessLog() {
  const [logs, setLogs] = useState([]);

  const load = async () => setLogs(await api('/api/access_log'));
  useEffect(() => { load(); }, []);

  const fmtTime = (t) => { try { return new Date(t).toLocaleString(); } catch { return t || ''; } };

  return (
    <div>
      <h4 className="mb-3">Access Log</h4>
      <button className="btn btn-sm btn-outline-secondary mb-2" onClick={load}>
        <i className="bi bi-arrow-repeat"></i> Refresh
      </button>
      <div className="table-responsive">
        <table className="table table-sm table-hover">
          <thead>
            <tr><th>Time</th><th>User</th><th>Method</th><th>Card/PIN</th><th>Reader</th><th>Granted</th><th>Reason</th></tr>
          </thead>
          <tbody>
            {logs.map((l, i) => (
              <tr key={i}>
                <td>{fmtTime(l.ts)}</td>
                <td>{l.username || '—'}</td>
                <td>{l.method || '—'}</td>
                <td><code>{l.card_hex || l.pin_hex || ''}</code></td>
                <td>{l.reader ?? ''}</td>
                <td>
                  <span className={`badge ${l.granted ? 'bg-success' : 'bg-danger'}`}>
                    {l.granted ? 'YES' : 'NO'}
                  </span>
                </td>
                <td>{l.reason || ''}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
