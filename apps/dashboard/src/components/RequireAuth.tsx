import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router";
import { useCurrentUser } from "../lib/auth";

export function RequireAuth({ children }: { children: ReactNode }) {
  const user = useCurrentUser();
  const location = useLocation();

  if (!user) {
    return <Navigate to="/login" state={{ from: location }} replace />;
  }
  return <>{children}</>;
}
