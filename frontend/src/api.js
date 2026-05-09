let apiHooks = {};

export function setApiHooks(hooks = {}) {
  apiHooks = hooks;
}

/** Lightweight fetch wrapper for the Flask backend. */
export async function api(url, method = 'GET', body = null, options = {}) {
  const opts = { method, credentials: 'same-origin' };
  if (body) {
    opts.headers = { 'Content-Type': 'application/json' };
    opts.body = JSON.stringify(body);
  }
  const r = await fetch(url, opts);
  const contentType = r.headers.get('content-type') || '';
  const payload = contentType.includes('application/json') ? await r.json() : { text: await r.text() };

  if (!r.ok) {
    const errorPayload = {
      ok: false,
      status: r.status,
      ...(payload && typeof payload === 'object' && !Array.isArray(payload) ? payload : { payload }),
    };
    if (r.status === 401 && apiHooks.onUnauthorized && !options.ignoreUnauthorized) {
      apiHooks.onUnauthorized(errorPayload);
    }
    return errorPayload;
  }

  return payload;
}
