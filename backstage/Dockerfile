# =============================================================================
# Dockerfile Oficial para la Imagen de Backstage.io — Getnet Autonomous ALM
# Basado en: https://backstage.io/docs/deployment/docker (Node.js 24 Bookworm Slim)
# Incluye:
#   - Software Catalog (catalog-info.yaml · System, Components, APIs)
#   - Software Templates Scaffolder (backstage/templates/*)
#   - Contratos OpenAPI 3.0 (backstage/apis/*)
#   - Código Re-Fixeado en Producción (backstage/refixed-code/*)
# =============================================================================

FROM node:24-bookworm-slim AS backstage-runtime

LABEL org.opencontainers.image.title="Getnet Backstage Software Catalog & Autonomous ALM Developer Portal"
LABEL org.opencontainers.image.description="Imagen Backstage.io con plantillas API, componentes y visor de código Re-Fixeado para Getnet (Grupo Santander)"
LABEL org.opencontainers.image.source="https://github.com/AngC1/Getnet-Autonomous-ALM-QAOps"
LABEL org.opencontainers.image.documentation="https://backstage.io/docs/deployment/docker"

# Instalar intérprete Python ligero y dependencias del sistema según guía oficial de Backstage Docker
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && \
    apt-get install -y --no-install-recommends python3 g++ build-essential curl git ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# Configurar usuario no-root `node` y directorio de trabajo `/app` conforme a https://backstage.io/docs/deployment/docker
USER node
WORKDIR /app

ENV NODE_ENV=production
ENV NODE_OPTIONS="--no-node-snapshot"
ENV BACKSTAGE_PORT=7007
ENV GITHUB_REPO_URL="https://github.com/AngC1/Getnet-Autonomous-ALM-QAOps"

# Copiar configuración de Backstage, Catálogo de Componentes, Plantillas Scaffolder, APIs y Código Re-Fixeado
COPY --chown=node:node catalog-info.yaml ./catalog-info.yaml
COPY --chown=node:node backstage/app-config.yaml ./app-config.yaml
COPY --chown=node:node backstage/app-config.production.yaml ./app-config.production.yaml
COPY --chown=node:node backstage/templates ./backstage/templates
COPY --chown=node:node backstage/apis ./backstage/apis
COPY --chown=node:node backstage/refixed-code ./backstage/refixed-code
COPY --chown=node:node backstage/backstage_image_server.mjs ./backstage/backstage_image_server.mjs

EXPOSE 7007

CMD ["node", "backstage/backstage_image_server.mjs", "--config", "app-config.yaml", "--config", "app-config.production.yaml"]
