using System.Text.Json;
using EdmgStudio.Core.Models;

namespace EdmgStudio.Core.Tests;

[TestClass]
public sealed class DashboardProjectCardTests
{
    private static readonly DateTimeOffset Now = new(2026, 9, 11, 12, 0, 0, TimeSpan.Zero);

    [TestMethod]
    public void Create_ProjectsReadyMetadataAndLatestArtwork()
    {
        ProjectDto project = ReadProject("""
            {
              "id":"project-a","name":"Aurora","created_at":"2026-09-10T10:00:00Z",
              "updated_at":"2026-09-11T10:00:00Z","meta":{
                "audio":{"filename":"song.wav"},
                "analysis":{"features":{"duration_s":125.4}},
                "last_plan":{"variants":[{"index":0,"scenes":[]}]}
              }
            }
            """);
        StudioJob render = ReadJob("""
            {"id":"render-1","project_id":"project-a","type":"timeline_render","status":"succeeded",
             "created_at":"2026-09-11T10:20:00Z","finished_at":"2026-09-11T10:30:00Z"}
            """);
        using JsonDocument outputs = JsonDocument.Parse("""
            {"images":[
              {"name":"old.png","path":"outputs/old.png","modified_at":10},
              {"name":"new.png","path":"outputs/new.png","modified_at":20}
            ]}
            """);

        DashboardProjectCard card = DashboardProjectCard.Create(project, [render], outputs.RootElement, Now);

        Assert.AreEqual("Aurora", card.Name);
        Assert.AreEqual("2:05", card.DurationLabel);
        Assert.AreEqual(DashboardProjectHealth.Ready, card.Health);
        Assert.AreEqual("Succeeded · Updated 1h ago", card.LastRenderLabel);
        Assert.AreEqual("outputs/new.png", card.ArtworkPath);
        Assert.IsTrue(card.HasRender);
        Assert.HasCount(28, card.Waveform);
    }

    [TestMethod]
    public void Create_PrioritizesFailedRenderHealthAndHandlesMissingMetadata()
    {
        ProjectDto project = ReadProject("""
            {"id":"project-b","name":"","created_at":"2026-09-01T10:00:00Z","updated_at":"","meta":{}}
            """);
        StudioJob render = ReadJob("""
            {"id":"render-2","project_id":"project-b","type":"internal_video","status":"failed",
             "created_at":"2026-09-11T11:55:00Z","error":"encoder failed"}
            """);

        DashboardProjectCard card = DashboardProjectCard.Create(project, [render], default, Now);

        Assert.AreEqual("Untitled project", card.Name);
        Assert.AreEqual("Duration pending", card.DurationLabel);
        Assert.AreEqual(DashboardProjectHealth.Attention, card.Health);
        Assert.AreEqual("Failed · Updated 5m ago", card.LastRenderLabel);
        Assert.IsNull(card.ArtworkPath);
    }

    [TestMethod]
    public void Create_ReportsTheNextRequiredWorkflowStep()
    {
        ProjectDto audioOnly = ReadProject("""
            {"id":"audio","name":"Audio","created_at":"2026-09-11T12:00:00Z","updated_at":"2026-09-11T12:00:00Z",
             "meta":{"audio":{"filename":"track.wav"}}}
            """);
        ProjectDto analyzed = ReadProject("""
            {"id":"analyzed","name":"Analyzed","created_at":"2026-09-11T12:00:00Z","updated_at":"2026-09-11T12:00:00Z",
             "meta":{"audio":{"filename":"track.wav"},"analysis":{"features":{"duration_s":10}}}}
            """);

        Assert.AreEqual(DashboardProjectHealth.NeedsAnalysis, DashboardProjectCard.Create(audioOnly, now: Now).Health);
        Assert.AreEqual(DashboardProjectHealth.NeedsPlan, DashboardProjectCard.Create(analyzed, now: Now).Health);
    }

    private static ProjectDto ReadProject(string json) =>
        JsonSerializer.Deserialize<ProjectDto>(json, StudioJson.Options)!;

    private static StudioJob ReadJob(string json) =>
        JsonSerializer.Deserialize<StudioJob>(json, StudioJson.Options)!;
}

[TestClass]
public sealed class StudioLaunchRequestTests
{
    [TestMethod]
    public void ProjectArguments_RoundTripReservedCharacters()
    {
        string arguments = StudioLaunchRequest.ForProject("project / 42");

        StudioLaunchRequest? request = StudioLaunchRequest.Parse(arguments);

        Assert.IsNotNull(request);
        Assert.AreEqual("project / 42", request.ProjectId);
        Assert.AreEqual("workspace", request.Destination);
    }

    [TestMethod]
    [DataRow(null)]
    [DataRow("")]
    [DataRow("--other=value")]
    [DataRow("--project=")]
    public void Parse_IgnoresUnsupportedOrIncompleteArguments(string? arguments)
    {
        Assert.IsNull(StudioLaunchRequest.Parse(arguments));
    }
}
