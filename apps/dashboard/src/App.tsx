import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Route, Routes } from "react-router";
import { Layout } from "./components/Layout";
import { RequireAuth } from "./components/RequireAuth";
import { Login } from "./pages/Login";
import { Overview } from "./pages/Overview";
import { Providers } from "./pages/Providers";
import { Models } from "./pages/Models";
import { Requests } from "./pages/Requests";
import { Latency } from "./pages/Latency";
import { Errors } from "./pages/Errors";
import { Organizations } from "./pages/Organizations";
import { Projects } from "./pages/Projects";
import { ApiKeys } from "./pages/ApiKeys";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchInterval: 15_000,
      retry: 1,
    },
  },
});

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route
            element={
              <RequireAuth>
                <Layout />
              </RequireAuth>
            }
          >
            <Route index element={<Overview />} />
            <Route path="providers" element={<Providers />} />
            <Route path="models" element={<Models />} />
            <Route path="requests" element={<Requests />} />
            <Route path="latency" element={<Latency />} />
            <Route path="errors" element={<Errors />} />
            <Route path="organizations" element={<Organizations />} />
            <Route path="projects" element={<Projects />} />
            <Route path="api-keys" element={<ApiKeys />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
