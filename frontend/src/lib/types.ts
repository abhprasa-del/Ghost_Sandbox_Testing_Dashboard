export type Category = "running" | "failed" | "degraded" | "passed" | "other";

export interface Run {
  ticket_key: string;
  title: string;
  assignee: string | null;
  sqa_owner: string | null;
  devqa_owner: string | null;
  alsi_version: string | null;
  metadata_mode: string;
  sandbox_build_no: number | null;
  sandbox_build_url: string | null;
  sandbox_status: string | null;
  ghost_version: string | null;
  commented_at: string;
  run_id: number;
  have_perf: string | null;
  have_load: string | null;
  have_bats: string | null;
  have_baseline: string | null;
  asan_status: string | null;
  lsan_status: string | null;
  tsan_status: string | null;
  perf_outcome: string | null;
  load_outcome: string | null;
  baseline_outcome: string | null;
  not_selected_jobs: string[] | null;
  comment_edited: boolean | null;
  ticket_status: string | null;
  category: Category;
}

export interface RunsPage {
  items: Run[];
  total: number;
  page: number;
  page_size: number;
}

export interface SummaryBlock {
  total: number;
  passed: number;
  failed: number;
  degraded: number;
  running: number;
  other: number;
}

export interface Summary {
  timezone: string;
  today: SummaryBlock;
  last_7_days: SummaryBlock;
}

export interface Filters {
  assignees: string[];
  sqa: string[];
  devqa: string[];
  alsi_versions: string[];
  metadata_modes: string[];
  statuses: string[];
}

export interface Meta {
  job_name_map: Record<string, string>;
  canonical_jobs: string[];
  categories: Category[];
  jira_base_url: string;
  dashboard_tz: string;
}

export interface SyncStatus {
  running: boolean;
  last_sync: {
    status: string | null;
    started_at: string;
    finished_at: string | null;
    comments_seen: number | null;
    runs_upserted: number | null;
    error_message: string | null;
  } | null;
}

export interface BuildArtifact {
  artifact_type: string;
  download_url: string;
  wget_command: string | null;
}

export interface BaselineSuite {
  suite_name: string;
  job_link: string | null;
  report_link: string | null;
  siam_link: string | null;
}

export interface BatsGroup {
  name: string;
  name_url: string | null;
  links: { label: string; url: string }[];
  note: string | null;
}

export interface JobResult {
  job_name: string;
  job_status: string;
  outcome: string | null;
  result_text: string | null;
  job_url: string | null;
  summary_url: string | null;
  analysis_url: string | null;
  plots_url: string | null;
  build_artifacts: BuildArtifact[];
  baseline_suites: BaselineSuite[];
  bats_groups?: BatsGroup[];
  result_links?: { label: string; url: string }[];
}

export interface RunDetail {
  run_id: number;
  ticket_key: string;
  title: string;
  assignee: string | null;
  sqa_owner: string | null;
  devqa_owner: string | null;
  ticket_status: string | null;
  jira_url: string | null;
  alsi_version: string | null;
  metadata_mode: string;
  sandbox_build_no: number | null;
  sandbox_build_url: string | null;
  sandbox_status: string | null;
  ghost_version: string | null;
  not_selected_jobs: string[] | null;
  ghost_crashes_url: string | null;
  commented_at: string;
  comment_edited: boolean | null;
  category: Category;
  job_results: JobResult[];
}

export interface TicketHistoryRun {
  run_id: number;
  alsi_version: string | null;
  metadata_mode: string;
  sandbox_build_no: number | null;
  sandbox_status: string | null;
  ghost_version: string | null;
  commented_at: string;
  comment_edited: boolean | null;
  category: Category;
  jobs: { job_name: string; job_status: string; outcome: string | null }[];
}

export interface TicketDetail {
  ticket: { ticket_key: string; title: string; assignee: string | null; status: string | null };
  runs: TicketHistoryRun[];
}
