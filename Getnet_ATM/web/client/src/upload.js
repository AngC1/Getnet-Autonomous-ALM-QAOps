// Subida de archivos: validación previa en el cliente y envío por XMLHttpRequest (con progreso).
// Las rutas son SIEMPRE relativas (la web vive detrás de un proxy en /proxy/3001/).
export const ACCEPT = 'image/png,image/jpeg,image/webp,video/mp4,video/quicktime,video/webm';
export const IMAGE_TYPES = ['image/png', 'image/jpeg', 'image/webp'];
export const VIDEO_TYPES = ['video/mp4', 'video/quicktime', 'video/webm'];
export const MAX_BYTES = 200 * 1024 * 1024;
export const MAX_IMAGE_BYTES = 5 * 1024 * 1024;

export const LABEL_OPTIONS = [
  ['CORRECTO', 'Ayesa Digital (correcto)'],
  ['INCORRECTO', 'Ayesa (incorrecto)'],
  ['SIN_LOGO', 'Sin logo'],
  ['AMBIGUO', 'Ambiguo'],
];

export const fmtSize = (n) => (n >= 1048576 ? `${(n / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`);

// Devuelve un mensaje de error o null. El servidor vuelve a validar por contenido.
export function checkFile(file) {
  if (!file) return 'Archivo no válido';
  const isImg = IMAGE_TYPES.includes(file.type);
  if (!isImg && !VIDEO_TYPES.includes(file.type)) return 'Tipo no permitido (PNG, JPEG, WebP, MP4, MOV o WebM)';
  if (file.size > MAX_BYTES) return 'Supera el límite de 200 MB';
  if (isImg && file.size > MAX_IMAGE_BYTES) return 'La imagen supera 5 MB';
  if (file.size === 0) return 'El archivo está vacío';
  return null;
}

export const kindOf = (file) => (VIDEO_TYPES.includes(file?.type) ? 'video' : 'imagen');

let seq = 0;
export const newItem = (file, label = 'CORRECTO') => {
  const error = checkFile(file);
  return { key: `f${++seq}`, file, label, status: error ? 'error' : 'pending', progress: 0, id: null, error };
};

// POST api/uploads (multipart). `XHR` es inyectable para los tests.
export function uploadFile(file, label, { onProgress, XHR = globalThis.XMLHttpRequest } = {}) {
  return new Promise((resolve, reject) => {
    const x = new XHR();
    x.open('POST', 'api/uploads');
    x.responseType = 'text';
    if (x.upload) x.upload.onprogress = (e) => { if (e.lengthComputable && onProgress) onProgress(e.loaded / e.total); };
    x.onerror = () => reject(new Error('Error de red al subir el archivo'));
    x.ontimeout = () => reject(new Error('Tiempo de espera agotado'));
    x.onabort = () => reject(new Error('Subida cancelada'));
    x.onload = () => {
      let body = null;
      try { body = JSON.parse(x.responseText); } catch { /* respuesta no JSON */ }
      if (x.status >= 200 && x.status < 300 && body?.id) { if (onProgress) onProgress(1); resolve(body); }
      else reject(new Error(body?.error || `Error ${x.status}`));
    };
    const fd = new FormData();
    fd.append('label', label);
    fd.append('file', file, file.name);
    x.send(fd);
  });
}
