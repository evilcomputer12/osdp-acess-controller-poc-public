import { useEffect, useState } from 'react';
import { api } from '../api';

const DAY_NAMES = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

export default function Schedules() {
  const [scheds, setScheds] = useState([]);
  const [showModal, setShowModal] = useState(false);
  const [name, setName] = useState('');
  const [periods, setPeriods] = useState([{ days: [0, 1, 2, 3, 4], start: '08:00', end: '18:00' }]);

  const load = async () => setScheds(await api('/api/schedules'));
  useEffect(() => { load(); }, []);

  const addPeriod = () => setPeriods([...periods, { days: [0, 1, 2, 3, 4], start: '08:00', end: '18:00' }]);

  const toggleDay = (pi, day) => {
    const p = [...periods];
    const d = p[pi].days.includes(day) ? p[pi].days.filter(x => x !== day) : [...p[pi].days, day];
    p[pi] = { ...p[pi], days: d };
    setPeriods(p);
  };

  const create = async () => {
    if (!name.trim()) return alert('Name required');
    const r = await api('/api/schedules', 'POST', { name, periods });
    if (r.ok) { setShowModal(false); load(); }
    else alert(r.error || 'Error');
  };

  const del = async (id) => {
    if (!confirm('Delete this schedule?')) return;
    await api(`/api/schedules/${id}`, 'DELETE');
    load();
  };

  return (
    <div>
      <h4 className="mb-3">Access Schedules</h4>
      <p className="text-muted small">
        Schedules define when users are allowed access. Days: 0=Mon … 6=Sun. Times in 24h format.
      </p>
      <button className="btn btn-sm btn-primary mb-3" onClick={() => { setName(''); setPeriods([{ days: [0,1,2,3,4], start: '08:00', end: '18:00' }]); setShowModal(true); }}>
        <i className="bi bi-plus-lg"></i> New Schedule
      </button>

      {scheds.map(s => (
        <div key={s.id} className="reader-card">
          <div className="d-flex justify-content-between align-items-center">
            <h5 className="mb-0">{s.name}</h5>
            <button className="btn btn-sm btn-outline-danger" onClick={() => del(s.id)}>
              <i className="bi bi-trash"></i>
            </button>
          </div>
          {(s.periods || []).map((p, i) => (
            <div key={i} className="small">
              {(p.days || []).map(d => DAY_NAMES[d]).join(', ')}: {p.start} – {p.end}
            </div>
          ))}
          {!s.periods?.length && <div className="small text-muted">No periods defined</div>}
        </div>
      ))}

      {showModal && (
        <div className="modal show d-block" tabIndex="-1" style={{ background: 'rgba(0,0,0,.5)' }}>
          <div className="modal-dialog"><div className="modal-content">
            <div className="modal-header">
              <h5 className="modal-title">New Schedule</h5>
              <button type="button" className="btn-close" onClick={() => setShowModal(false)}></button>
            </div>
            <div className="modal-body">
              <div className="mb-2">
                <label className="form-label small">Name</label>
                <input className="form-control form-control-sm" value={name} onChange={e => setName(e.target.value)} />
              </div>
              {periods.map((p, pi) => (
                <div key={pi} className="border rounded p-2 mb-2">
                  <div className="mb-1">
                    {DAY_NAMES.map((d, di) => (
                      <div key={di} className="form-check form-check-inline">
                        <input className="form-check-input" type="checkbox"
                          checked={p.days.includes(di)} onChange={() => toggleDay(pi, di)} />
                        <label className="form-check-label small">{d}</label>
                      </div>
                    ))}
                  </div>
                  <div className="row g-2">
                    <div className="col">
                      <input type="time" className="form-control form-control-sm" value={p.start}
                        onChange={e => { const np = [...periods]; np[pi] = { ...np[pi], start: e.target.value }; setPeriods(np); }} />
                    </div>
                    <div className="col">
                      <input type="time" className="form-control form-control-sm" value={p.end}
                        onChange={e => { const np = [...periods]; np[pi] = { ...np[pi], end: e.target.value }; setPeriods(np); }} />
                    </div>
                  </div>
                </div>
              ))}
              <button className="btn btn-sm btn-outline-secondary mt-2" onClick={addPeriod}>
                <i className="bi bi-plus"></i> Add Period
              </button>
            </div>
            <div className="modal-footer">
              <button className="btn btn-primary btn-sm" onClick={create}>Create</button>
            </div>
          </div></div>
        </div>
      )}
    </div>
  );
}
