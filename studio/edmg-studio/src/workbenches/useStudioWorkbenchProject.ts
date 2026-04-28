import { useEffect, useState } from "react";
import { apiGet } from "../components/api";
import { hasProjectId, resolveProjectId } from "../components/projectSelection";
import { useStudioSession } from "../components/studioSession";

export function useStudioWorkbenchProject() {
  const [projects, setProjects] = useState<any[]>([]);
  const [project, setProject] = useState<any>(null);
  const [projectsReady, setProjectsReady] = useState(false);
  const { projectId, setProjectId, selectedVariant, setSelectedVariant } = useStudioSession();
  const activeProjectId = projectsReady && hasProjectId(projects, projectId) ? projectId : "";

  const refreshProjects = async () => {
    const data = await apiGet("/v1/projects");
    const nextProjects = Array.isArray(data?.projects) ? data.projects : [];
    setProjects(nextProjects);
    setProjectsReady(true);
    const nextProjectId = resolveProjectId(nextProjects, projectId);
    if (nextProjectId !== projectId) setProjectId(nextProjectId);
    if (!nextProjectId) setProject(null);
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
    if (!projectsReady) return;
    if (activeProjectId) refreshProject(activeProjectId).catch(() => {});
    else setProject(null);
  }, [activeProjectId, projectsReady]);

  return {
    projects,
    projectId: activeProjectId,
    setProjectId,
    selectedVariant,
    setSelectedVariant,
    project,
    refreshProjects,
    refreshProject,
  };
}
