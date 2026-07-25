export function hasProjectId(projects: any[], projectId: string): boolean {
  return Boolean(projectId) && projects.some((item) => String(item?.id || "") === projectId);
}

export function resolveProjectId(projects: any[], currentProjectId: string): string {
  if (!projects.length) return "";
  return hasProjectId(projects, currentProjectId) ? currentProjectId : String(projects[0]?.id || "");
}
