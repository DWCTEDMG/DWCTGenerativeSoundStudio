using System.Text.Json;
using System.Text.Json.Nodes;
using EdmgStudio.Core.Models;

namespace EdmgStudio.Core.Tests;

[TestClass]
public sealed class ProjectTimelineOperationsTests
{
    [TestMethod]
    public void AddAndReorderTrack_ReturnImmutableProjectAndBackendCompatibleOperations()
    {
        CanonicalProject original = CreateProject();

        ProjectTimelineMutation added = ProjectTimelineOperations.AddTrack(original, "audio", "audio", "Dialogue");
        ProjectTimelineMutation reordered = ProjectTimelineOperations.ReorderTrack(added.Project, "audio", 0);

        Assert.HasCount(1, original.Tracks);
        Assert.AreEqual("audio", added.Project.Tracks[1].Id);
        Assert.AreEqual("audio", added.Operation["track_type"]!.GetValue<string>());
        Assert.AreEqual("audio", reordered.Project.Tracks[0].Id);
        Assert.AreEqual(0, reordered.Project.Tracks[0].Order);
        Assert.AreEqual(1, reordered.Project.Tracks[1].Order);
        Assert.AreEqual(0, reordered.Operation["index"]!.GetValue<int>());
    }

    [TestMethod]
    public void SetTrackState_PreservesRoutingMetadataAndEmitsOnlyRequestedValues()
    {
        CanonicalProject original = CreateProject();

        ProjectTimelineMutation mutation = ProjectTimelineOperations.SetTrackState(
            original,
            "video",
            muted: true,
            solo: false,
            recordArmed: true,
            inputMonitoring: true);

        Track track = mutation.Project.Tracks.Single();
        Assert.IsTrue(track.Muted);
        Assert.IsFalse(track.Solo);
        Assert.IsTrue(track.RecordArmed);
        Assert.IsTrue(track.InputMonitoring);
        Assert.AreEqual("main", track.Metadata["routing"]!["bus"]!.GetValue<string>());
        Assert.IsNull(mutation.Operation["locked"]);
        Assert.IsTrue(mutation.Operation["muted"]!.GetValue<bool>());
        Assert.IsFalse(mutation.Operation["solo"]!.GetValue<bool>());

        JsonObject rebuilt = ProjectTimelineContracts.RebuildTimeline(mutation.Project);
        Assert.AreEqual("main", rebuilt["tracks"]![0]!["routing"]!["bus"]!.GetValue<string>());
        Assert.IsTrue(rebuilt["tracks"]![0]!["record_armed"]!.GetValue<bool>());
    }

    [TestMethod]
    public void Operations_RejectDuplicateIdsAndInvalidRequests()
    {
        CanonicalProject project = CreateProject();

        Assert.Throws<InvalidOperationException>(() => ProjectTimelineOperations.AddTrack(project, "video", "audio"));
        Assert.Throws<ArgumentOutOfRangeException>(() => ProjectTimelineOperations.AddTrack(project, "new", "unsupported"));
        Assert.Throws<ArgumentOutOfRangeException>(() => ProjectTimelineOperations.ReorderTrack(project, "video", 1));
        Assert.Throws<ArgumentException>(() => ProjectTimelineOperations.SetTrackState(project, "video"));
    }

    [TestMethod]
    public void LockedTrack_AllowsOnlyUnlockBeforeOtherStateChanges()
    {
        CanonicalProject project = CreateProject();
        CanonicalProject locked = ProjectTimelineOperations.SetTrackState(project, "video", locked: true).Project;

        Assert.Throws<InvalidOperationException>(() => ProjectTimelineOperations.ReorderTrack(locked, "video", 0));
        Assert.Throws<InvalidOperationException>(() => ProjectTimelineOperations.SetTrackState(locked, "video", muted: true));
        Assert.Throws<InvalidOperationException>(() =>
            ProjectTimelineOperations.SetTrackState(locked, "video", locked: false, muted: true));

        CanonicalProject unlocked = ProjectTimelineOperations.SetTrackState(locked, "video", locked: false).Project;
        Assert.IsFalse(unlocked.Tracks.Single().Locked);
    }

    private static CanonicalProject CreateProject()
    {
        ProjectDto dto = JsonSerializer.Deserialize<ProjectDto>(
            """
            {"id":"project","name":"Project","revision":3,"schema_version":1,"meta":{"timeline":{
              "timebase":{"sample_rate":48000,"frame_rate":{"numerator":30,"denominator":1}},
              "tracks":[{"id":"video","name":"Picture","type":"video","routing":{"bus":"main"},
                "clips":[{"id":"clip","start_sample":"0","end_sample":"48000"}]}]
            }}}
            """,
            StudioJson.Options)!;
        return dto.CanonicalProject;
    }
}
