/**
 * Getnet Backstage.io Docker Image Runtime Server (Node 24 Bookworm Slim)
 * Reference: https://backstage.io/docs/deployment/docker
 *
 * Serves the Backstage Software Catalog (catalog-info.yaml), OpenAPI specs,
 * Software Templates (kind: Template), and Self-Healing Re-Fixed Code modules
 * (backstage/refixed-code/*.py) on port 7007 inside the Backstage container.
 */

import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const ROOT_DIR = path.resolve(__dirname, '..');
const PORT = Number(process.env.PORT || 7007);

function safeReadFile(relPath) {
  try {
    return fs.readFileSync(path.join(ROOT_DIR, relPath), 'utf8');
  } catch {
    return '';
  }
}

const REFIXED_MODULES = [
  {
    id: 'card_lock_engine_refixed',
    file: 'backstage/refixed-code/card_lock_engine_refixed.py',
    entityRef: 'component:default/getnet-card-blocker-svc',
    incidentId: 'GTN-INC-SYS-002',
    repoUrl: 'https://github.com/AngC1/Getnet-Autonomous-ALM-QAOps/blob/main/backstage/refixed-code/card_lock_engine_refixed.py',
  },
  {
    id: 'tpv_firmware_gateway_refixed',
    file: 'backstage/refixed-code/tpv_firmware_gateway_refixed.py',
    entityRef: 'component:default/getnet-tpv-smartpos-gateway',
    incidentId: 'GTN-INC-TPV-003',
    repoUrl: 'https://github.com/AngC1/Getnet-Autonomous-ALM-QAOps/blob/main/backstage/refixed-code/tpv_firmware_gateway_refixed.py',
  },
  {
    id: 'online_checkout_fx_refixed',
    file: 'backstage/refixed-code/online_checkout_fx_refixed.py',
    entityRef: 'component:default/getnet-ecommerce-checkout-fx',
    incidentId: 'GTN-INC-ECOM-004',
    repoUrl: 'https://github.com/AngC1/Getnet-Autonomous-ALM-QAOps/blob/main/backstage/refixed-code/online_checkout_fx_refixed.py',
  },
];

const server = http.createServer((req, res) => {
  const url = new URL(req.url || '/', `http://localhost:${PORT}`);

  if (url.pathname === '/healthcheck' || url.pathname === '/.backstage/health/v1/readiness') {
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(
      JSON.stringify({
        status: 'ok',
        service: 'getnet-backstage-developer-portal',
        nodeVersion: process.version,
        dockerBaseImage: 'node:24-bookworm-slim',
        backstageDocsRef: 'https://backstage.io/docs/deployment/docker',
      })
    );
    return;
  }

  if (url.pathname === '/api/catalog/entities') {
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(
      JSON.stringify({
        status: 'ok',
        catalogYaml: safeReadFile('catalog-info.yaml'),
        openApiSpec: safeReadFile('backstage/apis/openapi-getnet-tarjetas-tpv.yaml'),
        templates: [
          safeReadFile('backstage/templates/getnet-api-component-template/template.yaml'),
          safeReadFile('backstage/templates/getnet-refix-hotfix-template/template.yaml'),
        ],
      })
    );
    return;
  }

  if (url.pathname === '/api/refixed-code') {
    const items = REFIXED_MODULES.map((mod) => ({
      ...mod,
      code: safeReadFile(mod.file),
    }));
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ status: 'ok', count: items.length, refixedModules: items }));
    return;
  }

  res.writeHead(200, { 'Content-Type': 'application/json' });
  res.end(
    JSON.stringify({
      portal: 'Getnet Spain Backstage.io Software Catalog & Self-Healing Code Portal',
      dockerGuide: 'https://backstage.io/docs/deployment/docker',
      endpoints: ['/healthcheck', '/api/catalog/entities', '/api/refixed-code'],
    })
  );
});

server.listen(PORT, '0.0.0.0', () => {
  console.log(`[Backstage Docker Image] Listening on http://0.0.0.0:${PORT} (Node ${process.version})`);
});
