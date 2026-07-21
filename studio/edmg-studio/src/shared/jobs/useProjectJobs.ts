import { useCallback, useEffect, useState } from "react";
import { apiGet, apiPost } from "../../components/api";
import { postQueueJobAction, type QueueJobAction } from "./jobActions";
import type { StudioJob } from "./jobStatus";

export type JobLogSelection = {
  job: StudioJob;
  log: string;
  events: Array<Record<string, unknown>>;
};

type UseProjectJobsOptions = {
  projectId?: string;
  global?: boolean;
  autoRefresh?: boolean;
  refreshIntervalMs?: number;
};

export function useProjectJobs(options: UseProjectJobsOptions) {
  const {
    projectId = "",
    global = false,
    autoRefresh = false,
    refreshIntervalMs = 2500,
  } = options;

  const [jobs, setJobs] = useState<StudioJob[]>([]);
  const [selectedLog, setSelectedLog] = useState<JobLogSelection | null>(null);
  const [lastRefreshAt, setLastRefreshAt] = useState(0);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setError(null);
    try {
      if (global) {
        const data = await apiGet("/v1/jobs");
        setJobs(Array.isArray(data?.jobs) ? data.jobs : []);
      } else if (projectId) {
        const data = await apiGet(`/v1/projects/${projectId}/jobs`);
        setJobs(Array.isArray(data?.jobs) ? data.jobs : []);
      } else {
        setJobs([]);
      }
      setLastRefreshAt(Date.now());
    } catch (err) {
      setError(String(err));
    }
  }, [global, projectId]);

  const loadJobLog = useCallback(async (job: StudioJob) => {
    setError(null);
    try {
      const [logData, eventsData] = await Promise.all([
        apiGet(`/v1/projects/${job.project_id}/jobs/${job.id}/log`),
        apiGet(`/v1/projects/${job.project_id}/jobs/${job.id}/events`),
      ]);
      setSelectedLog({
        job,
        log: String(logData?.log || ""),
        events: Array.isArray(eventsData?.events) ? eventsData.events : [],
      });
    } catch (err) {
      setError(String(err));
    }
  }, []);

  const runJobAction = useCallback(
    async (job: StudioJob, action: QueueJobAction) => {
      setError(null);
      try {
        await postQueueJobAction(job, action);
        await refresh();
        if (selectedLog?.job.id === job.id) {
          await loadJobLog(job);
        }
      } catch (err) {
        setError(String(err));
      }
    },
    [loadJobLog, refresh, selectedLog?.job.id],
  );

  const resumeFromCheckpoint = useCallback(
    async (job: StudioJob) => {
      setError(null);
      try {
        await apiPost(`/v1/projects/${job.project_id}/jobs/${job.id}/resume_from_checkpoint`, {});
        await refresh();
      } catch (err) {
        setError(String(err));
      }
    },
    [refresh],
  );

  const restartClean = useCallback(
    async (job: StudioJob) => {
      setError(null);
      try {
        await apiPost(`/v1/projects/${job.project_id}/jobs/${job.id}/restart_clean`, {});
        await refresh();
      } catch (err) {
        setError(String(err));
      }
    },
    [refresh],
  );

  const tickWorker = useCallback(async () => {
    setError(null);
    try {
      await apiPost("/v1/jobs/tick", {});
      await refresh();
    } catch (err) {
      setError(String(err));
    }
  }, [refresh]);

  useEffect(() => {
    refresh().catch(() => {});
  }, [refresh]);

  useEffect(() => {
    if (!autoRefresh) return;
    const timer = window.setInterval(async () => {
      await refresh();
      if (selectedLog?.job) {
        await loadJobLog(selectedLog.job);
      }
    }, refreshIntervalMs);
    return () => window.clearInterval(timer);
  }, [autoRefresh, loadJobLog, refresh, refreshIntervalMs, selectedLog?.job]);

  return {
    jobs,
    selectedLog,
    setSelectedLog,
    lastRefreshAt,
    error,
    setError,
    refresh,
    loadJobLog,
    runJobAction,
    resumeFromCheckpoint,
    restartClean,
    tickWorker,
  };
}
