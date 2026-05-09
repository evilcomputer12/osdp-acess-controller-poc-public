import { useEffect, useState, useRef, useCallback } from 'react';
import { api } from '../api';
import socket from '../socket';

export default function Readers() {
  const [readers, setReaders] = useState([]);
  const debounceRef = useRef(null);

  const load = useCallback(async () => {
    setReaders(await api('/api/readers'));
  }, []);

  // Debounced reload — max once per second
  const debouncedLoad = useCallback(() => {
    if (debounceRef.current) return;
    debounceRef.current = setTimeout(() => {
      debounceRef.current = null;
      load();
    }, 1000);
  }, [load]);

  useEffect(() => {
    load();
    const onReaderUpdate = () => debouncedLoad();
    const onEvent = (ev) => {
      if (['state', 'pd_status', 'pdid', 'lstat'].includes(ev.type)) debouncedLoad();
    };
    socket.on('reader_update', onReaderUpdate);
    socket.on('event', onEvent);
    return () => {
      socket.off('reader_update', onReaderUpdate);
      socket.off('event', onEvent);
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [load, debouncedLoad]);

  return (
    <div>
      <h4 className="mb-3">Readers</h4>
      <div className="mb-3">
        <button className="btn btn-sm btn-primary" onClick={() => { api('/api/cmd/status', 'POST'); setTimeout(load, 1000); }}>
          <i className="bi bi-arrow-repeat"></i> Refresh Status
        </button>
        <button className="btn btn-sm btn-outline-secondary ms-2" onClick={() => {
          const addr = prompt('OSDP address (0-126):', '0');
          if (addr === null) return;
          const scbk = prompt('SCBK hex (32 chars, blank=default):', '');
          api('/api/cmd/add_reader', 'POST', { addr: parseInt(addr), scbk: scbk || undefined });
        }}>
          <i className="bi bi-plus-lg"></i> Add Reader
        </button>
      </div>

      {!readers.length ? (
        <div className="text-muted">No readers detected. Make sure the bridge is connected and click Refresh Status.</div>
      ) : readers.map(r => (
        <div key={r.index} className="reader-card">
          <div className="d-flex justify-content-between align-items-center">
            <h5 className="mb-0">Reader {r.index} — addr {r.addr ?? '?'}</h5>
            <div>
              <span className={`badge ${r.sc ? 'bg-success' : 'bg-warning'}`}>{r.sc ? 'Secure' : 'Plain'}</span>{' '}
              <span className={`badge ${r.tamper ? 'bg-danger' : 'bg-success'}`}>{r.tamper ? 'TAMPER' : 'Normal'}</span>
            </div>
          </div>
          <div className="small mt-2">
            State: <strong className={r.state === 'OFFLINE' ? 'text-danger' : r.state === 'SECURE' ? 'text-success' : ''}>{r.state || 'OFFLINE'}</strong> | Power: {r.power ? 'FAULT' : 'OK'}
          </div>
          {r.vendor && (
            <div className="small text-muted mt-1">
              Vendor: {r.vendor} | Model: {r.model} | Serial: {r.serial} | FW: {r.firmware}
            </div>
          )}
          <div className="mt-2">
            {['id', 'cap', 'lstat', 'istat', 'ostat'].map(cmd => (
              <button key={cmd} className="btn btn-sm btn-outline-info me-1"
                onClick={() => api(`/api/cmd/${cmd}`, 'POST', { index: r.index })}>
                {cmd.toUpperCase()}
              </button>
            ))}
            <button className="btn btn-sm btn-outline-success"
              onClick={() => api('/api/cmd/sc', 'POST', { index: r.index })}>
              Secure
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}
