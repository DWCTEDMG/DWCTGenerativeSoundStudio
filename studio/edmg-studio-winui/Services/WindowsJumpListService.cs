using EdmgStudio.Core.Models;
using Windows.UI.StartScreen;

namespace EdmgStudio.WinUI.Services;

internal static class WindowsJumpListService
{
    private const int MaximumProjectItems = 8;

    public static async Task SynchronizeProjectsAsync(IEnumerable<ProjectDto> projects)
    {
        try
        {
            if (!JumpList.IsSupported())
            {
                return;
            }

            JumpList jumpList = await JumpList.LoadCurrentAsync();
            jumpList.SystemGroupKind = JumpListSystemGroupKind.Recent;
            jumpList.Items.Clear();

            foreach (ProjectDto project in projects.Take(MaximumProjectItems))
            {
                if (string.IsNullOrWhiteSpace(project.Id))
                {
                    continue;
                }

                JumpListItem item = JumpListItem.CreateWithArguments(
                    StudioLaunchRequest.ForProject(project.Id),
                    string.IsNullOrWhiteSpace(project.Name) ? "Untitled project" : project.Name);
                item.GroupName = "Recent projects";
                item.Description = "Open this project in EDMG Studio";
                jumpList.Items.Add(item);
            }

            await jumpList.SaveAsync();
        }
        catch (Exception exception)
        {
            CrashLogger.Write("Windows jump-list synchronization is unavailable.", exception);
        }
    }
}
