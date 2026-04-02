import { useEffect, useState } from "react";
import { apiGet } from "../components/api";

const STORAGE_KEY = "edmg-studio-workbench-project-id";

function readStoredProjectId(): string {
  if (typeof window === "undefined") return "";
  try {
    return window.localStorage.getItem(STORAGE_KEY) || "";
  } catch {
    return "";
  }
}

function writeStoredProjectId(projectId: string) {
  if (typeof window === "undefined") return;
  try {
    if (projectId) window.localStorage.setItem(STORAGE_KEY, projectId);
    else window.localStorage.removeItem(STORAGE_KEY);
  } catch {
    // Ignore storage failures; selection still works in-memory.
  }
}

export function useStudioWorkbenchProject() {
  const [projects, setProjects] = useState<any[]>([]);
  const [projectId, setProjectId] = useState<string>(readStoredProjectId);
  const [project, setProject] = useState<any>(null);

  const refreshProjects = async () => {
    const data = await apiGet("/v1/projects");
    const nextProjects = Array.isArray(data?.projects) ? data.projects : [];
    setProjects(nextProjects);
    if (!nextProjects.length) {
      setProjectId("");
      setProject(null);
      writeStoredProjectId("");
      return;
    }

    const hasCurrent = projectId && nextProjects.some((item) => String(item?.id || "") === projectId);
    const storedId = readStoredProjectId();
    const hasStored = storedId && nextProjects.some((item) => String(item?.id || "") === storedId);
    const nextProjectId = hasCurrent
      ? projectId
      : hasStored
        ? storedId
        : String(nextProjects[0]?.id || "");

    if (nextProjectId !== projectId) setProjectId(nextProjectId);
  };

  const refreshProject = async (id: string) => {
    if (!id) {
      setProject(null);
      return;
    }
    const data = await apiGet(`/v1/projects/${id}`);
    setProject(data?.project || null);
  };

  useEffect(() => {
    refreshProjects().catch(() => {});
  }, []);

  useEffect(() => {
    writeStoredProjectId(projectId);
    if (projectId) refreshProject(projectId).catch(() => {});
    else setProject(null);
  }, [projectId]);

  return { projects, projectId, setProjectId, project, refreshProjects, refreshProject };
}
