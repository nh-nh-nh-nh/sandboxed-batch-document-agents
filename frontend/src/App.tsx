import { useEffect, useState } from "react";
import { getTenants } from "./api/client";
import type { Tenant } from "./api/types";
import { TenantPanel } from "./components/TenantPanel";

export default function App() {
  const [tenants, setTenants] = useState<Tenant[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    getTenants(controller.signal)
      .then(setTenants)
      .catch((err) => {
        if ((err as { name?: string }).name !== "AbortError") {
          setError("Could not load tenants.");
        }
      });
    return () => controller.abort();
  }, []);

  if (error) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-canvas">
        <p className="text-sm text-err">{error}</p>
      </div>
    );
  }

  if (!tenants) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-canvas">
        <p className="text-sm text-ink-muted">Loading…</p>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-canvas">
      <div className="grid grid-cols-1 md:grid-cols-2">
        {tenants.map((tenant) => (
          <TenantPanel key={tenant.id} tenant={tenant} />
        ))}
      </div>
    </div>
  );
}
