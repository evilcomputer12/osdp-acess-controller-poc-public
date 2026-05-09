import { useState, useEffect, useCallback, useRef } from 'react';
import socket from './socket';
import { api } from './api';
import Dashboard from './pages/Dashboard';
import Readers from './pages/Readers';
import Users from './pages/Users';
import Enrollment from './pages/Enrollment';
import Schedules from './pages/Schedules';
import Events from './pages/Events';
import AccessLog from './pages/AccessLog';
import ReaderConfig from './pages/ReaderConfig';
import CommsMonitor from './pages/CommsMonitor';
import SystemLogs from './pages/SystemLogs';
import Terminal from './pages/Terminal';
import FirmwareUpdate from './pages/FirmwareUpdate';

const NAV = [
  { id: 'dashboard',   icon: 'bi-speedometer2',        label: 'Dashboard' },
  { id: 'readers',     icon: 'bi-cpu',                  label: 'Readers' },
  { id: 'users',       icon: 'bi-people',               label: 'Users' },
  { id: 'enrollment',  icon: 'bi-person-badge',         label: 'Enrollment' },
  { id: 'schedules',   icon: 'bi-clock-history',        label: 'Schedules' },
  { id: 'events',      icon: 'bi-journal-text',         label: 'Events' },
  { id: 'access-log',  icon: 'bi-door-open',            label: 'Access Log' },
  { id: 'config',      icon: 'bi-gear',                 label: 'Reader Config' },
  { id: 'comms',       icon: 'bi-broadcast-pin',        label: 'Comms Monitor' },
  { id: 'system-logs', icon: 'bi-file-earmark-text',    label: 'System Logs' },
  { id: 'terminal',    icon: 'bi-terminal',             label: 'Terminal' },
  { id: 'firmware',    icon: 'bi-cloud-arrow-up',       label: 'Firmware' },
];

