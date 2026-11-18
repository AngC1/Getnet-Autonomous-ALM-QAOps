const j = async (r) => { if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || r.statusText); return r.json(); };
const qs = (o) => new URLSearchParams(Object.entries(o).filter(([, v]) => v)).toString();
export const api = {
  stats: () => fetch('api/stats').then(j),
  dashboard: (refresh) => fetch(`api/dashboard${refresh ? '?refresh=1' : ''}`).then(j),
  assets: (f) => fetch(`api/assets?${qs(f)}`).then(j),
  asset: (id) => fetch(`api/assets/${encodeURIComponent(id)}`).then(j),
  startVerify: (only) => fetch('api/jobs/verify', {
    method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(only?.length ? { only } : {}),
  }).then(j),
  startGenerate: (body) => fetch('api/jobs/generate', {
    method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body),
  }).then(j),
  job: (id) => fetch(`api/jobs/${encodeURIComponent(id)}`).then(j),
  latestJob: () => fetch('api/jobs/latest').then((r) => (r.status === 404 ? null : j(r))),
  validate: (id, label) => fetch(`api/assets/${encodeURIComponent(id)}/validate`, {
    method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(label ? { label } : {}),
  }).then(j),
};

export const REPORT_URL = 'api/report'; // relativa: la web va detrás de /proxy/3001/
