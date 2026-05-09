import { useEffect, useRef, useState } from 'react';
import socket from '../socket';

export default function Terminal() {
  const [lines, setLines] = useState([]);
  const [cmd, setCmd] = useState('');
  const feedRef = useRef(null);

  useEffect(() => {
    const onEvent = (ev) => {
      setLines(prev => [...prev, { dir: 'in', text: ev.raw || JSON.stringify(ev) }].slice(-500));
    };
    socket.on('event', onEvent);
    return () => socket.off('event', onEvent);
  }, []);

  useEffect(() => {
    if (feedRef.current) feedRef.current.scrollTop = feedRef.current.scrollHeight;
  }, [lines]);

  const send = () => {
    if (!cmd.trim()) return;
    socket.emit('send_cmd', { cmd: cmd.trim() });
    setLines(prev => [...prev, { dir: 'out', text: cmd.trim() }]);
    setCmd('');
  };

  return (
    <div>
      <h4 className="mb-3">Raw Terminal</h4>
      <div className="event-feed border rounded mb-2" ref={feedRef} style={{ height: 400 }}>
        {lines.map((l, i) => (
          <div key={i} className={`ev-row ${l.dir === 'out' ? 'text-warning' : 'text-success'}`}>
            {l.dir === 'out' ? '→ ' : '← '}{l.text}
          </div>
        ))}
      </div>
      <div className="input-group">
        <input className="form-control" value={cmd} onChange={e => setCmd(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && send()} placeholder="Type command…" autoComplete="off" />
        <button className="btn btn-primary" onClick={send}>Send</button>
      </div>
    </div>
  );
}