export default function App() {
  const [page, setPage] = useState('dashboard');
  const [sidebarOpen, setSidebarOpen] = useState(false);

  // Bridge state
  const [connected, setConnected] = useState(false);
  const [port, setPort] = useState('');
  const [txCount, setTxCount] = useState(0);
  const [rxCount, setRxCount] = useState(0);

  // TX/RX LED blink state
  const [txOn, setTxOn] = useState(false);
  const [rxOn, setRxOn] = useState(false);
  const [txActive, setTxActive] = useState(false);
  const [rxActive, setRxActive] = useState(false);
  const txTimer = useRef(null);
  const rxTimer = useRef(null);
  const txActivityTimer = useRef(null);
  const rxActivityTimer = useRef(null);

  // Access toast
  const [toast, setToast] = useState(null);
  const toastTimer = useRef(null);

  // Events buffer (shared across pages)
  const [liveFeed, setLiveFeed] = useState([]);
  const [commsFeed, setCommsFeed] = useState([]);

  // Stats
  const [stats, setStats] = useState({ readers: 0, users: 0, tx: 0, rx: 0, uptime: null });

  // ── Socket listeners ──
  useEffect(() => {
    const onBridgeStatus = (d) => {
      setConnected(d.connected);
      setPort(d.port || '');
      setTxCount(d.tx || 0);
      setRxCount(d.rx || 0);
    };

    const onEvent = (ev) => {
      setLiveFeed(prev => [ev, ...prev].slice(0, 300));
      if (ev.type === 'pd_status' || ev.type === 'state' || ev.type === 'lstat' || ev.type === 'pdid') {
        // reader update - handled by individual pages
      }
    };

    const onComms = (ev) => {
      setCommsFeed(prev => [...prev, ev].slice(-2000));
    };

    const onAccess = (d) => {
      setToast(d);
      clearTimeout(toastTimer.current);
      toastTimer.current = setTimeout(() => setToast(null), 5000);
    };

    const onHeartbeat = (d) => {
      const newTx = d.tx || 0;
      const newRx = d.rx || 0;
      setStats(prev => ({ ...prev, tx: newTx, rx: newRx, uptime: d.uptime }));
      // Drive LED blinks from count changes
      setTxCount(prev => {
        if (newTx !== prev) {
          setTxOn(true); setTxActive(true);
          clearTimeout(txTimer.current);
          txTimer.current = setTimeout(() => setTxOn(false), 150);
          clearTimeout(txActivityTimer.current);
          txActivityTimer.current = setTimeout(() => setTxActive(false), 2500);
        }
        return newTx;
      });
      setRxCount(prev => {
        if (newRx !== prev) {
          setRxOn(true); setRxActive(true);
          clearTimeout(rxTimer.current);
          rxTimer.current = setTimeout(() => setRxOn(false), 150);
          clearTimeout(rxActivityTimer.current);
          rxActivityTimer.current = setTimeout(() => setRxActive(false), 2500);
        }
        return newRx;
      });
    };

    socket.on('bridge_status', onBridgeStatus);
    socket.on('event', onEvent);
    socket.on('comms', onComms);
    socket.on('access', onAccess);
    socket.on('heartbeat', onHeartbeat);

    // Initial load
    api('/api/bridge/status').then(s => {
      setConnected(s.connected);
      setPort(s.port || s.detected_port || '');
      setTxCount(s.tx || 0);
      setRxCount(s.rx || 0);
    });
    api('/api/users').then(u => setStats(prev => ({ ...prev, users: u.length })));

    return () => {
      socket.off('bridge_status', onBridgeStatus);
      socket.off('event', onEvent);
      socket.off('comms', onComms);
      socket.off('access', onAccess);
      socket.off('heartbeat', onHeartbeat);
    };
  }, []);

  const toggleConnect = useCallback(async () => {
    if (connected) {
      await api('/api/bridge/disconnect', 'POST');
      setConnected(false);
      setPort('');
    } else {
      const r = await api('/api/bridge/connect', 'POST');
      if (r.ok) {
        setConnected(true);
        setPort(r.port || '');
        setTimeout(async () => {
          await api('/api/cmd/status', 'POST');
          await api('/api/cmd/sc', 'POST', { index: 0 });
        }, 500);
      } else {
        alert('Could not connect. Is the Blue Pill plugged in?');
      }
    }
  }, [connected]);

  const renderPage = () => {
    switch (page) {
      case 'dashboard':   return <Dashboard liveFeed={liveFeed} stats={stats} setStats={setStats} />;
      case 'readers':     return <Readers />;
      case 'users':       return <Users />;
      case 'enrollment':  return <Enrollment />;
      case 'schedules':   return <Schedules />;
      case 'events':      return <Events />;
      case 'access-log':  return <AccessLog />;
      case 'config':      return <ReaderConfig />;
      case 'comms':       return <CommsMonitor feed={commsFeed} setFeed={setCommsFeed} />;
      case 'system-logs': return <SystemLogs />;
      case 'terminal':    return <Terminal />;
      case 'firmware':    return <FirmwareUpdate />;
      default:            return <Dashboard liveFeed={liveFeed} stats={stats} setStats={setStats} />;
    }
  };

  return (
    <>
      {/* Sidebar */}
      <nav className={`sidebar ${sidebarOpen ? 'show' : ''}`}>
        <div className="p-3 border-bottom border-secondary">
          <h5 className="mb-0">
            <i className="bi bi-shield-lock-fill text-primary"></i> OSDP Panel
          </h5>
          <small className="text-muted">Access Control System</small>
        </div>
        <ul className="nav flex-column mt-2">
          {NAV.map(n => (
            <li key={n.id}>
              <a
                className={`nav-link ${page === n.id ? 'active' : ''}`}
                href="#"
                onClick={e => { e.preventDefault(); setPage(n.id); setSidebarOpen(false); }}
              >
                <i className={`bi ${n.icon}`}></i> {n.label}
              </a>
            </li>
          ))}
        </ul>
      </nav>

      {/* Main */}
      <div className="main-content">
        {/* Top bar */}
        <div className="top-bar">
          <button
            className="btn btn-sm btn-outline-secondary d-lg-none"
            onClick={() => setSidebarOpen(!sidebarOpen)}
          >
            <i className="bi bi-list"></i>
          </button>

          <span className={`led led-conn ${connected ? 'on' : ''}`} title="Bridge connected"></span>
          <span className="text-muted small">{connected ? 'Connected' : 'Disconnected'}</span>
          <button
            className={`btn btn-sm ${connected ? 'btn-outline-danger' : 'btn-outline-success'}`}
            onClick={toggleConnect}
          >
            {connected ? 'Disconnect' : 'Connect'}
          </button>

          {/* TX/RX LEDs — Controller & Reader */}
          <div className="ms-3 d-flex align-items-center gap-3">
            <div className="led-group" title="Controller TX → Reader RX">
              <span className="led-label">CTL TX</span>
              <span className={`led led-tx ${txOn ? 'on' : ''} ${txActive ? 'active' : ''}`}></span>
            </div>
            <div className="led-group" title="Reader TX → Controller RX">
              <span className="led-label">RDR TX</span>
              <span className={`led led-rx ${rxOn ? 'on' : ''} ${rxActive ? 'active' : ''}`}></span>
            </div>
          </div>

          <span className="ms-2 small text-muted">TX:{txCount} RX:{rxCount}</span>
          <span className="ms-auto small text-muted">{port}</span>
        </div>

        {renderPage()}
      </div>

      {/* Access toast */}
      {toast && (
        <div className="access-toast">
          <div className={`alert mb-0 ${toast.granted ? 'alert-success access-granted' : 'alert-danger access-denied'}`}>
            {toast.granted ? (
              <>
                <i className="bi bi-check-circle-fill"></i>{' '}
                <strong>ACCESS GRANTED</strong><br />
                {toast.username} ({toast.method}) Reader {toast.reader}
              </>
            ) : (
              <>
                <i className="bi bi-x-circle-fill"></i>{' '}
                <strong>ACCESS DENIED</strong><br />
                {toast.username ? `${toast.username} — ` : ''}
                {toast.reason || 'unknown'} ({toast.method}) Reader {toast.reader}
              </>
            )}
          </div>
        </div>
      )}
    </>
  );
}
