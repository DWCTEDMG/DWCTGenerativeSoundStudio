import { useEffect, useState } from "react";
import { apiGet } from "../components/api";
import { useStudioSession } from "../components/studioSession";

export function useStudioWorkbenchProject() {
  const [projects, setProjects] = useState<any[]>([]);
  const [project, setProject] = useState<any>(null);
  const { projectId, setProjectId, selectedVariant, setSelectedVariant } = useStudioSession();

  const refreshProjects = async () => {
    const data = await apiGet("/v1/projects");
    const nextProjects = Array.isArray(data?.projects) ? data.projects : [];
    setProjects(nextProjects);
    if (!nextProjects.length) {
      setProjectId("");
      setProject(null);
      return;
    }

    const hasCurrent = projectId && nextProjects.some((item) => String(item?.id || "") === projectId);
    const nextProjectId = hasCurrent ? projectId : String(nextProjects[0]?.id || "");

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
    if (projectId) refreshProject(projectId).catch(() => {});
    else setProject(null);
  }, [projectId]);

  return {
    projects,
    projectId,
    setProjectId,
    selectedVariant,
    setSelectedVariant,
    project,
    refreshProjects,
    refreshProject,
  };
}
