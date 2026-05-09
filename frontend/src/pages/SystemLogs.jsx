import { useEffect, useState } from 'react';
import { api } from '../api';

export default function SystemLogs() {
  const [logs, setLogs] = useState([]);
  const [level, setLevel] = useState('');

  const load = async () => {
    const url = '/api/system_logs' + (level ? `?level=${level}` : '');
    setLogs(await api(url));
  };

  useEffect(() => { load(); }, [level]);

  const fmtTime = (t) => { try { return new Date(t).toLocaleString(); } catch { return t || ''; } };
  const levelBadge = (l) => ({ info: 'bg-info', debug: 'bg-secondary', warn: 'bg-warning text-dark', error: 'bg-danger' }[l] || 'bg-secondary');

  return (
    <div>
      <h4 className="mb-3"><i className="bi bi-file-earmark-text text-warning"></i> System Logs</h4>
      <div className="mb-2">
        <select className="form-select form-select-sm d-inline-block w-auto" value={level}
          onChange={e => setLevel(e.target.value)}>
          <option value="">All levels</option>
          <option value="info">Info</option>
          <option value="debug">Debug</option>
          <option value="warn">Warning</option>
          <option value="error">Error</option>
        </select>
        <button className="btn btn-sm btn-outline-secondary ms-2" onClick={load}>
          <i className="bi bi-arrow-repeat"></i> Refresh
        </button>
      </div>
      <div className="table-responsive">
        <table className="table table-sm table-hover" style={{ fontSize: '.8rem' }}>
          <thead>
            <tr><th style={{ width: 170 }}>Time</th><th style={{ width: 60 }}>Level</th><th style={{ width: 70 }}>Source</th><th>Message</th></tr>
          </thead>
          <tbody>
            {logs.map((l, i) => (
              <tr key={i}>
                <td>{fmtTime(l.ts)}</td>
                <td><span className={`badge ${levelBadge(l.level)}`}>{l.level}</span></td>
                <td>{l.source || ''}</td>
                <td><code>{l.message || ''}</code></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
