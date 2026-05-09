import { useState } from 'react';
import { api } from '../api';

const LED_PRESETS = [
  { label: 'Off',                params: '0 0 0 0 0 0 0 0 1 0 0 0 0' },
  { label: 'Solid Red',          params: '0 0 0 0 0 0 0 0 1 10 0 1 0' },
  { label: 'Solid Green',        params: '0 0 0 0 0 0 0 0 1 10 0 2 0' },
  { label: 'Solid Amber',        params: '0 0 0 0 0 0 0 0 1 10 0 3 0' },
  { label: 'Solid Blue',         params: '0 0 0 0 0 0 0 0 1 10 0 4 0' },
  { label: 'Flash Red',          params: '0 0 2 5 5 1 0 50 0 0 0 0 0' },
  { label: 'Flash Green',        params: '0 0 2 5 5 2 0 50 0 0 0 0 0' },
  { label: 'Flash Amber',        params: '0 0 2 5 5 3 0 50 0 0 0 0 0' },
  { label: 'Flash Blue',         params: '0 0 2 5 5 4 0 50 0 0 0 0 0' },
  { label: 'Flash Red (fast)',   params: '0 0 2 2 2 1 0 50 0 0 0 0 0' },
  { label: 'Flash Green (fast)', params: '0 0 2 2 2 2 0 50 0 0 0 0 0' },
];

const DEFAULT_SCBK = '0102030405060708090A0B0C0D0E0F10';

