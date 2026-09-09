using EdmgStudio.Core.Models;

namespace EdmgStudio.WinUI.Pages;

public sealed class WorkspaceCreativeDirectionSceneItem(CreativeDirectionSceneDto scene)
{
    public int Index { get; } = scene.Index;
    public string Timing { get; } = $"Scene {scene.Index + 1} · {scene.StartSeconds:0.00}s – {scene.EndSeconds:0.00}s";
    public string Name { get; set; } = scene.Name;
    public string Prompt { get; set; } = scene.Prompt;
    public string CameraHint { get; set; } = scene.CameraHint;
    public string MotionHint { get; set; } = scene.MotionHint;
    public string DirectorMode { get; set; } = scene.DirectorMode;

    public CreativeDirectionSceneOverride ToOverride() =>
        new(Index, Name.Trim(), Prompt.Trim(), CameraHint.Trim(), MotionHint.Trim(), DirectorMode.Trim());
}
