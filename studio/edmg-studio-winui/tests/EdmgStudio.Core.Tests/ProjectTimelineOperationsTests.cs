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

    [TestMethod]
    public void EventOperations_PreserveExactSamplesAndSourcePhase()
    {
        CanonicalProject project = CreateProject(
            "\"start_sample\":\"9007199254740993\",\"end_sample\":\"9007199254788993\"," +
            "\"data\":{\"name\":\"Shot\",\"source_sample_rate\":44100,\"source_offset_sample\":\"10\",\"source_offset_remainder\":\"1/3\",\"speed\":2}");
        long splitSample = 9007199254748993;

        ProjectTimelineMutation split = ProjectTimelineOperations.SplitEvent(
            project, "video", "clip", new TimelinePosition(splitSample), "right");

        TimelineEvent left = split.Project.Tracks.Single().Events[0];
        TimelineEvent right = split.Project.Tracks.Single().Events[1];
        Assert.AreEqual(splitSample, left.End.Samples);
        Assert.AreEqual(splitSample, right.Start.Samples);
        Assert.AreEqual(14710, right.Source!.Start.Samples);
        Assert.AreEqual("1/3", right.Source.Start.Remainder);
        Assert.AreEqual("9007199254748993", split.Operation["position"]!.GetValue<string>());
        Assert.AreEqual("right", split.Operation["new_id"]!.GetValue<string>());

        ProjectTimelineMutation trimmed = ProjectTimelineOperations.TrimEvent(
            split.Project, "video", "right", "start", new TimelinePosition(splitSample + 1));
        Assert.AreEqual(14712, trimmed.Project.Tracks.Single().Events[1].Source!.Start.Samples);
        Assert.AreEqual("41/240", trimmed.Project.Tracks.Single().Events[1].Source!.Start.Remainder);
        Assert.AreEqual(10, project.Tracks.Single().Events.Single().Source!.Start.Samples);
    }

    [TestMethod]
    public void EventOperations_RejectLockedInvalidAndDuplicateChanges()
    {
        CanonicalProject project = CreateProject();
        CanonicalProject locked = ProjectTimelineOperations.SetTrackState(project, "video", locked: true).Project;

        Assert.Throws<InvalidOperationException>(() =>
            ProjectTimelineOperations.MoveEvent(locked, "video", "clip", new TimelinePosition(1)));
        Assert.Throws<ArgumentOutOfRangeException>(() =>
            ProjectTimelineOperations.TrimEvent(project, "video", "clip", "start", new TimelinePosition(48_000)));
        Assert.Throws<InvalidOperationException>(() =>
            ProjectTimelineOperations.SplitEvent(project, "video", "clip", new TimelinePosition(24_000), "video"));
    }

    [TestMethod]
    public void Markers_RoundTripAndEmitBackendCompatibleOperations()
    {
        CanonicalProject project = CreateProject();
        ProjectTimelineMutation added = ProjectTimelineOperations.AddMarker(
            project, "chorus", "Chorus", new TimelinePosition(96_000), "#FF00FF");
        ProjectTimelineMutation moved = ProjectTimelineOperations.MoveMarker(
            added.Project, "chorus", new TimelinePosition(72_000));

        JsonObject rebuilt = ProjectTimelineContracts.RebuildTimeline(moved.Project);
        Assert.AreEqual("72000", rebuilt["markers"]![0]!["position_sample"]!.GetValue<string>());
        Assert.AreEqual("move_marker", moved.Operation["kind"]!.GetValue<string>());
        Assert.AreEqual("72000", moved.Operation["position"]!.GetValue<string>());
        Assert.IsEmpty(ProjectTimelineOperations.DeleteMarker(moved.Project, "chorus").Project.Markers);
        Assert.Throws<InvalidOperationException>(() =>
            ProjectTimelineOperations.AddMarker(project, "clip", "Duplicate", new TimelinePosition(0)));
        CanonicalProject withMarker = ProjectTimelineOperations.AddMarker(
            project, "marker-id", "Marker", new TimelinePosition(0)).Project;
        Assert.Throws<InvalidOperationException>(() =>
            ProjectTimelineOperations.AddTrack(withMarker, "marker-id", "video"));
    }

    [TestMethod]
    public void Snap_UsesExactFrameAndFractionalBeatGrids()
    {
        var timebase = new ProjectTimebase(48_000, new FrameRate(30_000, 1_001));

        Assert.AreEqual(1602, ProjectTimelineOperations.Snap(
            timebase, new TimelinePosition(1601), TimelineSnapMode.Frame).Samples);
        Assert.AreEqual(24_000, ProjectTimelineOperations.Snap(
            timebase, new TimelinePosition(23_999), TimelineSnapMode.Beat, 120).Samples);
        Assert.AreEqual(16_000, ProjectTimelineOperations.Snap(
            timebase, new TimelinePosition(15_999), TimelineSnapMode.HalfBeat, 90).Samples);
        Assert.AreEqual(6_000, ProjectTimelineOperations.Snap(
            timebase, new TimelinePosition(6_000), TimelineSnapMode.QuarterBeat, 120).Samples);
        Assert.AreEqual(23_976, ProjectTimelineOperations.Snap(
            timebase, new TimelinePosition(24_000), TimelineSnapMode.Beat, 120.12m).Samples);
        Assert.AreEqual(24_000, ProjectTimelineOperations.Snap(
            timebase, new TimelinePosition(12_000), TimelineSnapMode.Beat, 120).Samples);
        Assert.Throws<ArgumentOutOfRangeException>(() => ProjectTimelineOperations.Snap(
            timebase, new TimelinePosition(1), TimelineSnapMode.Beat, 0));
        Assert.Throws<ArgumentOutOfRangeException>(() => ProjectTimelineOperations.Snap(
            timebase, new TimelinePosition(1), TimelineSnapMode.Beat, -1));
    }

    private static CanonicalProject CreateProject(
        string clipJson = "\"start_sample\":\"0\",\"end_sample\":\"48000\"")
    {
        ProjectDto dto = JsonSerializer.Deserialize<ProjectDto>(
            "{\"id\":\"project\",\"name\":\"Project\",\"revision\":3,\"schema_version\":1,\"meta\":{\"timeline\":{" +
            "\"timebase\":{\"sample_rate\":48000,\"frame_rate\":{\"numerator\":30,\"denominator\":1}}," +
            "\"tracks\":[{\"id\":\"video\",\"name\":\"Picture\",\"type\":\"video\",\"routing\":{\"bus\":\"main\"}," +
            "\"clips\":[{\"id\":\"clip\"," + clipJson + "}]}]}}}",
            StudioJson.Options)!;
        return dto.CanonicalProject;
    }
}
