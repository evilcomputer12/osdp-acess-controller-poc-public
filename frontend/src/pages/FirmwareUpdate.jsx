import { useState, useEffect } from 'react';
import { api } from '../api';
import socket from '../socket';

export default function FirmwareUpdate() {
  const [file, setFile] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState({ percent: 0, message: '' });
  const [result, setResult] = useState(null);

  useEffect(() => {
    const onProgress = (d) => setProgress(d);
    socket.on('fw_progress', onProgress);
    return () => socket.off('fw_progress', onProgress);
  }, []);

  const handleUpload = async () => {
    if (!file) return;
    setUploading(true);
    setResult(null);
    setProgress({ percent: 0, message: 'Starting...' });

    const form = new FormData();
    form.append('file', file);

    try {
      const res = await fetch('/api/firmware/upload', { method: 'POST', body: form });
      const data = await res.json();
      if (data.ok) {
        setResult({ ok: true, text: 'Firmware updated successfully!' });
      } else {
        setResult({ ok: false, text: data.error || 'Update failed' });
      }
    } catch (e) {
      setResult({ ok: false, text: e.message });
    } finally {
      setUploading(false);
    }
  };

  return (
    <div>
      <h4 className="mb-3">Firmware Update</h4>

      <div className="card bg-dark border-secondary mb-3">
        <div className="card-body">
          <h6 className="card-title">
            <i className="bi bi-cloud-arrow-up me-2"></i>Upload Firmware
          </h6>
          <p className="text-secondary small mb-3">
            Select a compiled <code>.bin</code> file to flash to the OSDP Bridge.
            The MCU will reboot into the bootloader, receive the firmware, then restart.
          </p>

          <div className="input-group mb-3">
            <input
              type="file"
              accept=".bin"
              className="form-control bg-dark text-light border-secondary"
              onChange={(e) => { setFile(e.target.files[0]); setResult(null); }}
              disabled={uploading}
            />
            <button
              className="btn btn-warning"
              onClick={handleUpload}
              disabled={!file || uploading}
            >
              {uploading ? (
                <><span className="spinner-border spinner-border-sm me-1"></span>Flashing...</>
              ) : (
                <><i className="bi bi-lightning-charge me-1"></i>Flash</>
              )}
            </button>
          </div>

          {file && !uploading && (
            <div className="text-secondary small">
              <i className="bi bi-file-earmark-binary me-1"></i>
              {file.name} ({(file.size / 1024).toFixed(1)} KB)
            </div>
          )}

          {uploading && (
            <div className="mt-3">
              <div className="progress bg-secondary" style={{ height: '24px' }}>
                <div
                  className="progress-bar progress-bar-striped progress-bar-animated bg-warning"
                  style={{ width: `${progress.percent}%` }}
                >
                  {progress.percent}%
                </div>
              </div>
              <div className="text-secondary small mt-1">{progress.message}</div>
            </div>
          )}

          {result && (
            <div className={`alert mt-3 mb-0 ${result.ok ? 'alert-success' : 'alert-danger'}`}>
              {result.ok ? <i className="bi bi-check-circle me-1"></i> : <i className="bi bi-x-circle me-1"></i>}
              {result.text}
            </div>
          )}
        </div>
      </div>

      <div className="card bg-dark border-secondary">
        <div className="card-body">
          <h6 className="card-title">
            <i className="bi bi-info-circle me-2"></i>How it works
          </h6>
          <ol className="text-secondary small mb-0">
            <li>The app sends a <strong>BOOTLOADER</strong> command to the MCU</li>
            <li>The MCU reboots into the USB bootloader (LED blinks fast)</li>
            <li>The bootloader erases the application flash region</li>
            <li>New firmware is written in 256-byte chunks with verification</li>
            <li>CRC-32 check ensures data integrity</li>
            <li>The MCU boots the new firmware and reconnects</li>
          </ol>
          <hr className="border-secondary" />
          <p className="text-secondary small mb-0">
            <strong>Recovery:</strong> If the update fails, connect PA4 to GND and reset
            the board to force bootloader mode. Then retry the upload.
          </p>
        </div>
      </div>
    </div>
  );
}
