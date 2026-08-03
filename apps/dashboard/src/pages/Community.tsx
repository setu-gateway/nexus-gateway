import { useQuery } from "@tanstack/react-query";
import { PageHeader, QueryState, StatCard, Table } from "../components/ui";

const REPO = "setu-gateway/nexus-gateway";
const GITHUB_API = `https://api.github.com/repos/${REPO}`;

// GitHub's anonymous REST API is rate-limited to 60 requests/hour per IP - the
// dashboard's default QueryClient refetches every 15s (App.tsx), which would burn
// through that limit in under a minute if these queries used it. A 10-minute
// staleTime keeps this page useful without ever coming close to the limit.
const GITHUB_STALE_TIME_MS = 10 * 60 * 1000;

interface RepoSummary {
  stargazers_count: number;
  forks_count: number;
  open_issues_count: number;
  html_url: string;
  pushed_at: string;
}

interface Contributor {
  login: string;
  avatar_url: string;
  html_url: string;
  contributions: number;
}

interface IssueOrPr {
  number: number;
  title: string;
  html_url: string;
  pull_request?: unknown;
}

interface Release {
  tag_name: string;
  name: string | null;
  published_at: string;
  html_url: string;
}

async function fetchGitHub<T>(path: string): Promise<T> {
  const res = await fetch(`${GITHUB_API}${path}`);
  if (!res.ok) {
    throw new Error(`GitHub API request failed (${res.status}): ${path}`);
  }
  return res.json();
}

export function Community() {
  const repoQuery = useQuery({
    queryKey: ["github-repo"],
    queryFn: () => fetchGitHub<RepoSummary>(""),
    staleTime: GITHUB_STALE_TIME_MS,
    refetchInterval: false,
  });
  const contributorsQuery = useQuery({
    queryKey: ["github-contributors"],
    queryFn: () => fetchGitHub<Contributor[]>("/contributors?per_page=20"),
    staleTime: GITHUB_STALE_TIME_MS,
    refetchInterval: false,
  });
  const issuesQuery = useQuery({
    queryKey: ["github-issues"],
    // GitHub's /issues endpoint includes PRs too - each has a `pull_request` key,
    // filtered out below to get a true issues-only list.
    queryFn: () => fetchGitHub<IssueOrPr[]>("/issues?state=open&per_page=100"),
    staleTime: GITHUB_STALE_TIME_MS,
    refetchInterval: false,
  });
  const releasesQuery = useQuery({
    queryKey: ["github-releases"],
    queryFn: () => fetchGitHub<Release[]>("/releases?per_page=5"),
    staleTime: GITHUB_STALE_TIME_MS,
    refetchInterval: false,
  });

  const openIssues = (issuesQuery.data ?? []).filter((i) => !i.pull_request);
  const openPrs = (issuesQuery.data ?? []).filter((i) => i.pull_request);

  const isLoading = repoQuery.isLoading || contributorsQuery.isLoading;
  const error = repoQuery.error || contributorsQuery.error;

  return (
    <div>
      <PageHeader
        title="Community"
        subtitle={
          <>
            Live from{" "}
            <a href={`https://github.com/${REPO}`} target="_blank" rel="noreferrer" className="text-brand-light hover:underline">
              github.com/{REPO}
            </a>
            .
          </>
        }
      />
      <QueryState isLoading={isLoading} error={error} isEmpty={false}>
        <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
          <StatCard label="Stars" value={repoQuery.data?.stargazers_count ?? "—"} />
          <StatCard label="Forks" value={repoQuery.data?.forks_count ?? "—"} />
          <StatCard label="Open issues" value={issuesQuery.data ? openIssues.length : "—"} />
          <StatCard label="Open PRs" value={issuesQuery.data ? openPrs.length : "—"} />
        </div>

        <div className="mt-6">
          <h2 className="mb-2 text-sm font-medium text-slate-300">Contributors</h2>
          <QueryState isLoading={contributorsQuery.isLoading} error={contributorsQuery.error} isEmpty={(contributorsQuery.data ?? []).length === 0}>
            <Table head={["Contributor", "Commits"]}>
              {(contributorsQuery.data ?? []).map((c) => (
                <tr key={c.login}>
                  <td className="px-4 py-3">
                    <a href={c.html_url} target="_blank" rel="noreferrer" className="flex items-center gap-2 hover:underline">
                      <img src={c.avatar_url} alt="" className="h-6 w-6 rounded-full" />
                      {c.login}
                    </a>
                  </td>
                  <td className="px-4 py-3 text-slate-400">{c.contributions}</td>
                </tr>
              ))}
            </Table>
          </QueryState>
        </div>

        <div className="mt-6">
          <h2 className="mb-2 text-sm font-medium text-slate-300">Recent releases</h2>
          <QueryState
            isLoading={releasesQuery.isLoading}
            error={releasesQuery.error}
            isEmpty={(releasesQuery.data ?? []).length === 0}
            emptyMessage="No releases published yet."
          >
            <Table head={["Release", "Published"]}>
              {(releasesQuery.data ?? []).map((r) => (
                <tr key={r.tag_name}>
                  <td className="px-4 py-3">
                    <a href={r.html_url} target="_blank" rel="noreferrer" className="hover:underline">
                      {r.name || r.tag_name}
                    </a>
                  </td>
                  <td className="px-4 py-3 text-slate-400">{new Date(r.published_at).toLocaleDateString()}</td>
                </tr>
              ))}
            </Table>
          </QueryState>
        </div>
      </QueryState>
    </div>
  );
}
