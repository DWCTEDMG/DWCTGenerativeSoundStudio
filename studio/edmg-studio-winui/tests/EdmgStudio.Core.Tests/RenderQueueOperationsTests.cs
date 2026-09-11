using System.Text.Json;
using EdmgStudio.Core.Models;

namespace EdmgStudio.Core.Tests;

[TestClass]
public sealed class RenderQueueOperationsTests
{
    private static readonly DateTimeOffset Now = new(2026, 9, 11, 12, 0, 0, TimeSpan.Zero);

    [TestMethod]
    public void Create_RunningJobProjectsProgressEtaAndDestination()
    {
        StudioJob job = ReadJob("""
            {"id":"job-123456789","project_id":"project-a","type":"internal_video","status":"running",
             "created_at":"2026-09-11T11:00:00Z","started_at":"2026-09-11T11:50:00Z","priority":50,
             "progress":{"percent":25,"stage":"frames","message":"Rendering frames","current":30,"total":120},
             "payload":{"output_path":"outputs/final.mp4"}}
            """);

        RenderQueueJobSummary summary = RenderQueueJobSummary.Create(job, Now);

        Assert.AreEqual("internal video · job-1234", summary.Title);
        Assert.AreEqual("Rendering frames", summary.StageLabel);
        Assert.AreEqual("25% · 30/120", summary.ProgressLabel);
        Assert.AreEqual("ETA 30:00", summary.EtaLabel);
        Assert.AreEqual("Elapsed 10:00", summary.ElapsedLabel);
        Assert.AreEqual("High", summary.PriorityLabel);
        Assert.AreEqual("outputs/final.mp4", summary.DestinationLabel);
        Assert.AreEqual(RenderQueueHealth.Active, summary.Health);
        Assert.IsTrue(summary.Matches(RenderQueueFilter.Active));
    }

    [TestMethod]
    public void Create_FailedInternalJobProvidesRecoveryGuidance()
    {
        StudioJob job = ReadJob("""
            {"id":"failed","project_id":"project-a","type":"internal_video","status":"failed",
             "created_at":"2026-09-11T11:00:00Z","error":"encoder failed","priority":100}
            """);

        RenderQueueJobSummary summary = RenderQueueJobSummary.Create(job, Now);

        Assert.AreEqual(RenderQueueHealth.Attention, summary.Health);
        Assert.AreEqual("Urgent", summary.PriorityLabel);
        StringAssert.Contains(summary.Recommendation, "resume from checkpoint");
        Assert.IsTrue(summary.Matches(RenderQueueFilter.Attention));
        Assert.IsFalse(summary.Matches(RenderQueueFilter.Completed));
    }

    [TestMethod]
    public void Snapshot_AggregatesQueueOperationalState()
    {
        StudioJob[] jobs =
        [
            ReadJob("""{"id":"run","project_id":"p","type":"render","status":"running","progress":{"percent":50}}"""),
            ReadJob("""{"id":"wait","project_id":"p","type":"render","status":"queued","progress":{"percent":0}}"""),
            ReadJob("""{"id":"done","project_id":"p","type":"render","status":"succeeded","progress":{"percent":100}}"""),
            ReadJob("""{"id":"fail","project_id":"p","type":"render","status":"failed"}""")
        ];

        RenderQueueSnapshot snapshot = RenderQueueSnapshot.Create(jobs);

        Assert.AreEqual(4, snapshot.TotalCount);
        Assert.AreEqual(2, snapshot.ActiveCount);
        Assert.AreEqual(1, snapshot.RunningCount);
        Assert.AreEqual(1, snapshot.QueuedCount);
        Assert.AreEqual(1, snapshot.CompletedCount);
        Assert.AreEqual(1, snapshot.AttentionCount);
        Assert.AreEqual(25, snapshot.ActiveProgress);
        Assert.AreEqual("1 running · 1 waiting · 25% average", snapshot.Summary);
    }

    private static StudioJob ReadJob(string json) =>
        JsonSerializer.Deserialize<StudioJob>(json, StudioJson.Options)!;
}
