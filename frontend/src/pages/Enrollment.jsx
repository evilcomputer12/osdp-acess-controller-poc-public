import { useEffect, useState } from 'react';
import { api } from '../api';
import socket from '../socket';

export default function Enrollment() {
  const [users, setUsers] = useState([]);
  const [creds, setCreds] = useState([]);
  const [userMap, setUserMap] = useState({});
  const [cardUser, setCardUser] = useState('');
  const [pinUser, setPinUser] = useState('');
  const [cardStatus, setCardStatus] = useState({ text: '', cls: '' });
  const [pinStatus, setPinStatus] = useState({ text: '', cls: '' });
  const [manualCard, setManualCard] = useState({ hex: '', bits: 26, fmt: 1 });
  const [manualPin, setManualPin] = useState('');

  const load = async () => {
    const u = await api('/api/users');
    setUsers(u);
    const map = {};
    u.forEach(x => map[x.id] = x.username);
    setUserMap(map);
    if (u.length && !cardUser) setCardUser(u[0].id);
    if (u.length && !pinUser) setPinUser(u[0].id);
    setCreds(await api('/api/credentials'));
  };

  useEffect(() => { load(); }, []);

  useEffect(() => {
    const onEnrollDone = (d) => {
      const setter = d.type === 'card' ? setCardStatus : setPinStatus;
      setter({ text: `✓ Enrolled ${d.type} for ${d.user}${d.hex ? ' — ' + d.hex : ''}`, cls: 'text-success' });
      load();
    };
    const onEnrollWaiting = (d) => {
      const setter = d.mode === 'card' ? setCardStatus : setPinStatus;
      setter({ text: `Waiting for ${d.mode}… Present now`, cls: 'text-warning pulse-warn' });
    };
    const onPinProgress = (d) => {
      if (d.length > 0) {
        setPinStatus({ text: `${'●'.repeat(d.length)} (${d.length} digits) — press # to submit, * to clear`, cls: 'text-info' });
      }
    };
    socket.on('enroll_done', onEnrollDone);
    socket.on('enroll_waiting', onEnrollWaiting);
    socket.on('pin_progress', onPinProgress);
    return () => {
      socket.off('enroll_done', onEnrollDone);
      socket.off('enroll_waiting', onEnrollWaiting);
      socket.off('pin_progress', onPinProgress);
    };
  }, []);

  const startEnroll = async (mode) => {
    const uid = mode === 'card' ? cardUser : pinUser;
    if (!uid) return alert('Select a user first');
    const status = await api('/api/bridge/status');
    if (!status.connected) return alert('Bridge not connected!');
    const setter = mode === 'card' ? setCardStatus : setPinStatus;
    setter({ text: `Waiting for ${mode}... Present card/enter PIN now`, cls: 'text-warning' });
    const r = await api('/api/enroll/start', 'POST', { user_id: uid, mode });
    if (!r.ok) setter({ text: 'Error starting enrollment', cls: 'text-danger' });
  };

  const cancelEnroll = async (mode) => {
    await api('/api/enroll/cancel', 'POST');
    const setter = mode === 'card' ? setCardStatus : setPinStatus;
    setter({ text: 'Cancelled', cls: 'text-muted' });
  };

  const enrollCardManual = async () => {
    if (!cardUser || !manualCard.hex) return alert('Select user and enter card hex');
    const r = await api('/api/enroll/card', 'POST', {
      user_id: cardUser, card_hex: manualCard.hex, bits: manualCard.bits, format: manualCard.fmt,
    });
    if (r.ok) { load(); setManualCard({ ...manualCard, hex: '' }); }
    else alert(r.error || 'Error');
  };

  const enrollPinManual = async () => {
    if (!pinUser || !manualPin) return alert('Select user and enter PIN hex');
    const r = await api('/api/enroll/pin', 'POST', { user_id: pinUser, pin_hex: manualPin });
    if (r.ok) { load(); setManualPin(''); }
    else alert(r.error || 'Error');
  };

  const revoke = async (id) => {
    if (!confirm('Revoke this credential?')) return;
    await api(`/api/credentials/${id}`, 'DELETE');
    load();
  };

  const fmtTime = (t) => { try { return new Date(t).toLocaleString(); } catch { return t || ''; } };

  return (
    <div>
      <h4 className="mb-3">Card &amp; PIN Enrollment</h4>
      <div className="row g-4">
        {/* Card */}
        <div className="col-md-6">
          <div className="stat-card">
            <h5><i className="bi bi-credit-card-2-front"></i> Card Enrollment</h5>
            <div className="mb-2">
              <label className="form-label small">Select User</label>
              <select className="form-select form-select-sm" value={cardUser} onChange={e => setCardUser(e.target.value)}>
                {users.map(u => <option key={u.id} value={u.id}>{u.username}{u.full_name ? ` — ${u.full_name}` : ''}</option>)}
              </select>
            </div>
            <button className="btn btn-warning btn-sm" onClick={() => startEnroll('card')}>
              <i className="bi bi-broadcast"></i> Scan Next Card
            </button>
            <button className="btn btn-outline-secondary btn-sm ms-1" onClick={() => cancelEnroll('card')}>Cancel</button>
            <span className={`ms-2 small ${cardStatus.cls}`}>{cardStatus.text}</span>
            <hr />
            <h6>Manual Card Entry</h6>
            <div className="input-group input-group-sm mb-2">
              <span className="input-group-text">HEX</span>
              <input className="form-control" value={manualCard.hex}
                onChange={e => setManualCard({ ...manualCard, hex: e.target.value })} placeholder="e.g. 0A1B2C3D" />
            </div>
            <div className="row g-2 mb-2">
              <div className="col">
                <input type="number" className="form-control form-control-sm" value={manualCard.bits}
                  onChange={e => setManualCard({ ...manualCard, bits: +e.target.value })} placeholder="Bits" />
              </div>
              <div className="col">
                <input type="number" className="form-control form-control-sm" value={manualCard.fmt}
                  onChange={e => setManualCard({ ...manualCard, fmt: +e.target.value })} placeholder="Format" />
              </div>
            </div>
            <button className="btn btn-sm btn-primary" onClick={enrollCardManual}>Enroll Card</button>
          </div>
        </div>

        {/* PIN */}
        <div className="col-md-6">
          <div className="stat-card">
            <h5><i className="bi bi-dial"></i> PIN Enrollment</h5>
            <div className="mb-2">
              <label className="form-label small">Select User</label>
              <select className="form-select form-select-sm" value={pinUser} onChange={e => setPinUser(e.target.value)}>
                {users.map(u => <option key={u.id} value={u.id}>{u.username}{u.full_name ? ` — ${u.full_name}` : ''}</option>)}
              </select>
            </div>
            <button className="btn btn-warning btn-sm" onClick={() => startEnroll('pin')}>
              <i className="bi bi-broadcast"></i> Capture Next PIN
            </button>
            <button className="btn btn-outline-secondary btn-sm ms-1" onClick={() => cancelEnroll('pin')}>Cancel</button>
            <span className={`ms-2 small ${pinStatus.cls}`}>{pinStatus.text}</span>
            <hr />
            <h6>Manual PIN Entry</h6>
            <div className="input-group input-group-sm mb-2">
              <span className="input-group-text">PIN (HEX)</span>
              <input className="form-control" value={manualPin}
                onChange={e => setManualPin(e.target.value)} placeholder="e.g. 31323334" />
            </div>
            <button className="btn btn-sm btn-primary" onClick={enrollPinManual}>Enroll PIN</button>
          </div>
        </div>
      </div>

      <h5 className="mt-4">Enrolled Credentials</h5>
      <div className="table-responsive">
        <table className="table table-sm table-hover">
          <thead>
            <tr><th>User</th><th>Type</th><th>Value (HEX)</th><th>Decimal</th><th>Bits</th><th>Reader</th><th>Enrolled</th><th>Actions</th></tr>
          </thead>
          <tbody>
            {creds.map(c => (
              <tr key={c.id}>
                <td>{userMap[c.user_id] || '?'}</td>
                <td>{c.type}</td>
                <td><code>{c.type === 'card' ? c.card_hex : c.pin_hex}</code></td>
                <td>{c.card_dec || ''}</td>
                <td>{c.bits || ''}</td>
                <td>{c.reader ?? ''}</td>
                <td>{fmtTime(c.enrolled)}</td>
                <td>
                  <button className="btn btn-sm btn-outline-danger" onClick={() => revoke(c.id)}>
                    <i className="bi bi-trash"></i>
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
