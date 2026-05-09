import { useEffect, useRef, useState } from 'react';
import { api } from '../api';
import socket from '../socket';

const COMMS_COLORS = {
  card: '#0f0', keypad: '#0f0', debug: '#f80', heartbeat: '#888',
  state: '#0af', pd_status: '#0af', error: '#f33', nak: '#f33',
  boot: '#ff0', config: '#ff0', pong: '#888', ok: '#888',
  lstat: '#0af', istat: '#0af', ostat: '#0af', pdid: '#0af', pdcap: '#0af',
  door: '#f80', sensor: '#f80', relay: '#f80', busy: '#f80', status: '#0af',
};

export default function CommsMonitor({ feed, setFeed, canDebug = true }) {
  const [autoScroll, setAutoScroll] = useState(true);
  const [hbTime, setHbTime] = useState('--');
  const [busTx, setBusTx] = useState(0);
  const [busRx, setBusRx] = useState(0);
  const [uptime, setUptime] = useState('--');
  const feedRef = useRef(null);

  useEffect(() => {
    const onHb = (d) => {
      setHbTime(new Date().toLocaleTimeString());
      setBusTx(d.tx || 0);
      setBusRx(d.rx || 0);
      if (d.uptime != null) {
        const h = Math.floor(d.uptime / 3600), m = Math.floor((d.uptime % 3600) / 60), s = d.uptime % 60;
        setUptime(`${h}h ${m}m ${s}s`);
      }
    };
    socket.on('heartbeat', onHb);
    return () => socket.off('heartbeat', onHb);
  }, []);

  useEffect(() => {
    if (autoScroll && feedRef.current) {
      feedRef.current.scrollTop = feedRef.current.scrollHeight;
    }
  }, [feed, autoScroll]);

  return (
    <div>
      <h4 className="mb-3">
        <i className="bi bi-broadcast-pin text-info"></i> Comms Monitor
        <span className="badge bg-success ms-2 small">LIVE</span>
      </h4>

      <div className="row g-3 mb-3">
        <div className="col-auto">
          <div className="stat-card p-2 px-3"><h6>Heartbeat</h6><span className="small text-success">{hbTime}</span></div>
        </div>
        <div className="col-auto">
          <div className="stat-card p-2 px-3"><h6>Bus TX</h6><span className="value" style={{ fontSize: '1.2rem' }}>{busTx}</span></div>
        </div>
        <div className="col-auto">
          <div className="stat-card p-2 px-3"><h6>Bus RX</h6><span className="value" style={{ fontSize: '1.2rem' }}>{busRx}</span></div>
        </div>
        <div className="col-auto">
          <div className="stat-card p-2 px-3"><h6>Uptime</h6><span className="small">{uptime}</span></div>
        </div>
        <div className="col-auto d-flex align-items-end">
          <div className="form-check form-switch">
            <input className="form-check-input" type="checkbox" checked={autoScroll}
              onChange={e => setAutoScroll(e.target.checked)} id="autoScrollChk" />
            <label className="form-check-label small" htmlFor="autoScrollChk">Auto-scroll</label>
          </div>
        </div>
        <div className="col-auto d-flex align-items-end gap-1">
          <button className="btn btn-sm btn-outline-secondary" onClick={() => setFeed([])}>
            <i className="bi bi-trash"></i> Clear
          </button>
          {canDebug && (
            <>
              <button className="btn btn-sm btn-outline-info" onClick={() => api('/api/cmd/debug', 'POST', { on: true })}>
                <i className="bi bi-bug"></i> Debug ON
              </button>
              <button className="btn btn-sm btn-outline-secondary" onClick={() => api('/api/cmd/debug', 'POST', { on: false })}>
                Debug OFF
              </button>
            </>
          )}
        </div>
      </div>

      <div className="event-feed border rounded" ref={feedRef} style={{ height: '500px', fontSize: '0.75rem' }}>
        {feed.map((ev, i) => {
          const ts = ev.ts ? new Date(ev.ts).toLocaleTimeString('en-US', {
            hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit', fractionalSecondDigits: 3,
          }) : '';
          const color = COMMS_COLORS[ev.type] || '#c9d1d9';
          return (
            <div key={i} className="ev-row">
              <span className="text-muted">{ts}</span>{' '}
              <span className="badge" style={{ background: color, color: '#000', fontSize: '.65rem' }}>{ev.type}</span>{' '}
              <span style={{ color }}>{ev.raw || ''}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
