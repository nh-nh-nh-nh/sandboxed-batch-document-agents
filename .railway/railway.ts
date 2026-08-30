import { bucket, defineRailway, github, postgres, project, ref, service, volume } from "railway/iac";

export default defineRailway(() => {
  const sandboxedBatchDocumentAgents = github("nh-nh-nh-nh/sandboxed-batch-document-agents", { checkSuites: false });

  const Postgres = postgres("Postgres", { region: "sfo" });
  const postgresVolume = volume("postgres-volume", { alerts: { usage: { "100": {}, "80": {}, "95": {} } }, allowOnlineResize: true, region: "sfo", sizeMB: 500 });
  const blobStorage = bucket("blob-storage", { region: "iad" });

  const sharedEnv = {
    DATABASE_URL: "postgresql+asyncpg://${{Postgres.PGUSER}}:${{Postgres.PGPASSWORD}}@${{Postgres.PGHOST}}:${{Postgres.PGPORT}}/${{Postgres.PGDATABASE}}",
    S3_ENDPOINT_URL: ref(blobStorage, "ENDPOINT"),
    S3_BUCKET: ref(blobStorage, "BUCKET"),
    AWS_ACCESS_KEY_ID: ref(blobStorage, "ACCESS_KEY_ID"),
    AWS_SECRET_ACCESS_KEY: ref(blobStorage, "SECRET_ACCESS_KEY"),
    AWS_REGION: "us-east-1",
    TEMPORAL_ADDRESS: "sandboxed-batch-document-agents.ast5h.tmprl.cloud:7233",
    TEMPORAL_NAMESPACE: "sandboxed-batch-document-agents.ast5h",
    TEMPORAL_TLS: "true",
    TEMPORAL_TASK_QUEUE: "document-analysis",
    WORKER_MAX_CONCURRENT_ACTIVITIES: "16",
    WORKER_MAX_CONCURRENT_WORKFLOW_TASKS: "100",
    ANTHROPIC_MODEL: "claude-sonnet-5",
    ANTHROPIC_MAX_TOKENS: "8192",
    ANTHROPIC_EFFORT: "medium",
    MODAL_APP_NAME: "sandboxed-batch-document-agents",
    SANDBOX_TIMEOUT_S: "1200",
    SANDBOX_CPU: "0.25",
    SANDBOX_MEMORY_MB: "1024",
    TOOL_EXEC_TIMEOUT_S: "120",
    MAX_FILES_PER_SUBMISSION: "100",
    MAX_FILE_BYTES: "1048576",
    MAX_SUBMISSION_BYTES: "104857600",
    TOOL_OUTPUT_MAX_BYTES: "32768",
    AGENT_MAX_TURNS: "25",
  };

  const temporalWorker = service("temporal-worker", {
    source: sandboxedBatchDocumentAgents,
    rootDirectory: "backend",
    start: "uv run python -m sbda.temporal.worker",
    replicas: { "sfo": 1 },
    env: sharedEnv,
  });

  const backendApi = service("backend-api", {
    source: sandboxedBatchDocumentAgents,
    rootDirectory: "backend",
    preDeploy: "uv run alembic upgrade head",
    start: "uv run uvicorn sbda.api.main:app --host 0.0.0.0 --port $PORT",
    healthcheck: "/health",
    replicas: { "sfo": 1 },
    env: {
      ...sharedEnv,
      UPLOAD_REQUEST_TIMEOUT_S: "600",
      CORS_ORIGINS: '["https://frontend-production-0d39.up.railway.app"]',
    },
  });

  const frontend = service("frontend", {
    source: sandboxedBatchDocumentAgents,
    rootDirectory: "frontend",
    build: "npm run build",
    start: "npx --yes serve -s dist -l $PORT",
    replicas: { "sfo": 1 },
    env: {
      VITE_API_BASE_URL: "https://backend-api-production-c560.up.railway.app",
    },
  });

  return project("sandboxed-batch-document-agents", {
    resources: [temporalWorker, frontend, Postgres, backendApi, postgresVolume, blobStorage],
  });
});
