import { useEffect, useState } from 'react';
import { api } from '../api';

function esc(s) {
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}

function fmtUptime(s) {
  if (s == null) return '—';
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
  return `${h}h ${m}m ${sec}s`;
}

export default function Dashboard({ liveFeed, stats, setStats }) {
  const [readers, setReaders] = useState([]);

  const refresh = async () => {
    const r = await api('/api/readers');
    setReaders(r);
    setStats(prev => ({ ...prev, readers: r.length }));
    const u = await api('/api/users');
    setStats(prev => ({ ...prev, users: u.length }));
  };

  useEffect(() => { refresh(); }, []);

  return (
    <div>
      <h4 className="mb-3">Dashboard</h4>

      <div className="row g-3 mb-4">
        <div className="col-6 col-md-3">
          <div className="stat-card"><h6>Readers</h6><div className="value">{stats.readers}</div></div>
        </div>
        <div className="col-6 col-md-3">
          <div className="stat-card"><h6>Users</h6><div className="value">{stats.users}</div></div>
        </div>
        <div className="col-6 col-md-3">
          <div className="stat-card"><h6>MCU TX</h6><div className="value">{stats.tx}</div></div>
        </div>
        <div className="col-6 col-md-3">
          <div className="stat-card"><h6>MCU RX</h6><div className="value">{stats.rx}</div></div>
        </div>
      </div>

      <div className="row g-3 mb-4">
        <div className="col-6 col-md-3">
          <div className="stat-card"><h6>Uptime</h6><div className="value">{fmtUptime(stats.uptime)}</div></div>
        </div>
      </div>

      {/* Reader cards */}
      <div className="row g-3 mb-4">
        {readers.map(r => (
          <div key={r.index} className="col-md-4 col-lg-3">
            <div className="reader-card">
              <div className="d-flex justify-content-between align-items-center mb-2">
                <h6 className="mb-0">Reader {r.index}</h6>
                <span className={`badge ${r.sc ? 'bg-success' : 'bg-secondary'}`}>
                  {r.sc ? 'SC' : 'No SC'}
                </span>
              </div>
              <div className="small">State: <strong className={r.state === 'OFFLINE' ? 'text-danger' : r.state === 'SECURE' ? 'text-success' : ''}>{r.state || 'OFFLINE'}</strong></div>
              <div className="small">
                Addr: {r.addr ?? '?'}{' '}
                <span className={`badge ${r.tamper ? 'bg-danger' : 'bg-success'}`}>
                  {r.tamper ? 'TAMPER' : 'OK'}
                </span>
                {r.power && <span className="badge bg-danger ms-1">POWER</span>}
              </div>
              {r.vendor && (
                <div className="small text-muted">
                  {r.vendor} S/N:{r.serial || ''} FW:{r.firmware || ''}
                </div>
              )}
            </div>
          </div>
        ))}
      </div>

      <h5>Live Event Feed</h5>
      <div className="event-feed border rounded">
        {liveFeed.map((ev, i) => (
          <div key={i} className="ev-row">
            <span className="text-muted">
              {ev.ts ? new Date(ev.ts).toLocaleTimeString() : ''}
            </span>{' '}
            <span className="badge bg-secondary">{ev.type}</span>{' '}
            <span className="text-info">{ev.raw || ''}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