export default function ReaderConfig() {
  const [ledIdx, setLedIdx] = useState(0);
  const [ledPreset, setLedPreset] = useState(0);
  const [buz, setBuz] = useState({ index: 0, tone: 2, on: 5, off: 5, count: 3 });
  const [com, setCom] = useState({ index: 0, addr: 0, baud: 9600 });
  const [key, setKey] = useState({ idx: 0, val: DEFAULT_SCBK });
  const [rel, setRel] = useState({ idx: 0, val: 'T1500' });

  const sendLed = () => {
    api('/api/cmd/led', 'POST', { index: ledIdx, params: LED_PRESETS[ledPreset].params });
  };

  const handleKeyChange = (e) => {
    const v = e.target.value.replace(/[^0-9A-Fa-f]/g, '').toUpperCase().slice(0, 32);
    setKey({ ...key, val: v });
  };

  return (
    <div>
      <h4 className="mb-3">Reader Configuration</h4>
      <div className="row g-4">
        {/* LED */}
        <div className="col-md-6">
          <div className="stat-card">
            <h5><i className="bi bi-lightbulb"></i> LED Control</h5>
            <div className="row g-2 mb-2">
              <div className="col-4"><label className="form-label small">Reader #</label>
                <input type="number" className="form-control form-control-sm" value={ledIdx} onChange={e => setLedIdx(+e.target.value)} /></div>
              <div className="col-8"><label className="form-label small">Preset</label>
                <select className="form-select form-select-sm" value={ledPreset} onChange={e => setLedPreset(+e.target.value)}>
                  {LED_PRESETS.map((p, i) => <option key={i} value={i}>{p.label}</option>)}
                </select></div>
            </div>
            <button className="btn btn-sm btn-primary" onClick={sendLed}><i className="bi bi-send"></i> Send LED</button>
          </div>
        </div>

        {/* Right column */}
        <div className="col-md-6">
          {/* Buzzer */}
          <div className="stat-card mb-3">
            <h5><i className="bi bi-bell"></i> Buzzer Control</h5>
            <div className="row g-2 mb-2">
              <div className="col-3"><label className="form-label small">Reader</label>
                <input type="number" className="form-control form-control-sm" value={buz.index} onChange={e => setBuz({ ...buz, index: +e.target.value })} /></div>
              <div className="col-3"><label className="form-label small">Tone</label>
                <select className="form-select form-select-sm" value={buz.tone} onChange={e => setBuz({ ...buz, tone: +e.target.value })}>
                  <option value={0}>None</option><option value={1}>Off</option><option value={2}>Default</option>
                </select></div>
              <div className="col-2"><label className="form-label small">On</label>
                <input type="number" className="form-control form-control-sm" value={buz.on} onChange={e => setBuz({ ...buz, on: +e.target.value })} /></div>
              <div className="col-2"><label className="form-label small">Off</label>
                <input type="number" className="form-control form-control-sm" value={buz.off} onChange={e => setBuz({ ...buz, off: +e.target.value })} /></div>
              <div className="col-2"><label className="form-label small">Count</label>
                <input type="number" className="form-control form-control-sm" value={buz.count} onChange={e => setBuz({ ...buz, count: +e.target.value })} /></div>
            </div>
            <button className="btn btn-sm btn-primary" onClick={() => api('/api/cmd/buzzer', 'POST', buz)}>
              <i className="bi bi-send"></i> Send Buzzer
            </button>
          </div>

          {/* COM Settings */}
          <div className="stat-card mb-3">
            <h5><i className="bi bi-wifi"></i> COM Settings</h5>
            <div className="row g-2 mb-2">
              <div className="col-3"><label className="form-label small">Reader</label>
                <input type="number" className="form-control form-control-sm" value={com.index} onChange={e => setCom({ ...com, index: +e.target.value })} /></div>
              <div className="col-4"><label className="form-label small">New Addr</label>
                <input type="number" className="form-control form-control-sm" value={com.addr} onChange={e => setCom({ ...com, addr: +e.target.value })} /></div>
              <div className="col-5"><label className="form-label small">Baud</label>
                <select className="form-select form-select-sm" value={com.baud} onChange={e => setCom({ ...com, baud: +e.target.value })}>
                  {[9600, 19200, 38400, 57600, 115200].map(b => <option key={b} value={b}>{b}</option>)}
                </select></div>
            </div>
            <button className="btn btn-sm btn-warning" onClick={() => api('/api/cmd/comset', 'POST', com)}>
              <i className="bi bi-send"></i> Set COM
            </button>
          </div>

          {/* Security Key */}
          <div className="stat-card mb-3">
            <h5><i className="bi bi-key"></i> Security Key</h5>
            <div className="row g-2 mb-2">
              <div className="col-3"><label className="form-label small">Reader</label>
                <input type="number" className="form-control form-control-sm" value={key.idx} onChange={e => setKey({ ...key, idx: +e.target.value })} /></div>
              <div className="col-9"><label className="form-label small">SCBK (32 hex chars = 16 bytes)</label>
                <input className="form-control form-control-sm font-monospace" value={key.val}
                  onChange={handleKeyChange}
                  maxLength={32}
                  placeholder="0102030405060708090A0B0C0D0E0F10" />
                <div className="text-muted small mt-1">{key.val.length}/32 hex chars</div></div>
            </div>
            <button className="btn btn-sm btn-danger" onClick={() => {
              if (key.val.length !== 32 || !/^[0-9A-Fa-f]{32}$/.test(key.val)) return alert('Key must be exactly 32 hex characters (0-9, A-F)');
              api('/api/cmd/keyset', 'POST', { index: key.idx, key: key.val });
            }}>
              <i className="bi bi-send"></i> Set Key
            </button>
          </div>

          {/* Relay */}
          <div className="stat-card">
            <h5><i className="bi bi-toggle-on"></i> Relay / Output</h5>
            <div className="row g-2 mb-2">
              <div className="col-4"><label className="form-label small">Reader</label>
                <input type="number" className="form-control form-control-sm" value={rel.idx} onChange={e => setRel({ ...rel, idx: +e.target.value })} /></div>
              <div className="col-4"><label className="form-label small">Value</label>
                <input className="form-control form-control-sm" value={rel.val} onChange={e => setRel({ ...rel, val: e.target.value })} placeholder="0, 1, or T<ms>" /></div>
            </div>
            <button className="btn btn-sm btn-primary" onClick={() => api('/api/cmd/relay', 'POST', { index: rel.idx, value: rel.val })}>
              <i className="bi bi-send"></i> Relay
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
